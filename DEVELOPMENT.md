# Adlist-Parser — Development Guide

This document is the primary reference for contributors and maintainers. It covers architecture, module contracts, parsing rules, testing, linting, VS Code tasks, and contribution conventions.

## Table of Contents

- [Getting Started](#getting-started)
- [Contributing Workflow](#contributing-workflow)
- [Architecture & Flow](#architecture--flow)
- [Module Responsibilities](#module-responsibilities)
- [Stable Contracts](#stable-contracts)
- [Parsing Rules](#parsing-rules)
- [CLI Modes](#cli-modes)
- [Testing](#testing)
- [Linting](#linting)
- [VS Code Tasks](#vs-code-tasks)
- [Fast Dev Loop](#fast-dev-loop)
- [Edge Cases & Invariants](#edge-cases--invariants)
- [Contribution Conventions](#contribution-conventions)

---

## Architecture & Flow

`adparser/cli.py::main()` runs two pipelines concurrently via `asyncio.gather()`:

- **Adlist pipeline** → `output/adlist.txt`
- **Whitelist pipeline** → `output/whitelist.txt`

All heavy CPU/IO work is pushed off the event loop with `asyncio.to_thread()`. Live progress is displayed via `status.GroupedStatusDisplay`.

### Pipeline stages (both pipelines)

1. `io.load_sources(JSON)` → `List[Source]`  
   Paths are resolved relative to the JSON file's location, not the CWD.
2. `fetcher.fetch(sources, progress_cb)` → `(results, failed)`  
   Concurrent HTTP/local fetch with ≤16 workers; `progress_cb(completed, total)` called by workers.
3. `content.generate_list(results, sources, failed)` → `(domains, abp_rules, failed)`  
   Normalizes, categorises, and converts entries.
4. **Adlist only**: merge new entries with existing `output/adlist.txt` before writing, to preserve entries across transient source failures. Whitelist writes directly.
5. `io.write_output(path, lines, header)` — LF-only line endings.
6. Post-process: `content.separate_blocklist_whitelist(adlist, whitelist)` — moves `@@||` rules from adlist to whitelist, drops shadowed blocks, re-writes both files with fresh headers, entry counts, and case-insensitive sorting.
7. `redundancy.generate_redundancy_report(...)` + `reporting.generate_report(...)` — redundancy analysis and final summary.

---

## Module Responsibilities

| Module          | Responsibility                                                                                         |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| `cli.py`        | Async orchestrator; argument parsing; coordinates all stages                                           |
| `content.py`    | Domain normalization, ABP handling, Pi-hole regex → ABP conversion, deduplication                      |
| `fetcher.py`    | Concurrent HTTP and local fetch; progress callback; UA header; ≤16 workers                             |
| `io.py`         | JSON source loaders; path resolution (Windows-safe URL vs path); LF-only file writes                   |
| `models.py`     | `Source` dataclass: `raw`, `resolved_path`, `is_url()`, `is_file_url()`                                |
| `conflicts.py`  | Detect entries present in both `data/blacklist.txt` and `data/whitelist.txt`; canonical ABP comparison |
| `duplicates.py` | `--remove-duplicates` pipeline; removes local entries covered by remote sources or broader rules       |
| `status.py`     | Grouped spinners; `spinner.show_progress()` wraps async operations                                     |
| `redundancy.py` | Duplicate/overlap analysis including local-file coverage                                               |
| `reporting.py`  | Emoji summary; wide-char-safe column width calculation                                                 |
| `constants.py`  | Default `data/` inputs, `output/` paths, `cache/` dir, and all compiled regex patterns                 |

### `models.py` — `Source` dataclass

```python
@dataclass
class Source:
    raw: str                        # Original string (URL, local path, or file URI)
    resolved_path: Optional[str]    # Absolute filesystem path for local files

    def is_url(self) -> bool: ...       # True for http/https; file:// treated as local
    def is_file_url(self) -> bool: ...  # True for file:// URIs
```

---

## Stable Contracts

These function signatures are treated as public APIs. Do not change them without updating all callers.

```python
# fetcher.py
fetch(sources: List[Source], cb: Callable[[int, int], None]) -> tuple[list, list]
# cb(completed, total) is called by workers after each source finishes

# content.py
generate_list(results, sources, failed) -> tuple[list[str], list[str], list[Source]]
# returns (domains, abp_rules, failed_sources)

separate_blocklist_whitelist(adlist: list[str], whitelist: list[str]) -> tuple[list[str], list[str]]
# returns (clean_adlist, clean_whitelist)

# io.py
write_output(path: str, lines: list[str], header: str) -> None
# Always writes LF-only; headers are regenerated after post-processing
```

---

## Parsing Rules

### Hosts file entries

- `0.0.0.0 example.com` or `127.0.0.1 example.com` → `example.com`
- Leading IP (`0.0.0.0`, `127.0.0.1`, `::1`) is stripped anywhere in a hosts line; only the hostname token is kept.

### Wildcards

- `*.sub.domain` is preserved as a domain token during processing.
- The final domain output strips the leading `*.` — `*.a.b` → `a.b`.
- Wildcards are **not** expanded.

### ABP rules

| Input              | Output    | Notes                                   |
| ------------------ | --------- | --------------------------------------- | ------------------------------ | -------------------------------------------- |
| `                  |           | example.com^`                           | adlist entry                   | Plain block rule                             |
| `@@                |           | example.com^`                           | whitelist entry                | Exception rule; moved during post-processing |
| `                  |           | example.com^$option`                    | options stripped before output | `$` options removed                          |
| `example.com##.ad` | discarded | Element-hiding rules are DNS-irrelevant |

### ABP normalization (conservative)

| Malformed pattern       | Fixed pattern        | Rule                                |
| ----------------------- | -------------------- | ----------------------------------- |
| `\|\|*cdn.site^`        | `\|\|*.cdn.site^`    | Insert missing dot after wildcard   |
| `\|\|app.*.adjust.com^` | `\|\|*.adjust.com^`  | Drop wildcard-only labels           |
| `\|\|domain.google.*^`  | `\|\|domain.google^` | Remove wildcard TLD (not supported) |
| `@@\|domain.com^\|`     | `@@\|\|domain.com^`  | Fix single pipe + trailing pipe     |

Keep these conversions conservative — do not broaden them.

### Pi-hole regex → ABP

- Anchored forms like `(^|\.)domain\.com$` → `||domain.com^`
- Complex or JS-like regex is discarded (not converted). The pipeline does not crash.

### IDN / punycode

- IDN is handled via `_maybe_extract_domain` (punycode). Do not widen `DOMAIN_RE`.

### Comments & filtering

- Whole-line comments stripped: lines starting with `#`, `!`, `//`, `;`
- Inline comments stripped: trailing ` # …`, ` ! …`, etc.
- HTML/XML fragments filtered via `HTML_TAG_RE`.

---

## CLI Modes

### Default run

```pwsh
python -m adparser
# or
adlist-parser
```

Runs both pipelines and writes `output/adlist.txt` and `output/whitelist.txt`.

### `--remove-duplicates`

```pwsh
python -m adparser --remove-duplicates
```

Removes entries from `data/blacklist.txt` and `data/whitelist.txt` that are already covered by remote sources in the respective JSON config, or by broader rules within the same file. Files are modified in-place. Implemented in `duplicates.py`.

### `--check-conflicts`

```pwsh
python -m adparser --check-conflicts
```

Detects entries present in both `data/blacklist.txt` and `data/whitelist.txt`. Comparison is case-insensitive and canonical (Pi-hole regex converted to ABP before matching). Prints a report and exits without modifying any files. Implemented in `conflicts.py`.

---

## Testing

Tests live in `tests/` and use **pytest** with branch coverage. Configuration is in `pyproject.toml`.

```pwsh
# Run all tests with coverage
pytest

# Run a specific file
pytest tests/test_content.py

# Run with verbose output
pytest -v
```

Coverage is reported to the terminal (`--cov-report=term-missing`) and written to `coverage.xml`. The `--maxfail=1` flag stops the run on the first failure.

### Test files

| File                             | Coverage                                      |
| -------------------------------- | --------------------------------------------- |
| `test_cli.py`                    | CLI orchestration, argument dispatch          |
| `test_conflicts.py`              | Conflict detection logic                      |
| `test_content.py`                | Normalization, ABP handling, regex conversion |
| `test_duplicates.py`             | Duplicate/coverage removal pipeline           |
| `test_io_and_fetcher.py`         | Source loading, path resolution, fetch        |
| `test_main_entrypoint.py`        | `__main__` entry point                        |
| `test_redundancy.py`             | Redundancy report generation                  |
| `test_remove_covered_entries.py` | `--remove-duplicates` end-to-end              |

### Writing new tests

- Keep tests small and pure; avoid network calls in unit tests.
- Patch `fetcher.fetch` and `io.load_sources` for integration tests.
- Use `tmp_path` (pytest fixture) for any file I/O.

---

## Linting

```pwsh
# Run pylint and write report
pylint adparser tests > pylint-report.txt
# or via the VS Code task (see below)
```

A non-zero exit is allowed while still generating `pylint-report.txt` for review. The goal is zero warnings/errors.

---

## VS Code Tasks

All tasks target Windows PowerShell.

| Task name                    | Command                 | Notes                                           |
| ---------------------------- | ----------------------- | ----------------------------------------------- |
| **Adlist-Parser**            | `python -m adparser`    | Full end-to-end run                             |
| **Tests: Pytest (coverage)** | `pytest`                | Coverage as configured in `pyproject.toml`      |
| **Lint: Pylint (report)**    | `pylint adparser tests` | Writes `pylint-report.txt`; non-zero exit is OK |

## GitHub Actions

The `.github/workflows/update-lists.yml` workflow runs the parser and commits updated outputs automatically:

| Trigger          | Condition                                              |
| ---------------- | ------------------------------------------------------ |
| Monthly schedule | `cron: 0 3 1 * *` (03:00 UTC on the 1st of each month) |
| Push to `main`   | Only when files under `data/` are changed              |
| Manual dispatch  | `workflow_dispatch` (run from the Actions tab)         |

The job is skipped when the push actor is `github-actions[bot]` to prevent the bot's own commits from triggering a new run.

The workflow uses Git LFS to store and retrieve large files in `cache/`, `output/`, and `data/`. Git LFS must be enabled on the runner (installed by default on GitHub-hosted runners).

---

## Fast Dev Loop

For rapid iteration without downloading remote sources, restrict sources to local files:

**`data/adlists.json`**:

```json
{ "lists": ["blacklist.txt"], "urls": [] }
```

**`data/whitelists.json`**:

```json
{ "lists": ["whitelist.txt"], "urls": [] }
```

Add a handful of test lines to `data/blacklist.txt` and `data/whitelist.txt`, then run:

```pwsh
python -m adparser
```

This exercises the full pipeline (status UI, normalization, post-processing, separation, reporting) in under a second.

---

## Edge Cases & Invariants

- **Leading IPs**: stripped anywhere in a hosts line — only the hostname token is kept.
- **Wildcards**: tokens only; `*.a.b` → `a.b` in domain output; wildcards are never expanded.
- **ABP cleanup**: stay conservative; do not broaden patterns (prefer `||*.cdn.site^` over `||*cdn.site^`).
- **Regex → ABP**: only simple anchored Pi-hole forms (`(^|\.)domain\.com$`); complex regex is silently discarded.
- **Sorting**: always case-insensitive; deduplication is case-insensitive and whitespace-trimmed.
- **Line endings**: all output files use LF only; never write CRLF.
- **Network concurrency**: hard cap of ≤16 workers in `fetcher.py`.
- **Adlist merge**: the adlist pipeline always merges with the existing `output/adlist.txt` before writing, to preserve entries across transient source failures.
- **Header regeneration**: headers are regenerated during post-processing; never regenerate them mid-pipeline.
- **DOMAIN_RE**: do not widen this pattern or the IDN heuristics in `_maybe_extract_domain`.

---

## Getting Started

```pwsh
git clone https://github.com/Toomas633/Adlist-Parser.git
cd Adlist-Parser

# Install Git LFS (once per machine) and pull LFS objects
git lfs install
git lfs pull

# Editable install (adds the adlist-parser script and dev extras)
python -m pip install -e ".[dev]"

# Run the full pipeline
python -m adparser

# Run tests
pytest

# Lint
pylint adparser tests > pylint-report.txt
```

For rapid iteration see [Fast Dev Loop](#fast-dev-loop).

## Contributing Workflow

1. Fork the repository and create a feature branch (`git checkout -b feature/my-change`)
2. Make your changes following the conventions below
3. Run `pytest` and confirm all tests pass
4. Run `pylint adparser tests` and resolve any new warnings
5. Submit a pull request with a clear description of the change

## Contribution Conventions

- **stdlib-only**: never add runtime dependencies; do not change `pyproject.toml` beyond the existing `[project.optional-dependencies].dev` extras.
- **Single responsibility**: each module handles one concern; keep side effects (IO/prints) in `io.py`, `status.py`, and `cli.py`.
- **Async discipline**: push heavy CPU/IO off the event loop with `asyncio.to_thread()`; cap concurrency to ≤16 workers.
- **Stable contracts**: treat the function signatures listed under [Stable Contracts](#stable-contracts) as public APIs.
- **File format**: write LF-only files; keep deterministic case-insensitive sorting; regenerate headers only in post-processing.
- **Path handling**: maintain Windows-safe path/URL handling in `io.py`; do not break relative path resolution.
- **Tests**: add unit tests under `tests/` for any new logic; prefer small, pure functions.
- **Wide-char safety**: keep messages and summaries wide-char safe (see `reporting.py`).
- **Fetch contract**: when modifying `fetcher.py`, keep the UA header behaviour and `progress_cb` contract intact.
