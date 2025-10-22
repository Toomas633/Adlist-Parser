"""Redundancy analysis for sources.

Finds duplicate sources and highlights entries in local files that are
already covered by remote lists.
"""

from asyncio import to_thread
from os import path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from adparser.status import StatusSpinner

from .constants import ABP_OPTION_RE, ADLIST_OUTPUT, ELEMENT_HIDING_RE, WHITELIST_OUTPUT
from .content import normalize_lines_split
from .models import Source


def _normalized_entry_set(lines: Iterable[str]) -> Set[str]:
    """Normalize lines to a set of unique entries (domains + regex-like)."""
    domains, regexes = normalize_lines_split(lines)
    return set(domains) | set(regexes)


def _abp_prefix(entry: str) -> Optional[str]:
    """Return ABP prefix string ("@@||" or "||") if present, else None."""
    if entry.startswith('@@||'):
        return '@@||'
    if entry.startswith('||'):
        return '||'
    return None


def _abp_key(entry: str) -> Optional[str]:
    """Return normalized ABP domain key (without prefix/suffix) if entry is ABP."""
    if ELEMENT_HIDING_RE.search(entry):
        return None

    e = ABP_OPTION_RE.sub('', entry).strip().rstrip('|^')
    pref = _abp_prefix(e)
    if not pref:
        return None
    s = e[len(pref) :]

    if s.startswith('://'):
        s = s[3:]
    if '://' in s:
        s = s.split('://', 1)[-1]
    if '/' in s:
        s = s.split('/', 1)[0]
    if '@' in s:
        s = s.split('@')[-1]
    if ':' in s:
        s = s.split(':', 1)[0]
    return s.strip('.').lower() if s else None


def _ancestors(domain: str) -> List[str]:
    """Return domain ancestors from most-specific to top-level.

    Example: ``a.b.c`` -> ``['a.b.c', 'b.c', 'c']``
    """
    parts = domain.split('.')
    return ['.'.join(parts[i:]) for i in range(len(parts))]


def _remote_union(sources: Dict[str, Set[str]], labels: Dict[str, Source]) -> Set[str]:
    """Union of entries from all remote (URL) sources."""
    return set().union(
        *(
            s
            for other_label, s in sources.items()
            if labels.get(other_label) and labels[other_label].is_url()
        )
    )


def _collect_remote_abp_domains(entries: Iterable[str]) -> Set[str]:
    """Return ABP domain keys present in the remote entries."""
    keys: Set[str] = set()
    for r in entries:
        key = _abp_key(r)
        if key:
            keys.add(key)
    return keys


def _entry_covered_by_remote(entry: str, remote_abp_domains: Set[str]) -> bool:
    """Check if an entry is covered by broader ABP domains from remotes.

    Coverage rules:
    - For ABP entries (with @@|| or ||), if a parent domain of the key exists
      in remote ABP domains, it's considered covered.
    - For host/plain domains, strip leading wildcard tokens and check if any
      ancestor domain is present among remote ABP domains.
    """
    pref = _abp_prefix(entry)
    if pref:
        key = _abp_key(entry)
        if not key:
            return False
        parents = _ancestors(key)[1:]
        return any(p in remote_abp_domains for p in parents)

    dom = entry.lstrip('*.')
    return any(p in remote_abp_domains for p in _ancestors(dom))


def _iter_local_entries(
    per_source_sets: Dict[str, Set[str]], label_to_source: Dict[str, Source]
) -> Iterable[tuple[str, Set[str]]]:
    """Yield (label, entry_set) for local file sources only."""
    for label, entry_set in per_source_sets.items():
        source = label_to_source.get(label)
        if source and not source.is_url():
            yield label, entry_set


