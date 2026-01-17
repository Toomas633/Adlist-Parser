"""Remove local entries covered by remote sources.

Uses redundancy analysis to remove entries in data/blacklist.txt (and
optionally data/whitelist.txt) that are already covered by remote sources.

Usage:
  C:/GitHub/Adlist-Parser/.venv/Scripts/python.exe scripts/remove_covered_entries.py

Optional flags:
  --whitelist  Also remove covered entries from data/whitelist.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List

from adparser.content import normalize_lines_split
from adparser.fetcher import fetch
from adparser.io import load_sources
from adparser.redundancy import _analyze_redundancy

ROOT = Path(__file__).resolve().parents[1]


def _get_covered_entries(json_path: str, local_filename: str) -> set[str]:
    sources = load_sources(str(ROOT / json_path))
    results, failed = fetch(sources, lambda _c, _t: None)
    _, local_redundancy = _analyze_redundancy(results, failed, sources)
    return local_redundancy.get(local_filename, (set(), 0))[0]


def _filter_lines(lines: Iterable[str], covered: set[str]) -> tuple[List[str], int]:
    kept: List[str] = []
    removed = 0

    for raw in lines:
        if not raw or raw.startswith('#'):
            kept.append(raw)
            continue

        domains, non_domains = normalize_lines_split([raw])
        entries = domains + non_domains
        if not entries:
            kept.append(raw)
            continue

        if all(e in covered for e in entries):
            removed += 1
            continue

        kept.append(raw)

    return kept, removed


def _write_lines(path: Path, lines: List[str]) -> None:
    path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove local entries covered by remote sources."
    )
    parser.add_argument(
        "--whitelist",
        action="store_true",
        help="Also remove covered entries from data/whitelist.txt",
    )
    args = parser.parse_args()

    blacklist_path = ROOT / "data/blacklist.txt"
    blacklist_covered = _get_covered_entries("data/adlists.json", "blacklist.txt")
    blacklist_lines = blacklist_path.read_text(encoding="utf-8").splitlines()
    blacklist_kept, blacklist_removed = _filter_lines(
        blacklist_lines, blacklist_covered
    )
    _write_lines(blacklist_path, blacklist_kept)

    if args.whitelist:
        whitelist_path = ROOT / "data/whitelist.txt"
        whitelist_covered = _get_covered_entries(
            "data/whitelists.json", "whitelist.txt"
        )
        whitelist_lines = whitelist_path.read_text(encoding="utf-8").splitlines()
        whitelist_kept, whitelist_removed = _filter_lines(
            whitelist_lines, whitelist_covered
        )
        _write_lines(whitelist_path, whitelist_kept)
    else:
        whitelist_removed = 0

    print(
        "Removed ",
        blacklist_removed,
        " covered entries from data/blacklist.txt",
        sep="",
    )
    if args.whitelist:
        print(
            "Removed ",
            whitelist_removed,
            " covered entries from data/whitelist.txt",
            sep="",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
