<img align="right" src="https://sonarcloud.io/api/project_badges/quality_gate?project=Toomas633_Adlist-Parser">

# Adlist-Parser

A high-performance Python utility that fetches and merges multiple adlists into domain-only output for DNS blockers like Pi-hole, AdGuard, and similar DNS filtering solutions.

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Installation (optional)](#installation-optional)
- [Configuration](#configuration)
- [Output Format](#output-format)
- [Performance](#performance)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [VS Code Tasks](#vs-code-tasks)
- [Redundancy Analysis](#redundancy-analysis)
- [Troubleshooting](#troubleshooting)
- [Example Output](#example-output)
- [Requirements](#requirements)
- [Use Cases](#use-cases)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

- **Fast Concurrent Processing**: Processes 1.6M+ entries from 50+ sources in ~50-60 seconds
- **Zero Dependencies**: Uses only Python standard library (3.8+)
- **Dual Output**: Generates both adlists and whitelists simultaneously
- **Smart Content Processing**: Handles domains, wildcards, regex patterns, and Pi-hole format conversions
- **ABP Filter Support**: Converts Pi-hole regex patterns to AdBlock Plus (ABP) format with automatic wildcard normalization
- **Intelligent Separation**: Automatically separates exception rules (`@@||`) from blocklist to whitelist
- **Domain Validation**: Validates and filters invalid domain entries during post-processing
- **Real-time Progress**: Animated progress spinners with detailed status updates
- **Error Resilient**: Failed fetches don't crash the pipeline; they're logged and filtered out

## Quick Start

1. **Clone the repository**:

   ```bash
   git clone https://github.com/Toomas633/Adlist-Parser.git
   cd Adlist-Parser
   ```

2. **Run the parser**:

   - From a repo checkout:
     ```bash
     python -m adparser
     ```
   - If installed as a package:
     ```bash
     adlist-parser
     ```

   On Windows PowerShell:

   ```pwsh
   python -m adparser
   # or, if installed
   adlist-parser
   ```

3. **Find your results**:
   - `output/adlist.txt` - Merged blocklist (~1.6M entries)
   - `output/whitelist.txt` - Merged whitelist (~2K entries)

## Installation (optional)

You can run from a checkout (above) or install locally to get the `adlist-parser` command:

```pwsh
# Editable install for development
python -m pip install -e .

# Then run
adlist-parser
```

## Configuration

### Input Sources

Configure your sources in JSON files:

**`data/adlists.json`** - Blocklist sources:

```json
{
  "lists": ["blacklist.txt", "old_adlist.txt"],
  "urls": [
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "https://adaway.org/hosts.txt",
    "https://v.firebog.net/hosts/AdguardDNS.txt"
  ]
}
```

**`data/whitelists.json`** - Whitelist sources:

```json
{
  "lists": ["whitelist.txt"],
  "urls": [
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/whitelist-referral.txt"
  ]
}
```

### Source Types

- **URLs**: HTTP/HTTPS links to remote lists
- **Local files**: Relative paths to files in the `data/` directory
- **Mixed format**: Each source can contain domains, wildcards, regex patterns, or Pi-hole entries

Notes:

- Path resolution: relative paths inside the JSON files are resolved relative to the JSON file location (not the CWD).
- Accepted keys: both files accept any of `lists`, `urls`, `adlists`, or `sources` for compatibility; they are merged.

## Output Format

### Supported Input Formats

The parser intelligently handles multiple input formats:

- **Plain domains**: `example.com`
- **Wildcards**: `*.example.com`
- **Pi-hole regex**: `(\.|^)example\.com$`
- **AdBlock patterns**: `/pattern/flags`
- **Host file entries**: `0.0.0.0 example.com`
- **Comments**: Lines starting with `#`, `!`, `//`, or `;`

### Output Processing

1. **Domain Extraction**: Extracts clean domains from various host file formats
2. **Wildcard Handling**: `*.domain.com` is preserved as a domain token (wildcard not expanded). In the final domain output the leading `*.` is stripped to `domain.com`.
3. **ABP Normalization**: Fixes broken ABP patterns automatically:
   - `||*cdn.domain.com^` → `||*.cdn.domain.com^` (missing dot after wildcard)
   - `||app.*.adjust.com^` → `||*.adjust.com^` (wildcard-only label removed)
   - `||domain.google.*^` → `||domain.google^` (wildcard TLD removed - not supported)
   - `-domain.com^` → `||-domain.com^` (adds missing `||` prefix)
   - `@@|domain.com^|` → `@@||domain.com^` (fixes single pipe + trailing pipe)
4. **ABP Conversion**: Pi-hole regex patterns convert to `||domain^` format when possible
5. **Blocklist/Whitelist Separation**: Automatically moves `@@||` exception entries from blocklist to whitelist
6. **Domain Validation**: Validates and removes invalid domain entries during post-processing
7. **Regex Handling**: Complex regexes that can't convert to ABP are discarded (pipeline doesn't crash)
8. **Deduplication**: Preserves first-seen order during normalization; final outputs are sorted case-insensitively during post-processing
9. **Comment Filtering**: Strips whole-line and inline comments (`#`, `!`, `//`, `;`)
10. **HTML Filtering**: Removes HTML tags and attributes from lists
11. **Error Resilience**: Failed fetches logged and filtered during normalization
12. **Adlist merge**: Adlist pipeline merges with prior `output/adlist.txt` before writing to preserve entries across transient source failures (whitelist writes directly)

#### Determinism and file format

- Outputs use LF-only line endings.
- Sorting is deterministic and case-insensitive; deduplication is case-insensitive and whitespace-trimmed.
- Headers are regenerated during post-processing (don’t hand-edit outputs).

### Output file header (sample)

Each output starts with a generated header like this:

```text
# Adlist - Generated by Adlist-Parser
# https://github.com/Toomas633/Adlist-Parser
#
# Created/modified: 2025-01-01 00:00:00 UTC
# Total entries: 1,684,272
# Domains: 400,527
# ABP-style rules: 1,283,745
# Sources processed: 50
#
# This file is automatically generated. Do not edit manually.
# To update, run: adlist-parser or python -m adparser
#
```

## Performance

- **Concurrency**: Fetches multiple sources simultaneously (max 16 workers)
- **Async Processing**: Adlists and whitelists processed in parallel
- **Memory Efficient**: Line-by-line processing for large datasets
- **Real-world Scale**: Tested with 1.6M+ entries from 50+ sources

### Tuning

- Concurrency: network fetching uses up to 16 workers (see `adparser/fetcher.py`). You can adjust the cap there if needed for your environment.
- I/O: most heavy I/O runs off the event loop using `asyncio.to_thread()`; disk speed can impact total time.
- Output size: `output/adlist.txt` can reach ~1.6–1.7M lines depending on sources.

## How It Works

Two concurrent pipelines run via `asyncio.gather()` in `adparser/cli.py`:

**Pipeline Flow** (for both adlist and whitelist):

1. **Load Sources** → Parse JSON configs and resolve paths
2. **Fetch Content** → Concurrent downloads (16 workers max)
3. **Generate List** → Normalize, categorize, and convert entries
4. **Adlist-only merge** → Merge new entries with prior `output/adlist.txt` before write (preserves previous content across transient source failures); whitelist writes directly
5. **Write Output** → Save with auto-generated headers (LF-only line endings)
6. **Post-Processing** → Separate blocklist/whitelist entries, validate domains, regenerate headers, and re-write both files
7. **Redundancy Report** → Analyze duplicates and overlaps

**Key Processing Steps**:

- All heavy I/O wrapped with `asyncio.to_thread()` to keep event loop responsive
- Progress displayed via animated spinners (`adparser/status.py`)
- Domain validation using `DOMAIN_RE` regex pattern
- Pi-hole regex → ABP conversion when patterns are simple enough
- ABP wildcard normalization fixes malformed patterns automatically
- Post-processing separates `@@||` exception entries to whitelist
- Cross-list deduplication ensures no conflicts between blocklist and whitelist
- Failed sources tracked separately and reported at end
- Files are written with LF-only line endings

## Architecture

The codebase follows a modular async architecture with strict separation of concerns:

```
adparser/cli.py           # Main orchestrator with async/await
├── adparser/io.py        # JSON parsing, path resolution, file I/O
├── adparser/fetcher.py   # Concurrent HTTP fetching (ThreadPoolExecutor)
├── adparser/content.py   # Domain extraction, normalization, regex conversion
├── adparser/models.py    # Source descriptor dataclass (URL vs local files)
├── adparser/status.py    # Progress spinners and terminal UI updates
├── adparser/reporting.py # Results summary with emoji formatting
├── adparser/redundancy.py# Duplicate detection and overlap analysis
└── adparser/constants.py # File path constants

```

**Design Principles**:

- **Single Responsibility**: Each module handles one concern (fetch/parse/write separated)
- **Error Isolation**: Failed sources don't crash the pipeline
- **Async I/O**: Heavy operations run in thread pool via `to_thread()`
- **Progress Feedback**: Global `status_display` coordinates concurrent spinners
- **Order Preservation**: Deduplication via `_dedupe_preserve_order()` before final sort

## VS Code Tasks

This repository includes ready-to-run tasks for Windows PowerShell:

- Adlist-Parser: runs the tool end-to-end (equivalent to `python -m adparser`).
- Tests: Pytest (coverage): runs `pytest` with coverage as configured in `pyproject.toml`.
- Lint: Pylint (report): runs pylint and writes `pylint-report.txt`; non-zero exit is allowed while still generating the report.

Quality gates expectations:

- Build: N/A (pure Python). Runtime entry point is `adparser.cli:main`.
- Tests: PASS on local data set; full runs may take ~50–60s.
- Lint: PASS is ideal; if not, review `pylint-report.txt`.

## Redundancy Analysis

The parser includes built-in redundancy detection to help optimize your source lists:

**Features**:

- **Duplicate Detection**: Identifies sources with identical content
- **Local File Analysis**: Shows which entries in local files are already covered by remote sources
- **Removal Suggestions**: Lists first 20 redundant entries with count of remaining

**Example Output**:

```

🔁 Duplicate sources (identical content): 2 groups
├─ 🌐 https://example.com/list1.txt
└─ 🌐 https://example.com/list2.txt
💡 Tip: Keep one source from this group, remove the others

📄 Local file redundancy analysis:
• blacklist.txt: 150/200 entries (75.0%) already in remote sources

```

## Input Format Examples

The parser intelligently processes various input formats and converts them appropriately:

| Input Format            | Processing Result                            | Notes                                     |
| ----------------------- | -------------------------------------------- | ----------------------------------------- |
| `example.com`           | → `example.com` (domain)                     | Plain domain preserved                    |
| `*.example.com`         | → `\|\|*.example.com^` (ABP rule)            | Wildcard converted to ABP                 |
| `0.0.0.0 example.com`   | → `example.com` (domain)                     | Host file format extracted                |
| `(\.\|^)example\.com$`  | → `\|\|example.com^` (ABP rule)              | Pi-hole regex converted                   |
| `/ads?/`                | → ABP rule or discarded                      | Converted if simple, discarded if complex |
| `# Comment line`        | → filtered                                   | Comment removed                           |
| `domain.com # inline`   | → `domain.com`                               | Inline comment stripped                   |
| `<div>html</div>`       | → filtered                                   | HTML tags removed                         |
| `@@\|\|exception.com^`  | → Moved to whitelist as `\|\|exception.com^` | Exception rule separated                  |
| `\|\|*cdn.example.com^` | → `\|\|*.cdn.example.com^`                   | Malformed ABP pattern normalized          |

## Troubleshooting

**Common Issues**:

- **Network Errors**: Failed sources are listed as "UNAVAILABLE SOURCES" in the final report with `🌐` (remote) or `📄` (local) indicators
- **Proxy Issues**: Configure system proxy settings or mirror remote sources locally in `data/` and update JSON configs
- **Large Files**: `output/adlist.txt` can be 30MB+; use command-line tools (`grep`, `wc -l`) for inspection
- **Slow Performance**: Check network speed; adjust worker count in `adparser/fetcher.py` (default: 16)
- **Memory Usage**: The parser uses line-by-line processing, so memory footprint stays low even with 1.6M+ entries

## FAQ

- Why are element-hiding rules (e.g., `##`, `#@?#`) missing from outputs?
  - This tool targets DNS blocklists. Element-hiding is cosmetic (browser-side), so such rules are dropped during normalization.
- Why do some regex rules disappear?
  - Only simple, anchored Pi-hole patterns are converted to ABP (`||domain^`). Complex/JS-like regex is discarded for safety and DNS relevance.
- My local file entries are already covered by remotes—how do I find them?
  - Check the redundancy section at the end of the run; it lists duplicates and local entries already provided by remote sources.

## Example Output

```
🚀 Starting Adlist-Parser...
⚡ Processing adlists and whitelists concurrently...

⚡ Adlist: Fetching content... |/-\ [48/50 (96%)]
⚡ Whitelist: Processing domains...

Adlist: ✅ Complete - 1684272 entries (400527 domains, 1283745 ABP rules)
Whitelist: ✅ Complete - 2337 entries (1346 domains, 991 ABP rules)

=== Adlists redundancy analysis ===
Analyzed 50 sources.
✅ No redundancy issues detected

============================================================
🎉 ALL PROCESSING COMPLETED IN 53.16 SECONDS! 🎉
============================================================
📊 RESULTS SUMMARY:
┌──────────────────────────────────────────────────────────┐
│ 🛡️  ADLIST:    50 sources → 1684272 entries              │
│   📝 Domains:  400527 | ABP rules: 1283745              │
├──────────────────────────────────────────────────────────┤
│ ✅ WHITELIST:  6 sources →    2337 entries               │
│   📝 Domains:    1346 | ABP rules:     991              │
├──────────────────────────────────────────────────────────┤
│ 📁 Output files:                                         │
│   • output/adlist.txt                                    │
│   • output/whitelist.txt                                 │
└──────────────────────────────────────────────────────────┘
```

## Requirements

- Python 3.8 or higher
- No external dependencies (uses only standard library)

## Use Cases

- **Pi-hole**: Use `output/adlist.txt` as a blocklist and `output/whitelist.txt` as an allowlist
- **AdGuard Home**: Import both files as custom filtering rules
- **DNS Filtering**: Any DNS-based ad blocker that supports domain lists
- **Network Security**: Corporate firewall domain blocking lists

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Make** your changes following the existing patterns:
   - Keep modules single-responsibility
   - Use `asyncio.to_thread()` for I/O operations
   - Wrap long operations with `spinner.show_progress()`
   - Add inline documentation for complex logic

- Keep runtime stdlib-only; do not add dependencies or modify `pyproject.toml` beyond `[project.optional-dependencies].dev`
- Preserve public contracts: `fetcher.fetch`, `content.generate_list`, `content.separate_blocklist_whitelist`, `io.write_output`
- Do not widen domain regex or IDN heuristics; keep `_maybe_extract_domain` and `DOMAIN_RE` conservative

4. **Test** thoroughly with `python -m adparser`
5. **Verify** output files are generated correctly
6. **Submit** a pull request with clear description

**Development Tips**:

- Read `.github/copilot-instructions.md` for architecture overview
- Check `adparser/content.py` for parsing rules and regex patterns
- Use existing regex patterns rather than adding new ones
- Maintain backward compatibility with existing JSON configs

## Fast dev loop

For quick iterations, limit sources to local files to reduce runtime:

- Edit `data/adlists.json` and `data/whitelists.json` to only include the local files:

  ```json
  { "lists": ["blacklist.txt"], "urls": [] }
  ```

  ```json
  { "lists": ["whitelist.txt"], "urls": [] }
  ```

- Add a few test lines to `data/blacklist.txt` and `data/whitelist.txt` and run:

  ```pwsh
  python -m adparser
  ```

This exercises the full pipeline (status UI, normalization, separation, reporting) in seconds.

## Acknowledgments

- Built for the DNS filtering community
- Inspired by the need for fast, reliable adlist aggregation
- Uses high-quality sources from the community (StevenBlack, Hagezi, FadeMind, and others)
