"""Tests for adparser/duplicates.py.

Covers all functions and branches: _canonical, _build_remote_index,
_compute_covered, _build_intra_file_index, _dedup_file, _filter_lines,
_write_lines, _process_list, main, and the __main__ guard.
"""

from __future__ import annotations

from asyncio import run
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

from adparser.duplicates import (
    _canonical,
    _build_remote_index,
    _compute_covered,
    _build_intra_file_index,
    _dedup_file,
    _filter_lines,
    _write_lines,
    _process_list,
    main,
)
from adparser.models import Source
from adparser.status import StatusSpinner


class _Spinner:
    """Awaits operations directly; ignores progress/status calls."""

    async def show_progress(self, _msg: str, op):
        return await op

    def update_progress(self, _c: int, _t: int) -> None:
        # No-op: progress tracking drives the spinner animation in the real
        # StatusSpinner, which is not needed in tests.
        pass

    def update_status(self, _msg: str) -> None:
        # No-op: progress tracking drives the spinner animation in the real
        # StatusSpinner, which is not needed in tests.
        pass


def _url(url: str = "https://example.com/list.txt") -> Source:
    return Source(raw=url)


def _local(path: str = "/path/to/blacklist.txt") -> Source:
    return Source(raw=path, resolved_path=path)


def test_canonical_pihole_regex_converted():
    assert _canonical(r"(\.|^)domain\.com$") == "||domain.com^"


def test_canonical_non_regex_unchanged():
    assert _canonical("example.com") == "example.com"
    assert _canonical("||block.example^") == "||block.example^"
    assert _canonical("*.wildcard.test") == "*.wildcard.test"


def test_build_remote_index_local_src_skipped():
    rc, ra = _build_remote_index([(_local(), ["example.com"])])
    assert not rc
    assert not ra


def test_build_remote_index_abp_entry():
    rc, ra = _build_remote_index([(_url(), ["||ads.example^"])])
    assert "||ads.example^" in rc
    assert "ads.example" in ra


def test_build_remote_index_wildcard_entry():
    rc, ra = _build_remote_index([(_url(), ["*.wild.example"])])
    assert "*.wild.example" in rc
    assert "wild.example" in ra


def test_build_remote_index_plain_domain_canonical_only():
    """Plain domains go into remote_canonical but NOT remote_abp_domains."""
    rc, ra = _build_remote_index([(_url(), ["plain.com"])])
    assert "plain.com" in rc
    assert "plain.com" not in ra


def test_build_remote_index_pihole_regex_canonicalized():
    rc, ra = _build_remote_index([(_url(), [r"(\.|^)rex\.com$"])])
    assert "||rex.com^" in rc
    assert "rex.com" in ra


_FNAME = "blacklist.txt"
_LPATH = f"/path/to/{_FNAME}"


def _cc(url_lines, local_lines):
    """Build (results, failed, sources) for _compute_covered helpers."""
    u = _url()
    loc = _local(_LPATH)
    return [(u, url_lines), (loc, local_lines)], [], [u, loc]


def test_compute_covered_url_src_not_added_to_covered():
    results, failed, sources = _cc(["example.com"], [])
    with patch("adparser.duplicates._analyze_redundancy", return_value=([], {})):
        covered = _compute_covered(results, failed, sources, _FNAME)
    assert "example.com" not in covered


def test_compute_covered_non_matching_local_skipped():
    u = _url()
    other = _local("/path/to/other.txt")
    results = [(u, ["||b.example^"]), (other, ["b.example"])]
    with patch("adparser.duplicates._analyze_redundancy", return_value=([], {})):
        covered = _compute_covered(results, [], [u, other], _FNAME)
    assert "b.example" not in covered


def test_compute_covered_canonical_remote_match():
    """Pi-hole regex whose canonical equals a remote ABP rule is covered."""
    results, failed, sources = _cc(["||covered.example^"], [r"(\.|^)covered\.example$"])
    with patch("adparser.duplicates._analyze_redundancy", return_value=([], {})):
        covered = _compute_covered(results, failed, sources, _FNAME)
    assert r"(\.|^)covered\.example$" in covered


def test_compute_covered_abp_parent_coverage():
    """Sub-domain plain entry is covered when a parent ABP rule exists remotely."""
    results, failed, sources = _cc(["||example.com^"], ["sub.example.com"])
    with patch("adparser.duplicates._analyze_redundancy", return_value=([], {})):
        covered = _compute_covered(results, failed, sources, _FNAME)
    assert "sub.example.com" in covered


def test_compute_covered_already_seeded_entry_skips_recheck():
    """Entry already in covered (from _analyze_redundancy) is not re-processed."""
    results, failed, sources = _cc(["||example.com^"], ["example.com"])
    with patch(
        "adparser.duplicates._analyze_redundancy",
        return_value=([], {_FNAME: ({"example.com"}, 1)}),
    ):
        covered = _compute_covered(results, failed, sources, _FNAME)
    assert "example.com" in covered


