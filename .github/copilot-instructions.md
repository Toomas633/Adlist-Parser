## Copilot guide: Adlist-Parser

Purpose: Fetch, normalize, and merge 50+ adlists into two outputs for DNS blockers (Pi-hole/AdGuard) using only the Python stdlib. Typical run: ~50–60s, ~1.6M entries.

## Architecture & flow

- Orchestrator: `adparser/cli.py::main()` runs two pipelines concurrently via `asyncio.gather()`:
  - Adlist → `output/adlist.txt`
  - Whitelist → `output/whitelist.txt`
- Stages per pipeline (heavy work off the loop via `asyncio.to_thread()`; live progress via `status.GroupedStatusDisplay`):
  1.  `io.load_sources(JSON)` → List[Source] (resolves relative file paths relative to the JSON file)
  2.  `fetcher.fetch(sources)` → List[(label, lines)] + `failed_sources` (ThreadPoolExecutor, max 16)
  3.  `content.generate_list(...)` → `(domains, abp_rules, failed_sources)`
  4.  `io.write_output(path, sorted(set(domains+abp)))` with LF endings
  5.  Post-process: `content.separate_blocklist_whitelist(adlist, whitelist)`
  6.  Redundancy: `redundancy.generate_redundancy_report(...)` + final summary `reporting.generate_report(...)`

Key modules (single-responsibility):

- `adparser/content.py` — normalization, ABP handling, regex conversion, dedupe rules
- `adparser/fetcher.py` — concurrent HTTP/local fetch with UA, progress callback
- `adparser/io.py` — JSON loaders, path resolution, LF-only writers
- `adparser/status.py` — spinners and grouped status lines
- `adparser/redundancy.py` — duplicate/overlap analysis per-source
- `adparser/reporting.py` — emoji summary and output footer
- `adparser/constants.py` — default paths (data/_, output/_)

## Conventions that matter here

- Only stdlib; keep the event loop clean: wrap I/O/CPU in `to_thread()`.
- Progress: allocate a spinner line per concurrent stage via `GroupedStatusDisplay.allocate_line()`; update via callbacks from `fetch()`.
- Outputs are large: write with `newline="\n"`; avoid loading whole files unless necessary.
- Dedup: preserve first occurrence order during normalization, then final output is sorted case-insensitively.
- Source config: `io.load_sources` accepts list or object keys: `lists`, `urls`, `adlists`, `sources`; relative paths resolve against the JSON file’s folder.

Content rules (what gets kept/converted):

- Hosts line: `0.0.0.0 example.com` → `example.com`
- Plain/wildcard domains: `example.com`, `*.sub.domain` kept as domain tokens (wildcard not expanded)
- ABP allow/block: `@@||example.com^` → whitelist entry; `||example.com^` → adlist entry (options `$...` stripped; element-hiding `##` dropped)
- ABP cleanup (conservative): `||*cdn.site^` → `||*.cdn.site^`; `||app.*.adjust.com^` → `||*.adjust.com^`; `||domain.google.*^` → `||domain.google^`;
  missing pipes normalized (e.g., `@@|domain.com^|` → `@@||domain.com^`)
- Regex to ABP: simple anchored Pi-hole patterns like `(^|\.)domain\.com$` → `||domain.com^`; complex/JS-like regex are discarded

## Run and verify

- Local run (repo checkout): `python -m adparser` → writes `output/adlist.txt` and `output/whitelist.txt` and prints an emoji summary.
- Look for `# ERROR fetching …` markers and the “UNAVAILABLE SOURCES” section in the summary.
- If packaged, an entry point named `adlist-parser` may be available; for this repo, prefer `python -m adparser`.

## When editing or adding features

- Parsing/normalization changes live in `content.py` (`normalize_lines_split`, `_normalize_abp_wildcards`, `_convert_regex_to_abp`, `separate_blocklist_whitelist`). Keep behavior conservative and DNS-focused.
- Networking tweaks belong in `fetcher.py` (keep worker cap ≈16 and progress callback API stable).
- Any new CLI/status work should use `status.GroupedStatusDisplay` for consistent UX.
- Keep LF endings and IDN handling (`idna`) semantics in `content._maybe_extract_domain` intact.

Examples you’ll use often:

- `||*cdn.example.com^` → `||*.cdn.example.com^`
- `/^(?:[a-z0-9-]+\.)*bad\.site$/` → `||bad.site^` (convertible)
- `example.com # inline` → `example.com`
- `<div>html</div>` → dropped
