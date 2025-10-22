"""Human-readable reporting utilities for CLI summary output."""

from shutil import get_terminal_size
from time import time
from unicodedata import east_asian_width

from .constants import ADLIST_OUTPUT, WHITELIST_OUTPUT
from .models import Source


def _report_width() -> int:
    """Determine report width based on terminal size with sane bounds.

    Uses the current terminal width when available; falls back to 80 columns.
    Clamps between 60 and 160 to keep the layout readable across environments.
    """
    try:
        cols = get_terminal_size(fallback=(80, 24)).columns
    except OSError:
        cols = 80
    return max(60, min(160, cols))


def _parse_summary(result: tuple[int, int, int, int, list[Source], list[str]]):
    """Normalize a result tuple into a dict for easier access.

    Keys: sources, entries, domains, abp, failed, redundancy.
    """
    return {
        "sources": result[0],
        "entries": result[1],
        "domains": result[2],
        "abp": result[3],
        "failed": result[4],
        "redundancy": result[5],
    }


def generate_report(
    adlist_result: tuple[int, int, int, int, list[Source], list[str]],
    whitelist_result: tuple[int, int, int, int, list[Source], list[str]],
    start_time: float,
):
    """Print a formatted summary report for adlist and whitelist processing."""
    ad = _parse_summary(adlist_result)
    wl = _parse_summary(whitelist_result)

    elapsed = time() - start_time

    width = _report_width()
    print("=" * width)
    print(f"🎉 ALL PROCESSING COMPLETED IN {elapsed:.2f} SECONDS! 🎉")
    print("=" * width)

    print("📊 RESULTS SUMMARY:")
    print("┌" + "─" * (_report_width() - 2) + "┐")
    _generate_line(
        f"🛡️  ADLIST: {ad['sources']:>2} sources → {ad['entries']:>7} entries"
    )
    _generate_line(f"  📝 Domains: {ad['domains']:>7} | 🔷 ABP rules: {ad['abp']:>7}")
    if ad["failed"]:
        _generate_report_sources(ad["failed"])
    for line in ad["redundancy"]:
        _generate_line(line)

    print("├" + "─" * (_report_width() - 2) + "┤")

    _generate_line(
        f"✅ WHITELIST: {wl['sources']:>2} sources → {wl['entries']:>7} entries"
    )
    _generate_line(f"  📝 Domains: {wl['domains']:>7} | 🔷 ABP rules: {wl['abp']:>7}")
    for line in wl["redundancy"]:
        _generate_line(line)

    if wl["failed"]:
        _generate_report_sources(wl["failed"])

    print("├" + "─" * (_report_width() - 2) + "┤")

    _generate_line("📁 Output files:")
    _generate_line(f"  • {ADLIST_OUTPUT}")
    _generate_line(f"  • {WHITELIST_OUTPUT}")

    print("└" + "─" * (_report_width() - 2) + "┘")


def _generate_report_sources(failed_sources: list[Source]):
    """Print a formatted section listing failed sources."""
    _generate_line(f"⚠️  UNAVAILABLE SOURCES: {len(failed_sources)}")
    for source in failed_sources:
        if source.is_url():
            _generate_line(f"  🌐 {source.raw}")
        else:
            _generate_line(f"  📄 {source.raw}")


def _generate_line(message: str):
    """Print a single framed line honoring terminal width and wide chars."""
    width = _report_width()
    display_width = _get_display_width(message) + 4
    padding = max(0, width - display_width)
    line = f"│ {message}" + " " * padding + " │"
    print(line)


def _get_display_width(text: str) -> int:
    """Return printable width, accounting for wide glyphs and emoji variants."""
    width = 0
    i = 0
    while i < len(text):
        char = text[i]
        if i < len(text) - 1 and ord(text[i + 1]) == 0xFE0F:
            width += 1
            i += 2
        elif east_asian_width(char) in ('F', 'W'):
            width += 2
            i += 1
        else:
            width += 1
            i += 1
    return width