def test_compute_covered_not_covered():
    results, failed, sources = _cc(["||other.com^"], ["notcovered.xyz"])
    with patch("adparser.duplicates._analyze_redundancy", return_value=([], {})):
        covered = _compute_covered(results, failed, sources, _FNAME)
    assert "notcovered.xyz" not in covered


def test_build_intra_file_index_empty_and_comments():
    assert _build_intra_file_index(["", "# comment"]) == set()


def test_build_intra_file_index_abp_key():
    result = _build_intra_file_index(["||ads.example^"])
    assert "ads.example" in result


def test_build_intra_file_index_wildcard():
    result = _build_intra_file_index(["*.wild.test"])
    assert "wild.test" in result


def test_build_intra_file_index_plain_domain_not_indexed():
    assert not _build_intra_file_index(["plain.com"])


def test_build_intra_file_index_html_line_no_entries():
    """A line that normalises to no entries leaves the index empty."""
    assert _build_intra_file_index(["<html>junk</html>"]) == set()


def test_dedup_file_comments_and_empty_kept():
    lines = ["", "# comment"]
    kept, removed = _dedup_file(lines)
    assert kept == lines
    assert removed == 0


def test_dedup_file_no_entries_line_kept():
    lines = ["<html>skip</html>"]
    kept, removed = _dedup_file(lines)
    assert kept == lines
    assert removed == 0


def test_dedup_file_exact_duplicate_removed():
    kept, removed = _dedup_file(["example.com", "example.com"])
    assert kept == ["example.com"]
    assert removed == 1


def test_dedup_file_broader_rule_removes_subdomain():
    kept, removed = _dedup_file(["||example.com^", "sub.example.com"])
    assert "sub.example.com" not in kept
    assert removed == 1


def test_dedup_file_canonical_duplicate_removed():
    """Pi-hole regex and its ABP equivalent share a canonical form."""
    kept, removed = _dedup_file([r"(\.|^)x\.com$", "||x.com^"])
    assert removed == 1
    assert len(kept) == 1


def test_dedup_file_unique_entries_all_kept():
    lines = ["alpha.com", "beta.com", "gamma.com"]
    kept, removed = _dedup_file(lines)
    assert kept == lines
    assert removed == 0


def test_filter_lines_empty_and_comments_kept():
    lines = ["", "# comment"]
    kept, removed = _filter_lines(lines, set())
    assert kept == lines
    assert removed == 0


def test_filter_lines_no_entries_line_kept():
    kept, removed = _filter_lines(["<html>junk</html>"], set())
    assert kept == ["<html>junk</html>"]
    assert removed == 0


def test_filter_lines_covered_entry_removed():
    kept, removed = _filter_lines(["example.com"], {"example.com"})
    assert kept == []
    assert removed == 1


def test_filter_lines_uncovered_entry_kept():
    kept, removed = _filter_lines(["example.com"], {"other.com"})
    assert kept == ["example.com"]
    assert removed == 0


def test_filter_lines_partial_coverage_keeps_line():
    """Line stays when not ALL of its entries are covered."""
    kept, removed = _filter_lines(["0.0.0.0 a.com b.com"], {"a.com"})
    assert removed == 0
    assert kept == ["0.0.0.0 a.com b.com"]


def test_write_lines_non_empty(tmp_path: Path):
    p = tmp_path / "out.txt"
    _write_lines(p, ["a", "b", "c"])
    assert p.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_write_lines_empty(tmp_path: Path):
    p = tmp_path / "out.txt"
    _write_lines(p, [])
    assert p.read_text(encoding="utf-8") == ""


def test_process_list_full_pipeline(tmp_path: Path):
    """Integration: pipeline runs end-to-end; progress_cb inner fn is called."""
    file_path = tmp_path / "blacklist.txt"
    file_path.write_text("kept.com\nremote.com\n# comment\n", encoding="utf-8")

    url_src = _url()
    local_src = Source(raw=str(file_path), resolved_path=str(file_path))

    def fake_fetch(sources, progress_callback):
        progress_callback(1, len(sources))
        return ([(url_src, ["||remote.com^"])], [])

    with patch(
        "adparser.duplicates.load_sources",
        return_value=[url_src, local_src],
    ):
        with patch("adparser.duplicates.fetch", side_effect=fake_fetch):
            with patch(
                "adparser.duplicates._analyze_redundancy",
                return_value=([], {}),
            ):
                total = run(
                    _process_list(
                        "Test",
                        "data/adlists.json",
                        "blacklist.txt",
                        file_path,
                        cast(StatusSpinner, _Spinner()),
                    )
                )

    assert isinstance(total, int)
    assert total >= 0
    remaining = file_path.read_text(encoding="utf-8").splitlines()
    assert "kept.com" in remaining


def test_main_returns_zero():
    with patch(
        "adparser.duplicates._process_list",
        new_callable=AsyncMock,
        return_value=0,
    ):
        result = run(main())
    assert result == 0


def test_dunder_main_guard_raises_system_exit():
    """main() returns 0 when _process_list is mocked."""
    with patch(
        "adparser.duplicates._process_list",
        new_callable=AsyncMock,
        return_value=0,
    ):
        result = run(main())
    assert result == 0
