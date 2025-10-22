"""Combined tests for adparser.content.

This file merges the former test_content.py, test_content_more.py, and
test_content_helpers.py to keep related tests in one place.
"""

# pylint: disable=missing-function-docstring, protected-access
from pytest import mark

from adparser import content
from adparser.models import Source


def test_normalize_lines_split_basic():
    lines = [
        "# comment should be skipped",
        "0.0.0.0 example.com alias.local",
        "127.0.0.1 another.example",
        "::1 ipv6.local",
        "   0.0.0.0   spaced.local   # with comment",
        "<html>ignore html-ish</html>",
        "plain.example.com",
        "*.wild.example",
        "@@||allow.example^",
        "||block.example^",
        "(^|\\.)regex.example$",
        "not-a-domain$",
    ]

    domains, non_domains = content.normalize_lines_split(lines)

    assert "example.com" in domains
    assert "alias.local" in domains
    assert "another.example" in domains
    assert "ipv6.local" in domains
    assert "spaced.local" in domains
    assert "plain.example.com" in domains
    assert "*.wild.example" in domains
    assert "@@||allow.example^" in non_domains
    assert "||block.example^" in non_domains
    assert "(^|\\.)regex.example$" in non_domains


def test_generate_list_merges_and_extracts_auxiliary():
    src1 = Source(raw="local1")
    src2 = Source(raw="local2")
    lines1 = [
        "0.0.0.0 a.example",
        "@@||allow.example^",
        "||abp.block^",
        "(^|\\.)regex.domain$",
    ]
    lines2 = [
        "b.example",
        "*.c.example",
        "||*.wildcard.test^",
    ]

    domains, abp_rules, failed = content.generate_list(
        results=[(src2, lines2), (src1, lines1)],
        sources=[src1, src2],
        failed_sources=[],
    )

    assert domains == [
        "a.example",
        "b.example",
        "c.example",
    ]
    assert "@@||allow.example^" in abp_rules
    assert "||abp.block^" in abp_rules
    assert "||wildcard.test^" in abp_rules
    assert "||regex.domain^" in abp_rules
    assert failed == []


def test_separate_blocklist_whitelist_move_and_dedupe():
    adlist = [
        "example.com",
        "||ads.example^",
        "@@||should-move.example^",
        "||sub.ads.example^",
        "(^|\\.)regex.keep$",
    ]
    whitelist = [
        "@@||allow.example^",
        "allow-plain.example",
        "||ads.example^",
    ]

    block, white = content.separate_blocklist_whitelist(adlist, whitelist)

    assert "@@||should-move.example^" not in block
    assert "||sub.ads.example^" not in block
    assert "(^|\\.)regex.keep" in block
    assert "||ads.example^" not in block
    assert "example.com" in block
    assert "@@||allow.example^" in white
    assert "@@||ads.example^" in white
    assert any(x == "allow-plain.example" for x in white)


def test_abp_wildcard_and_prefix_normalization():
    src = Source(raw="mixed")
    lines = [
        "||*cdn.site^",
        "||app.*.adjust.com^",
        "||domain.google.*^",
        "@@|domain.com^|",
        "|https://user@host:8080/p^",
    ]

    domains, abp_rules, failed = content.generate_list(
        results=[(src, lines)], sources=[src], failed_sources=[]
    )

    assert not domains
    assert "||cdn.site^" in abp_rules
    assert "||app.adjust.com^" in abp_rules
    assert all(r != "||domain.google^" for r in abp_rules)
    assert "@@||domain.com^" in abp_rules
    assert "||host^" in abp_rules
    assert not failed


def test_regex_conversion_variants():
    src = Source(raw="regex")
    lines = [
        "/(^|\\.)ex\\.tld$/",
        "^(?:sub\\.)*foo\\.bar$",
        "(x+)baz$",
        "(?=lookahead)domain$",
    ]

    domains, abp_rules, _ = content.generate_list(
        results=[(src, lines)], sources=[src], failed_sources=[]
    )

    assert not domains
    assert "||ex.tld^" in abp_rules
    assert "||foo.bar^" not in abp_rules
    assert "||baz^" in abp_rules
    assert "||domain^" in abp_rules


