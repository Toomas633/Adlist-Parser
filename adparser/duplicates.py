"""Remove local entries covered by remote sources.

Uses redundancy analysis to remove entries in data/blacklist.txt and
data/whitelist.txt that are already covered by remote sources, as well as
duplicates and entries covered by broader rules within each file.

Usage:
  python -m adparser --remove-duplicates
"""

from __future__ import annotations

import asyncio
from asyncio import to_thread
from pathlib import Path
from typing import Iterable, List

from .conflicts import report_conflicts
from .content import _convert_regex_to_abp, normalize_lines_split
from .fetcher import fetch
from .io import load_sources
from .redundancy import _abp_key, _analyze_redundancy, _entry_covered_by_remote
from .status import GroupedStatusDisplay, StatusSpinner

ROOT = Path(__file__).resolve().parents[1]


def _canonical(entry: str) -> str:
    """Return canonical ABP form of a Pi-hole regex entry, or entry unchanged."""
    return _convert_regex_to_abp(entry) or entry


def _build_remote_index(results: list) -> tuple[set[str], set[str]]:
    """Collect canonical entries and ABP domain keys from URL sources."""
    remote_canonical: set[str] = set()
    remote_abp_domains: set[str] = set()
    for src, lines in results:
        if not src.is_url():
            continue
        doms, ndoms = normalize_lines_split(lines)
        for e in doms + ndoms:
            c = _canonical(e)
            remote_canonical.add(c)
            key = _abp_key(c)
            if key:
                remote_abp_domains.add(key.lstrip('*.'))
            elif c.startswith('*.'):
                remote_abp_domains.add(c[2:])
    return remote_canonical, remote_abp_domains


def _compute_covered(
    results: list,
    failed: list,
    sources: list,
    local_filename: str,
) -> set[str]:
    """Return local entries covered by remote sources.

    Extends the standard redundancy analysis with canonical ABP conversion so
    that Pi-hole regex patterns (e.g. ``(\\.|^)domain\\.com$``) are matched
    against equivalent remote ABP rules (``||domain.com^``).
    """
    _, local_redundancy = _analyze_redundancy(results, failed, sources)
    covered: set[str] = set(local_redundancy.get(local_filename, (set(), 0))[0])

    remote_canonical, remote_abp_domains = _build_remote_index(results)

    for src, lines in results:
        if src.is_url():
            continue
        if local_filename not in src.raw:
            continue
        doms, ndoms = normalize_lines_split(lines)
        for e in doms + ndoms:
            if e in covered:
                continue
            c = _canonical(e)
            if c in remote_canonical or _entry_covered_by_remote(c, remote_abp_domains):
                covered.add(e)

    return covered


def _build_intra_file_index(lines: List[str]) -> set[str]:
    """Collect every ABP domain key present in the file (pass 1 of dedup)."""
    all_abp_domains: set[str] = set()
    for raw in lines:
        if not raw or raw.startswith('#'):
            continue
        doms, ndoms = normalize_lines_split([raw])
        for e in doms + ndoms:
            c = _canonical(e)
            key = _abp_key(c)
            if key:
                all_abp_domains.add(key.lstrip('*.'))
            elif c.startswith('*.'):
                all_abp_domains.add(c[2:])
    return all_abp_domains


def _dedup_file(lines: List[str]) -> tuple[List[str], int]:
    """Remove intra-file duplicates and entries covered by a broader rule.

    Two-pass: first collect every ABP domain key present in the whole file,
    then drop any entry whose canonical form is already covered by one of
    those keys or is a canonical duplicate of an earlier line.
    """
    all_abp_domains = _build_intra_file_index(lines)

    kept: List[str] = []
    removed = 0
    seen_canonical: set[str] = set()

    for raw in lines:
        if not raw or raw.startswith('#'):
            kept.append(raw)
            continue

        doms, ndoms = normalize_lines_split([raw])
        entries = doms + ndoms
        if not entries:
            kept.append(raw)
            continue

        cans = [_canonical(e) for e in entries]

        if all(c in seen_canonical for c in cans):
            removed += 1
            continue

        if all(_entry_covered_by_remote(c, all_abp_domains) for c in cans):
            removed += 1
            continue

        kept.append(raw)
        seen_canonical.update(cans)

    return kept, removed


def _filter_lines(lines: Iterable[str], covered: set[str]) -> tuple[List[str], int]:
    """Remove entries already covered by remote sources."""
    kept: List[str] = []
    removed = 0

    for raw in lines:
        if not raw or raw.startswith('#'):
            kept.append(raw)
            continue

        doms, ndoms = normalize_lines_split([raw])
        entries = doms + ndoms
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


async def _process_list(
    label: str,
    json_path: str,
    local_filename: str,
    file_path: Path,
    spinner: StatusSpinner,
) -> int:
    sources = await spinner.show_progress(
        f"{label}: Loading sources...",
        to_thread(load_sources, str(ROOT / json_path)),
    )

    def progress_cb(c: int, t: int) -> None:
        spinner.update_progress(c, t)

    results, failed = await spinner.show_progress(
        f"{label}: Fetching content...",
        to_thread(fetch, sources, progress_cb),
    )

    covered = await spinner.show_progress(
        f"{label}: Analyzing coverage...",
        to_thread(_compute_covered, results, failed, sources, local_filename),
    )

    lines = file_path.read_text(encoding="utf-8").splitlines()

    lines, self_removed = await spinner.show_progress(
        f"{label}: Removing intra-file duplicates...",
        to_thread(_dedup_file, lines),
    )

    kept, remote_removed = await spinner.show_progress(
        f"{label}: Removing remotely-covered entries...",
        to_thread(_filter_lines, lines, covered),
    )

    await to_thread(_write_lines, file_path, kept)

    total = self_removed + remote_removed
    spinner.update_status(
        f"✅ {label}: Removed {total} entries from {file_path.name} "
        f"({self_removed} intra-file, {remote_removed} remote)"
    )

    return total


async def main() -> int:
    status = GroupedStatusDisplay()
    adlist_spinner = status.allocate_line()
    whitelist_spinner = status.allocate_line()

    await asyncio.gather(
        _process_list(
            "Adlist",
            "data/adlists.json",
            "blacklist.txt",
            ROOT / "data/blacklist.txt",
            adlist_spinner,
        ),
        _process_list(
            "Whitelist",
            "data/whitelists.json",
            "whitelist.txt",
            ROOT / "data/whitelist.txt",
            whitelist_spinner,
        ),
    )
    status.finalize()

    report_conflicts()

    return 0
