from time import time
from unicodedata import east_asian_width

from .constants import ADLIST_OUTPUT, WHITELIST_OUTPUT
from .models import Source

REPORT_WIDTH = 80


def generate_report(
    adlist_result: tuple[int, int, int, int, list[Source]],
    whitelist_result: tuple[int, int, int, int, list[Source]],
    start_time: float,
):
    adlist_sources, adlist_entries, adlist_domains, adlist_abp, adlist_failed = (
        adlist_result
    )
    (
        whitelist_sources,
        whitelist_entries,
        whitelist_domains,
        whitelist_abp,
        whitelist_failed,
    ) = whitelist_result

    elapsed = time() - start_time

    print("=" * REPORT_WIDTH)
    print(f"🎉 ALL PROCESSING COMPLETED IN {elapsed:.2f} SECONDS! 🎉")
    print("=" * REPORT_WIDTH)

    print("📊 RESULTS SUMMARY:")
    print("┌" + "─" * (REPORT_WIDTH - 2) + "┐")
    _generate_line(
        f"🛡️  ADLIST: {adlist_sources:>2} sources → {adlist_entries:>7} entries"
    )
    _generate_line(f"  📝 Domains: {adlist_domains:>7} | 🔷 ABP rules: {adlist_abp:>7}")
    _generate_report_sources(adlist_failed) if adlist_failed else None

    print("├" + "─" * (REPORT_WIDTH - 2) + "┤")

    _generate_line(
        f"✅ WHITELIST: {whitelist_sources:>2} sources → {whitelist_entries:>7} entries"
    )
    _generate_line(
        f"  📝 Domains: {whitelist_domains:>7} | 🔷 ABP rules: {whitelist_abp:>7}"
    )
    _generate_report_sources(whitelist_failed) if whitelist_failed else None

    print("├" + "─" * (REPORT_WIDTH - 2) + "┤")

    _generate_line("📁 Output files:")
    _generate_line(f"  • {ADLIST_OUTPUT}")
    _generate_line(f"  • {WHITELIST_OUTPUT}")

    print("└" + "─" * (REPORT_WIDTH - 2) + "┘")


def _generate_report_sources(failed_sources: list[Source]):
    _generate_line(f"⚠️  UNAVAILABLE SOURCES: {len(failed_sources)}")
    for source in failed_sources:
        if source.is_url():
            _generate_line(f"  🌐 {source.raw}")
        else:
            _generate_line(f"  📄 {source.raw}")


def _generate_line(message):
    display_width = _get_display_width(message) + 4
    padding = REPORT_WIDTH - display_width
    message = f"│ {message}" + " " * padding + " │"
    print(message)


def _get_display_width(text):
    """Calculate the display width of text, accounting for wide characters like emojis."""
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
