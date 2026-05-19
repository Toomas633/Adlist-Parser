"""Tests for adparser.conflicts – conflict detection between blacklist and whitelist."""

from pathlib import Path

import adparser.conflicts as mod
from adparser.conflicts import (
    _canonical,
    _read_entries,
    check_conflicts,
    report_conflicts,
)


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_canonical_passthrough_domain():
    """Plain domain passes through _canonical unchanged."""
    assert _canonical("example.com") == "example.com"


def test_canonical_passthrough_abp_block():
    """ABP block rule passes through _canonical unchanged."""
    assert _canonical("||block.example^") == "||block.example^"


def test_canonical_passthrough_abp_allow():
    """ABP allow rule passes through _canonical unchanged."""
    assert _canonical("@@||allow.example^") == "@@||allow.example^"


def test_canonical_converts_pihole_regex():
    """Pi-hole anchored regex is converted to its ABP equivalent."""
    assert _canonical(r"(\.|^)domain\.com$") == "||domain.com^"


def test_read_entries_missing_file(tmp_path):
    """Missing file returns an empty list without raising."""
    assert _read_entries(tmp_path / "no_file.txt") == []


def test_read_entries_skips_hash_comments(tmp_path):
    """Lines starting with # are excluded from the result."""
    f = tmp_path / "list.txt"
    f.write_text("# comment\nexample.com\n", encoding="utf-8")
    assert _read_entries(f) == ["example.com"]


def test_read_entries_skips_bang_comments(tmp_path):
    """Lines starting with ! are excluded from the result."""
    f = tmp_path / "list.txt"
    f.write_text("! adblock comment\nexample.com\n", encoding="utf-8")
    assert _read_entries(f) == ["example.com"]


def test_read_entries_skips_blank_lines(tmp_path):
    """Blank lines are excluded from the result."""
    f = tmp_path / "list.txt"
    f.write_text("\n\nexample.com\n\n", encoding="utf-8")
    assert _read_entries(f) == ["example.com"]


def test_read_entries_strips_whitespace(tmp_path):
    """Leading and trailing whitespace is stripped from each entry."""
    f = tmp_path / "list.txt"
    f.write_text("  trimmed.com  \n", encoding="utf-8")
    assert _read_entries(f) == ["trimmed.com"]


def test_read_entries_multiple(tmp_path):
    """Multiple valid entries are all returned in order."""
    f = tmp_path / "list.txt"
    f.write_text("# header\n\na.com\nb.com\n", encoding="utf-8")
    assert _read_entries(f) == ["a.com", "b.com"]


def test_check_conflicts_no_conflicts(tmp_path, monkeypatch):
    """Disjoint blacklist and whitelist produce no conflicts."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["block.com", "bad.net"])
    _write(wl, ["good.com", "safe.net"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    assert not check_conflicts()


def test_check_conflicts_exact_match(tmp_path, monkeypatch):
    """Identical entry in both lists is returned as a conflict pair."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["bad.com", "conflict.example"])
    _write(wl, ["safe.com", "conflict.example"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    result = check_conflicts()
    assert result == [("conflict.example", "conflict.example")]


def test_check_conflicts_multiple(tmp_path, monkeypatch):
    """All overlapping entries are individually reported."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["a.com", "b.com", "c.com"])
    _write(wl, ["b.com", "c.com", "d.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    result = check_conflicts()
    assert len(result) == 2
    assert ("b.com", "b.com") in result
    assert ("c.com", "c.com") in result


def test_check_conflicts_case_insensitive(tmp_path, monkeypatch):
    """Comparison is case-insensitive; original casing is preserved in the pair."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["UPPER.COM"])
    _write(wl, ["upper.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    result = check_conflicts()
    assert len(result) == 1
    assert result[0] == ("UPPER.COM", "upper.com")


def test_check_conflicts_canonical_regex_vs_abp(tmp_path, monkeypatch):
    """Pi-hole regex in blacklist matches its ABP equivalent in whitelist."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, [r"(\.|^)domain\.com$"])
    _write(wl, ["||domain.com^"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    result = check_conflicts()
    assert len(result) == 1
    assert result[0] == (r"(\.|^)domain\.com$", "||domain.com^")


def test_check_conflicts_skips_comment_lines(tmp_path, monkeypatch):
    """Comment lines are not considered when detecting conflicts."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["# comment", "real.com"])
    _write(wl, ["# comment", "real.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    result = check_conflicts()
    assert result == [("real.com", "real.com")]


def test_check_conflicts_missing_files(tmp_path, monkeypatch):
    """Missing input files are treated as empty; no conflicts are reported."""
    monkeypatch.setattr(mod, "BLACKLIST_PATH", tmp_path / "bl.txt")
    monkeypatch.setattr(mod, "WHITELIST_PATH", tmp_path / "wl.txt")
    assert not check_conflicts()


def test_check_conflicts_empty_blacklist(tmp_path, monkeypatch):
    """Empty blacklist produces no conflicts regardless of whitelist content."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, [])
    _write(wl, ["something.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    assert not check_conflicts()


def test_check_conflicts_empty_whitelist(tmp_path, monkeypatch):
    """Empty whitelist produces no conflicts regardless of blacklist content."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["something.com"])
    _write(wl, [])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    assert not check_conflicts()


def test_report_no_conflicts_prints_ok(tmp_path, monkeypatch, capsys):
    """report_conflicts() prints an OK message when no conflicts exist."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["only.in.blacklist"])
    _write(wl, ["only.in.whitelist"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    report_conflicts()
    out = capsys.readouterr().out
    assert "No conflicts" in out
    assert "CONFLICT" not in out


def test_report_with_conflicts_prints_entries(tmp_path, monkeypatch, capsys):
    """report_conflicts() prints each conflicting entry when conflicts exist."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["shared.com"])
    _write(wl, ["shared.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    report_conflicts()
    out = capsys.readouterr().out
    assert "CONFLICT" in out
    assert "shared.com" in out


def test_report_singular_label(tmp_path, monkeypatch, capsys):
    """A single conflict uses the singular 'CONFLICT' label in the output."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["one.com"])
    _write(wl, ["one.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    report_conflicts()
    out = capsys.readouterr().out
    assert "1 CONFLICT BETWEEN" in out


def test_report_plural_label(tmp_path, monkeypatch, capsys):
    """Multiple conflicts use the plural 'CONFLICTS' label in the output."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, ["a.com", "b.com"])
    _write(wl, ["a.com", "b.com"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    report_conflicts()
    out = capsys.readouterr().out
    assert "2 CONFLICTS BETWEEN" in out


def test_report_shows_both_forms_when_differ(tmp_path, monkeypatch, capsys):
    """Regex in blacklist and ABP in whitelist are both shown."""
    bl = tmp_path / "blacklist.txt"
    wl = tmp_path / "whitelist.txt"
    _write(bl, [r"(\.|^)domain\.com$"])
    _write(wl, ["||domain.com^"])
    monkeypatch.setattr(mod, "BLACKLIST_PATH", bl)
    monkeypatch.setattr(mod, "WHITELIST_PATH", wl)
    report_conflicts()
    out = capsys.readouterr().out
    assert r"(\.|^)domain\.com$" in out
    assert "||domain.com^" in out
