"""Conflict detection between data/blacklist.txt and data/whitelist.txt.

Reports entries that appear in both local source files so the user can
decide which file to remove them from.  Canonical comparison via
``_convert_regex_to_abp`` means that a Pi-hole regex such as
``(^|\\.)domain\\.com$`` is treated as equivalent to ``||domain.com^``.
"""

from __future__ import annotations

from pathlib import Path

from .constants import COMMENT_LINE_RE
from .content import _convert_regex_to_abp
from .reporting import _generate_line, _report_width

ROOT = Path(__file__).resolve().parents[1]
BLACKLIST_PATH = ROOT / "data" / "blacklist.txt"
WHITELIST_PATH = ROOT / "data" / "whitelist.txt"


def _canonical(entry: str) -> str:
    """Return canonical ABP form of a Pi-hole regex entry, or entry unchanged."""
    return _convert_regex_to_abp(entry) or entry


def _read_entries(path: Path) -> list[str]:
    """Return non-empty, non-comment lines from *path*."""
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not COMMENT_LINE_RE.match(line.strip())
    ]


def check_conflicts() -> list[tuple[str, str]]:
    """Return ``(blacklist_entry, whitelist_entry)`` pairs that conflict.

    Comparison is case-insensitive and canonical (Pi-hole regexes are
    converted to their ABP equivalent before matching).
    """
    blacklist = _read_entries(BLACKLIST_PATH)
    whitelist = _read_entries(WHITELIST_PATH)

    wl_map: dict[str, str] = {}
    for entry in whitelist:
        wl_map[_canonical(entry).lower()] = entry

    conflicts: list[tuple[str, str]] = []
    for entry in blacklist:
        match = wl_map.get(_canonical(entry).lower())
        if match is not None:
            conflicts.append((entry, match))

    return conflicts


def report_conflicts() -> None:
    """Print a formatted conflict report to stdout.

    Exits silently (with a short confirmation line) when no conflicts exist.
    """
    conflicts = check_conflicts()
    width = _report_width()

    if not conflicts:
        print("=" * width)
        print("✅ No conflicts between blacklist.txt and whitelist.txt")
        print("=" * width)
        return

    print("=" * width)
    count = len(conflicts)
    print(
        f"⚠️  {count} CONFLICT{'S' if count != 1 else ''} "
        "BETWEEN blacklist.txt AND whitelist.txt"
    )
    print("=" * width)
    print("┌" + "─" * (width - 2) + "┐")
    _generate_line(
        "The following entries exist in both files. "
        "Remove from one to resolve each conflict:"
    )
    print("├" + "─" * (width - 2) + "┤")
    for bl_entry, wl_entry in conflicts:
        if bl_entry == wl_entry:
            _generate_line(f"  {bl_entry}")
        else:
            _generate_line(f"  blacklist → {bl_entry}")
            _generate_line(f"  whitelist → {wl_entry}")
    print("└" + "─" * (width - 2) + "┘")