def test_idna_domain_and_wildcard_handling():
    lines = [
        "täst.de",
        "*.münich.de",
        "invalid_label_-.com",
    ]
    domains, non_domains = content.normalize_lines_split(lines)

    assert "xn--tst-qla.de" in domains
    assert "*.xn--mnich-kva.de" in domains
    assert "invalid_label_-.com" in non_domains


def test_separate_handles_pipe_and_options_and_move_to_whitelist():
    adlist = [
        "||https://user@sub.host:8443/path^$third-party",
        "||sub.host^",
        "||ads.example",
    ]
    whitelist = [
        "@@|domain.com^|",
        "allow*.wild*card.example",
    ]

    block, white = content.separate_blocklist_whitelist(adlist, whitelist)

    assert "||sub.host^" in block and block.count("||sub.host^") == 1
    assert any(e in block for e in ("||ads.example^",))
    assert "@@||domain.com^" in white
    assert any(x == "allow*.wild*card.example" for x in white)


def test_filter_covered_adds_caret_and_keeps_regex_like():
    entries = {"||ads.example", "a.b$", "(^|\\.)keep.example$"}
    out = content._filter_covered(entries, "||")

    assert "||ads.example^" in out
    assert any(e.endswith("$") for e in out)


@mark.parametrize(
    "value",
    [
        "",
        "-bad.start",
        "bad.end-",
        "...",
    ],
)
def test_maybe_extract_domain_none(value):
    assert content._maybe_extract_domain(value) is None


@mark.parametrize(
    "value,expected",
    [
        ("/a/", True),
        ("^start", True),
        ("end$", True),
        ("plain.example", False),
    ],
)
def test_is_regex_like_entry(value, expected):
    assert content._is_regex_like_entry(value) is expected


@mark.parametrize(
    "raw,expected",
    [
        ("@@|domain.com^|", "@@||domain.com^"),
        ("||*sub.domain^", "||*.sub.domain^"),
        ("||example.*^", "||example^"),
    ],
)
def test_normalize_abp_wildcards_helper_and_prefix(raw, expected):
    assert content._normalize_abp_wildcards(raw) == expected


@mark.parametrize(
    "value,expected",
    [
        ("/abc/", "abc"),
        ("abc", "abc"),
    ],
)
def test_unwrap_slash_delimited_helper(value, expected):
    assert content._unwrap_slash_delimited(value) == expected


@mark.parametrize(
    "prefix",
    [content.DOMAIN_PREFIX_CAPTURE, content.DOMAIN_PREFIX_NOCAPTURE],
)
def test_strip_leading_domain_prefix_variants(prefix):
    assert (
        content._strip_leading_domain_prefix(prefix + "example\\.com")
        == "example\\.com"
    )


@mark.parametrize(
    "pattern,expected",
    [
        ("^" + content.DOMAIN_PREFIX_CAPTURE + "foo\\.bar$", "||foo.bar^"),
        ("^" + content.DOMAIN_PREFIX_NOCAPTURE + "baz\\.qux$", "||baz.qux^"),
    ],
)
def test_convert_regex_to_abp_prefix_stripping(pattern, expected):
    assert content._convert_regex_to_abp(pattern) == expected


def test_to_domain_abp_invalid():
    assert content._to_domain_abp("-bad-.com") is None


@mark.parametrize(
    "value,expected",
    [("domain^", "abp"), ("(foo)", "regex"), ("##.ad", None)],
)
def test_categorize_entry_variants_helper(value, expected):
    assert content._categorize_entry(value) == expected


def test_extract_domains_from_hosts_none_and_leading_ip_empty():
    assert content._extract_domains_from_hosts("192.168.1.1 foo") is None
    assert content._extract_domains_from_leading_ip("0.0.0.0   ") == []


def test_is_valid_domain_part_star_label():
    assert content._is_valid_domain_part("a.*.b") is True


def test_ancestors_returns_chain():
    assert content._ancestors("a.b.c") == ["a.b.c", "b.c", "c"]


def test_filter_covered_parent_rule_covers_subdomain():
    entries = {"||example.com^", "sub.example.com"}
    out = content._filter_covered(entries, "||")

    assert "sub.example.com" not in out


def test_process_entry_preserve_abp_invalid_pipe_entry():
    block, white = set(), set()

    content._process_entry_preserve_abp("||-bad-.com^", False, block, white)

    assert "||-bad-.com^" not in block and not white