def _covered_entries(
    entry_set: Set[str], union_remote: Set[str], remote_abp_domains: Set[str]
) -> Set[str]:
    """Compute entries from entry_set that are covered by remote sources."""
    covered: Set[str] = set(entry_set & union_remote)
    for entry in entry_set:
        if entry in covered:
            continue
        if _entry_covered_by_remote(entry, remote_abp_domains):
            covered.add(entry)
    return covered


def _build_source_sets(
    fetch_results: List[tuple[Source, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
) -> Tuple[Dict[str, Set[str]], Dict[str, Source]]:
    """Map source labels (strings) to normalized entry sets and Sources.

    The fetch results may use `Source` instances or plain string labels as
    the first element. Normalize keys to the source label string (use
    `Source.raw` when a `Source` is provided) to avoid unhashable keys.
    """
    failed_labels = {fs.raw for fs in failed_sources}
    source_sets: Dict[str, Set[str]] = {}
    for label, lines in fetch_results:
        if isinstance(label, Source):
            lbl = label.raw
        else:
            lbl = str(label)
        if lbl in failed_labels:
            continue
        source_sets[lbl] = _normalized_entry_set(lines)

    label_to_source = {source.raw: source for source in all_sources}
    return source_sets, label_to_source


def _compute_duplicates(per_source_sets: Dict[str, Set[str]]) -> List[List[str]]:
    """Group sources (by label string) that have identical normalized content."""
    buckets: Dict[frozenset[str], List[str]] = {}
    for label, entry_set in per_source_sets.items():
        buckets.setdefault(frozenset(entry_set), []).append(label)
    return [sorted(labels) for labels in buckets.values() if len(labels) > 1]


def _compute_local_file_redundancy(
    per_source_sets: Dict[str, Set[str]], label_to_source: Dict[str, Source]
) -> Dict[str, tuple[Set[str], int]]:
    """Compute, for each local file, which lines are covered by remote sources.

    `per_source_sets` keys are label strings that map to entries in
    `label_to_source`.
    """
    local_coverage: Dict[str, tuple[Set[str], int]] = {}

    union_remote = _remote_union(per_source_sets, label_to_source)
    remote_abp_domains = _collect_remote_abp_domains(union_remote)

    for label, entry_set in _iter_local_entries(per_source_sets, label_to_source):
        source = label_to_source[label]
        covered = _covered_entries(entry_set, union_remote, remote_abp_domains)
        local_coverage[source.raw] = (covered, len(entry_set))

    return local_coverage


def _format_source_label(label: str) -> str:
    """Format a source label with a URL/file emoji."""
    source = Source(label)
    if source.is_url():
        return f"🌐 {label}"
    return f"📄 {label}"


def _generate_duplicate_sources(duplicate_groups: List[List[str]]) -> List[str]:
    """Print duplicate source groups; return True if any were found."""
    message: List[str] = []

    if not duplicate_groups:
        return message

    message.append(
        f"  🔁 Duplicate sources (identical content): {len(duplicate_groups)} groups"
    )
    for grp in duplicate_groups:
        for i, label in enumerate(grp):
            prefix = "   ├─" if i < len(grp) - 1 else "   └─"
            message.append(f"  {prefix} {_format_source_label(label)}")
        message.append(
            "      💡 Tip: Keep one source from this group, remove the others"
        )

    return message


def _generate_local_file_redundancy(
    local_file_redundancy: Dict[str, tuple[Set[str], int]],
) -> List[str]:
    """Print redundancy results for local files; return True if any found."""
    message: List[str] = []

    if not local_file_redundancy:
        return message

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
            (
                f"    • {label}: {len(covered_lines)}/{total_lines} entries "
                f"({coverage_pct:.1f}%) already in remote sources"
            )
        )

        lines_to_print.append("      Entries that can be removed:")
        for line in sorted(covered_lines)[:20]:
            lines_to_print.append(f"        - {line}")
        if len(covered_lines) > 20:
            lines_to_print.append(f"        ... and {len(covered_lines) - 20} more")

    if has_redundancy:
        message.append("  📄 Local file redundancy analysis:")
        for line in lines_to_print:
            message.append(line)

    return message


def _analyze_redundancy(
    fetch_results: List[tuple[Source, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
) -> Tuple[
    List[List[str]],
    Dict[str, Tuple[Set[str], int]],
]:
    """Analyze redundancy across sources.

    Returns:
        - per_source_sets: label -> normalized entry set
        - label_to_source: label -> Source
        - duplicate_groups: groups of duplicate labels
        - local_file_redundancy: label -> (covered_lines, total_lines)
    """
    per_source_sets, label_to_source = _build_source_sets(
        fetch_results, failed_sources, all_sources
    )
    duplicate_groups = _compute_duplicates(per_source_sets)
    local_file_redundancy = _compute_local_file_redundancy(
        per_source_sets, label_to_source
    )

    return duplicate_groups, local_file_redundancy


async def generate_redundancy_report(
    fetch_results: List[Tuple[Source, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
    spinner: StatusSpinner,
    label: str,
) -> List[str]:
    """Analyze and print redundancy information for a set of sources."""
    filtered_fetch, filtered_failed, filtered_all = _exclude_old_output_sources(
        label, fetch_results, failed_sources, all_sources
    )
    duplicate_groups: List[List[str]]
    local_file_redundancy: Dict[str, Tuple[Set[str], int]]
    duplicate_groups, local_file_redundancy = await spinner.show_progress(
        f"{label} redundancy: Analyzing...",
        to_thread(_analyze_redundancy, filtered_fetch, filtered_failed, filtered_all),
    )

    duplicates = _generate_duplicate_sources(duplicate_groups)
    local_redundancies = _generate_local_file_redundancy(local_file_redundancy)

    message: str
    if duplicates or local_redundancies:
        message = "Duplicates or local redundancies found."
    else:
        message = "No duplicates or local redundancies found."

    spinner.update_status(f"✅ {label} redundancy: Complete - {message}")

    return duplicates + local_redundancies


def _exclude_old_output_sources(
    label: str,
    fetch_results: List[Tuple[Source, List[str]]],
    failed_sources: List[Source],
    all_sources: List[Source],
):
    """Filter out references to current output files from redundancy inputs.

    Depending on the label (Adlist/Whitelist), exclude entries that point to
    the generated output file paths to avoid self-reporting redundancy.
    Returns filtered copies of the three input collections.
    """
    if label.lower().startswith("adlist"):
        exclude_rel = ADLIST_OUTPUT
    elif label.lower().startswith("whitelist"):
        exclude_rel = WHITELIST_OUTPUT
    else:
        return fetch_results, failed_sources, all_sources

    exclude_abs = path.abspath(exclude_rel)
    fr = [
        (lab, lines)
        for lab, lines in fetch_results
        if not is_excluded_label(lab, exclude_rel, exclude_abs)
    ]
    fs = [s for s in failed_sources if not is_excluded_src(s, exclude_rel, exclude_abs)]
    asrc = [s for s in all_sources if not is_excluded_src(s, exclude_rel, exclude_abs)]
    return fr, fs, asrc


def is_excluded_src(src: Source, exclude_rel: str, exclude_abs: str) -> bool:
    """Return True if a source matches the excluded output file.

    A source is excluded when its raw label equals the relative output path or
    when its resolved absolute file path matches the absolute output path.
    """
    if src.raw == exclude_rel:
        return True
    if src.resolved_path and path.abspath(src.resolved_path) == exclude_abs:
        return True
    return False


def is_excluded_label(lab: object, exclude_rel: str, exclude_abs: str) -> bool:
    """Return True if a label corresponds to the excluded output file.

    Accepts either a Source instance or an arbitrary label; in the latter case,
    it compares the string form to the relative excluded path.
    """
    if isinstance(lab, Source):
        return is_excluded_src(lab, exclude_rel, exclude_abs)
    return str(lab) == exclude_rel
