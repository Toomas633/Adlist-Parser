"""Redundancy analysis for adlist sources.

Identifies duplicate sources and analyzes which entries in local files
can be removed because they're already covered by remote sources.
"""

from typing import Dict, Iterable, List, Set

from .content import normalize_lines_split
from .models import Source


def _normalized_entry_set(lines: Iterable[str]) -> Set[str]:
    """Normalize lines to a set of unique entries (domains + regexes)."""
    domains, regexes = normalize_lines_split(lines)
    return set(domains) | set(regexes)


def _build_source_sets(
    fetch_results: List[tuple[str, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
) -> tuple[Dict[str, Set[str]], Dict[str, Source]]:
    """Build a mapping of source labels to their normalized entry sets.

    Also returns a dict mapping labels to Source objects for later use.
    """
    failed_labels = {fs.raw for fs in failed_sources}
    source_sets = {
        label: _normalized_entry_set(lines)
        for label, lines in fetch_results
        if label not in failed_labels
    }
    label_to_source = {source.raw: source for source in all_sources}
    return source_sets, label_to_source


def _compute_duplicates(per_source_sets: Dict[str, Set[str]]) -> List[List[str]]:
    """Find groups of sources with identical normalized content."""
    buckets: Dict[frozenset[str], List[str]] = {}
    for label, entry_set in per_source_sets.items():
        buckets.setdefault(frozenset(entry_set), []).append(label)
    return [sorted(labels) for labels in buckets.values() if len(labels) > 1]


def _compute_local_file_redundancy(
    per_source_sets: Dict[str, Set[str]], label_to_source: Dict[str, Source]
) -> Dict[str, tuple[Set[str], int]]:
    """For each local file, compute which lines are covered by remote sources.

    Returns dict mapping local file labels to (covered_lines_set, total_lines_count).
    """
    local_coverage: Dict[str, tuple[Set[str], int]] = {}

    for label, entry_set in per_source_sets.items():
        source = label_to_source.get(label)
        if not source or source.is_url():
            continue

        union_remote = set().union(
            *(
                s
                for other_label, s in per_source_sets.items()
                if label_to_source.get(other_label)
                and label_to_source[other_label].is_url()
            )
        )

        covered = entry_set & union_remote
        local_coverage[label] = (covered, len(entry_set))

    return local_coverage


def _format_source_label(label: str, label_to_source: Dict[str, Source]) -> str:
    """Format a source label with an emoji indicator."""
    source = label_to_source.get(label)
    if source and source.is_url():
        return f"🌐 {label}"
    return f"📄 {label}"


def _print_duplicate_sources(
    duplicate_groups: List[List[str]], label_to_source: Dict[str, Source]
) -> bool:
    """Print duplicate source groups. Returns True if duplicates were found."""
    if not duplicate_groups:
        return False

    print(f"\n🔁 Duplicate sources (identical content): {len(duplicate_groups)} groups")
    for grp in duplicate_groups:
        for i, label in enumerate(grp):
            prefix = " ├─" if i < len(grp) - 1 else " └─"
            print(f"{prefix} {_format_source_label(label, label_to_source)}")
        print("    💡 Tip: Keep one source from this group, remove the others")
    return True


def _print_local_file_redundancy(
    local_file_redundancy: Dict[str, tuple[Set[str], int]],
) -> bool:
    """Print redundancy analysis for local files. Returns True if redundancy was found."""
    if not local_file_redundancy:
        return False

    has_redundancy = False
    lines_to_print = []

    for label, (covered_lines, total_lines) in sorted(local_file_redundancy.items()):
        if not covered_lines:
            continue

        has_redundancy = True
        coverage_pct = (
            (len(covered_lines) / total_lines * 100) if total_lines > 0 else 0
        )
        lines_to_print.append(
            f"  • {label}: {len(covered_lines)}/{total_lines} entries "
            f"({coverage_pct:.1f}%) already in remote sources"
        )

        lines_to_print.append("    Entries that can be removed:")
        for line in sorted(covered_lines)[:20]:
            lines_to_print.append(f"      - {line}")
        if len(covered_lines) > 20:
            lines_to_print.append(f"      ... and {len(covered_lines) - 20} more")

    if has_redundancy:
        print("\n📄 Local file redundancy analysis:")
        for line in lines_to_print:
            print(line)

    return has_redundancy


def _analyze_redundancy(
    fetch_results: List[tuple[str, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
) -> tuple[
    Dict[str, Set[str]],
    Dict[str, Source],
    List[List[str]],
    Dict[str, tuple[Set[str], int]],
]:
    """Analyze redundancy across sources.

    Returns:
        - per_source_sets: Dict mapping source labels to their normalized entry sets
        - label_to_source: Dict mapping labels to Source objects
        - duplicate_groups: List of duplicate source groups
        - local_file_redundancy: Dict mapping local files to (covered_lines, total_lines)
    """
    per_source_sets, label_to_source = _build_source_sets(
        fetch_results, failed_sources, all_sources
    )
    duplicate_groups = _compute_duplicates(per_source_sets)
    local_file_redundancy = _compute_local_file_redundancy(
        per_source_sets, label_to_source
    )

    return per_source_sets, label_to_source, duplicate_groups, local_file_redundancy


def generate_redundancy_report(
    fetch_results: List[tuple[str, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
    title: str,
) -> None:
    """Analyze and print redundancy information for a set of sources."""
    print(f"=== {title} redundancy analysis ===")

    label_to_source = {source.raw: source for source in all_sources}

    if failed_sources:
        print(f"⚠️  Skipping {len(failed_sources)} unavailable sources in analysis:")
        for source in failed_sources:
            print(f"   - {_format_source_label(source.raw, label_to_source)}")

    per_source_sets, label_to_source, duplicate_groups, local_file_redundancy = (
        _analyze_redundancy(fetch_results, failed_sources, all_sources)
    )

    print(f"Analyzed {len(per_source_sets)} sources.")

    has_duplicates = _print_duplicate_sources(duplicate_groups, label_to_source)
    has_local_redundancy = _print_local_file_redundancy(local_file_redundancy)

    if not has_duplicates and not has_local_redundancy:
        print("\n✅ No redundancy issues detected")
