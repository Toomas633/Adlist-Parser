"""Utilities for normalizing adlist content.

Responsibilities:
- Identify and drop full-line comments and strip inline comments
- Preserve non-domain lines (including regex-like) and wildcard tokens as-is after comment removal
- Extract/validate plain domains via DOMAIN_RE
- Dedupe while preserving order; final sort happens by caller
"""

from re import IGNORECASE, compile
from typing import Iterable, List, Optional, Set, Tuple

from .models import Source

COMMENT_LINE_RE = compile(r"^\s*(#|!|//|;)")
INLINE_COMMENT_RE = compile(r"\s+(#|!|//|;).*$")
DOMAIN_RE = compile(
    r"(?i)^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$"
)
HTML_TAG_RE = compile(
    r"^\s*<|<[a-z/!?]|data-[a-z-]+=|<meta\s|<script|<style|<link|<html|<body|<div|<head|<title",
    IGNORECASE,
)
ABP_PATTERN_RE = compile(r"^\|\||^@@")
REGEX_PATTERN_RE = compile(r"^/.*/$|^\(.*\)\$$|[\[\](){}*+?|\\]")
PIHOLE_REGEX_RE = compile(r"^\([^)]+\)(.+)\$$")
ABP_WILDCARD_RE = compile(r"^(@@)?\|\|(.+?)\^?$")

HOSTS_LINE_RE = compile(r"^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+(.+)$")
LEADING_IP_RE = compile(r"^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s*")


SCHEME_ABP_RE = compile(r"^\|https?://([^/\^]+)")
SINGLE_PIPE_RE = compile(r"^\|([^\^/]+)\^?")
ELEMENT_HIDING_RE = compile(r"#@?#|##")
ABP_OPTION_RE = compile(r"\$.*$")

DOMAIN_PREFIX_CAPTURE = r"([a-z0-9-]+\.)*"
DOMAIN_PREFIX_NOCAPTURE = r"(?:[a-z0-9-]+\.)*"
PIHOLE_SUBDOMAIN_ANCHOR = "(^|\\.)"
ANCHOR_START = "^"
ANCHOR_END = "$"


def _normalize_abp_wildcards(entry: str) -> str:
    """Normalize non-standard ABP wildcard patterns to valid syntax.

    Conservative normalization that only fixes clearly broken patterns:
    - ||*cdn.domain.com^ -> ||*.cdn.domain.com^ (missing dot after wildcard)
    - ||app.*.adjust.com^ -> ||*.adjust.com^ (wildcard-only label)
    - ||domain.google.*^ -> ||domain.google^ (wildcard TLD - not supported)
    - -domain.com^ -> ||-domain.com^ (missing || prefix)
    - @@|domain.com^| -> @@||domain.com^ (single pipe + trailing pipe)

    Patterns with mid-label wildcards like analytics*.domain.com are kept as-is
    since some blockers may support them or convert them internally.

    Args:
        entry: ABP-style pattern that may have non-standard wildcards

    Returns:
        Normalized ABP pattern
    """
    entry = entry.rstrip('|')
    entry = _ensure_abp_prefix(entry)

    match = ABP_WILDCARD_RE.match(entry)
    if not match:
        return entry

    allowlist = match.group(1) or ""
    domain_part = _normalize_wildcard_domain_part(match.group(2))

    return f"{allowlist}||{domain_part}^"


def _ensure_abp_prefix(entry: str) -> str:
    """Ensure entries ending with '^' use proper ABP prefixes (|| or @@||)."""
    if (
        entry.endswith('^')
        and not entry.startswith('||')
        and not entry.startswith('@@||')
    ):
        if entry.startswith('@@|') and not entry.startswith('@@||'):
            return '@@||' + entry[3:]
        if entry.startswith('@@'):
            return '@@||' + entry[2:]
        return '||' + entry
    return entry


def _normalize_wildcard_domain_part(domain_part: str) -> str:
    """Normalize wildcard usage within the domain part of an ABP rule."""
    if domain_part.startswith("*") and not domain_part.startswith("*."):
        next_char = domain_part[1] if len(domain_part) > 1 else ""
        if next_char.isalnum():
            domain_part = "*." + domain_part[1:]
        elif next_char in ("-", "_"):
            domain_part = domain_part[1:].lstrip("-_")

    if domain_part.endswith(".*"):
        domain_part = domain_part[:-2]

    if ".*." in domain_part:
        parts = domain_part.split(".")
        try:
            first_wildcard_idx = parts.index("*")
            remaining_parts = parts[first_wildcard_idx + 1 :]
            domain_part = "*." + ".".join(remaining_parts)
        except ValueError:
            pass

    while ".." in domain_part:
        domain_part = domain_part.replace("..", ".")

    return domain_part.strip(".")


def _extract_host_from_abp(entry: str) -> Optional[tuple]:
    """Attempt to extract (allowlist: bool, host: str) from an ABP rule.

    Returns None when the ABP rule is not DNS-relevant (element-hiding) or when
    no host can be reasonably extracted.
    """
    entry = ABP_OPTION_RE.sub('', entry)
    entry = entry.rstrip('|^')

    if ELEMENT_HIDING_RE.search(entry):
        return None

    allow = False
    e = entry.strip()
    if e.startswith('@@'):
        allow = True
        e = e[2:]

    m = SCHEME_ABP_RE.match(e)
    if m:
        host = m.group(1)
        host = host.split('@')[-1].split(':')[0]
        host = host.strip('.')
        return allow, host

    m = ABP_WILDCARD_RE.match(e)
    if m:
        host = m.group(2)
        if host.startswith('://'):
            host = host[3:]
        if host.startswith('http://') or host.startswith('https://'):
            host = host.split('://', 1)[-1]
        host = host.split('/')[0]
        host = host.split('@')[-1].split(':')[0]
        return allow, host

    m = SINGLE_PIPE_RE.match(e)
    if m:
        host = m.group(1).split('@')[-1].split(':')[0]
        host = host.strip('.')
        return allow, host

    token = e.split('^')[0].split('/')[0]
    if token and any(c.isalnum() for c in token):
        token = token.strip('|').strip()
        return allow, token

    return None


def _convert_regex_to_abp(regex: str) -> Optional[str]:
    """Convert regex pattern to ABP-style format if possible.

    Args:
        regex: The regex pattern to convert.

    Returns:
        ABP-style pattern if conversion is possible, None otherwise.
    """
    """
    Convert various regex inputs into a POSIX ERE suitable for Pi-hole (FTLDNS) where possible.

    Returns a POSIX-style regex string (anchored where reasonable) or None if the
    pattern is too complex or contains JS-only constructs.
    """

    if regex.startswith(PIHOLE_SUBDOMAIN_ANCHOR) and regex.endswith(ANCHOR_END):
        inner = regex[len(PIHOLE_SUBDOMAIN_ANCHOR) : -1]
        return _to_domain_abp(inner)

    pattern = _unwrap_slash_delimited(regex)

    if pattern.startswith(PIHOLE_SUBDOMAIN_ANCHOR) and pattern.endswith(ANCHOR_END):
        inner = pattern[len(PIHOLE_SUBDOMAIN_ANCHOR) : -1]
        return _to_domain_abp(inner)

    if pattern.startswith(ANCHOR_START) and pattern.endswith(ANCHOR_END):
        body = pattern[1:-1]
        inner = _strip_leading_domain_prefix(body)
        if inner is not None:
            return _to_domain_abp(inner)
        return None

    match = PIHOLE_REGEX_RE.match(regex)
    if match:
        domain_pattern = match.group(1)
        return _to_domain_abp(domain_pattern)

    return None


def _unwrap_slash_delimited(pattern: str) -> str:
    """Return inner content if the pattern is /.../ wrapped; else return as-is."""
    if pattern.startswith('/') and pattern.endswith('/') and len(pattern) >= 2:
        return pattern[1:-1]
    return pattern


def _strip_leading_domain_prefix(body: str) -> Optional[str]:
    r"""Strip leading domain prefix like (?:sub\.)* and return the remainder if present."""
    if body.startswith(DOMAIN_PREFIX_CAPTURE):
        return body[len(DOMAIN_PREFIX_CAPTURE) :]
    if body.startswith(DOMAIN_PREFIX_NOCAPTURE):
        return body[len(DOMAIN_PREFIX_NOCAPTURE) :]
    return None


def _to_domain_abp(dom: str) -> Optional[str]:
    d = dom.strip('.').replace('\\.', '.')
    if _is_valid_domain_part(d):
        return f"||{d}^"
    return None


def _categorize_entry(entry: str) -> Optional[str]:
    """Categorize an entry as 'abp', 'regex', or None if invalid.

    Args:
        entry: The non-domain entry to categorize.

    Returns:
        'abp' for ABP-style syntax, 'regex' for regular expressions, None for invalid entries.
    """

    if ELEMENT_HIDING_RE.search(entry):
        return None

    if ABP_PATTERN_RE.search(entry) or entry.startswith('|'):
        return 'abp'
    if REGEX_PATTERN_RE.search(entry):
        return 'regex'
    if entry.endswith('^') and not entry.startswith('('):
        return 'abp'
    return None


def generate_list(
    results: List[Tuple[str, List[str]]], sources: List, failed_sources: List[Source]
) -> Tuple[List[str], List[str], List[Source]]:
    """Merge results and return three lists: (domains, abp_rules, failed_sources).

    - Domains include plain domains and wildcard hostnames as-is.
    - ABP rules include AdBlock Plus style syntax (||domain^, etc.).
    - Regex patterns that cannot be converted to ABP are discarded.
    - Failed sources list is passed through for reporting.
    """
    label_to_lines = dict(results)
    merged: List[str] = []
    for s in sources:
        lines = label_to_lines.get(s.raw, [])
        merged.extend(lines)

    domains, non_domains = normalize_lines_split(merged)

    plain_domains: List[str] = []
    auxiliary: List[str] = []

    for domain in domains:
        if domain.startswith('*.'):
            cleaned = domain[2:]
            plain_domains.append(cleaned)
        else:
            plain_domains.append(domain)

    for entry in non_domains:
        category = _categorize_entry(entry)
        if category == 'abp':
            extracted = _extract_host_from_abp(entry)
            if extracted:
                allow, host = extracted
                clean_host = host.lstrip('*.').replace('*.', '').replace('*', '')
                if clean_host and _is_valid_domain_part(clean_host):
                    if allow:
                        auxiliary.append('@@||' + clean_host + '^')
                    else:
                        auxiliary.append('||' + clean_host + '^')
            else:
                normalized = _normalize_abp_wildcards(entry)
                m = ABP_WILDCARD_RE.match(normalized)
                if m:
                    host = m.group(2).lstrip('*.').replace('*.', '').replace('*', '')
                    if _is_valid_domain_part(host):
                        if normalized.startswith('@@'):
                            auxiliary.append('@@||' + host + '^')
                        else:
                            auxiliary.append('||' + host + '^')
        elif category == 'regex':
            converted = _convert_regex_to_abp(entry)
            if converted:
                auxiliary.append(converted)

    domains_sorted = sorted(_dedupe_preserve_order(plain_domains), key=str.lower)
    aux_sorted = sorted(_dedupe_preserve_order(auxiliary), key=str.lower)
    return domains_sorted, aux_sorted, failed_sources


def _strip_inline_comment(line: str) -> str:
    """Remove trailing inline comments introduced by #, !, //, or ;."""
    return INLINE_COMMENT_RE.sub("", line)


def _maybe_extract_domain(token: str) -> Optional[str]:
    """Validate and normalize a domain or wildcard token.

    Returns the lowercased domain without a trailing dot, or None if invalid.
    """
    token = token.strip().strip(".,")
    if not token:
        return None

    wildcard = False
    if token.startswith('*.'):
        wildcard = True
        core = token[2:]
    else:
        core = token

    if DOMAIN_RE.match(token):
        return token.rstrip('.').lower()

    try:
        puny = core.encode('idna').decode('ascii')
    except Exception:
        return None

    if wildcard:
        puny = '*.' + puny

    if DOMAIN_RE.match(puny):
        return puny.rstrip('.').lower()

    return None


def _dedupe_preserve_order(lines: Iterable[str]) -> List[str]:
    """Remove duplicates while preserving first occurrence order."""
    seen: Set[str] = set()
    out: List[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def normalize_lines_split(lines: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Normalize lines and split into (domains, regexes).

    - Non-comment, non-empty lines that are not domains are kept in regexes after inline comment removal (no conversion).
    - Plain domains and wildcards are added to domains; wildcards are NOT expanded into regexes.
    - HTML tags and attributes are filtered out.
    """
    domains: List[str] = []
    regexes: List[str] = []
    for raw in lines:
        if COMMENT_LINE_RE.search(raw):
            continue
        if HTML_TAG_RE.search(raw):
            continue
        line = _strip_inline_comment(raw).strip()
        if not line:
            continue

        hosts_match = HOSTS_LINE_RE.match(line)
        if hosts_match:
            tokens = hosts_match.group(1).split()
            for t in tokens:
                d = _maybe_extract_domain(t)
                if d:
                    domains.append(d)
            continue

        m = LEADING_IP_RE.match(line)
        if m:
            rest = line[m.end() :].strip()
            if rest:
                tokens = rest.split()
                for t in tokens:
                    d = _maybe_extract_domain(t)
                    if d:
                        domains.append(d)
                continue

        dom = _maybe_extract_domain(line)
        if dom:
            domains.append(dom)
            continue

        kept = line
        if kept:
            regexes.append(kept)
    return domains, regexes


def _is_valid_domain_part(domain: str) -> bool:
    """Check if domain part is valid (no leading/trailing hyphens, etc.)."""
    if not domain:
        return False
    labels = domain.split('.')
    for label in labels:
        if not label:
            return False
        if label.startswith('-') or label.endswith('-'):
            return False
        if label == '*':
            continue
        if not any(c.isalnum() for c in label):
            return False
    return True


def separate_blocklist_whitelist(
    adlist_entries: List[str], whitelist_entries: List[str]
) -> Tuple[List[str], List[str]]:
    """Separate entries into proper blocklist and whitelist, removing invalid entries.

    Moves @@|| entries from adlist to whitelist (removing @@ prefix).
    Validates domain parts and removes entries with invalid domains.
    Deduplicates across both lists.

    Args:
        adlist_entries: Current adlist entries (may contain @@|| entries)
        whitelist_entries: Current whitelist entries

    Returns:
        Tuple of (cleaned_adlist, cleaned_whitelist) with proper separation
    """

    blocklist_set: Set[str] = set()
    whitelist_set: Set[str] = set()

    for e in adlist_entries:
        _process_entry_preserve_abp(
            e,
            to_whitelist=False,
            blocklist_set=blocklist_set,
            whitelist_set=whitelist_set,
        )

    for e in whitelist_entries:
        _process_entry_preserve_abp(
            e,
            to_whitelist=True,
            blocklist_set=blocklist_set,
            whitelist_set=whitelist_set,
        )

    whitelist_keys = {_normalize_key(x) for x in whitelist_set}
    cleaned_block = []
    for b in sorted(blocklist_set, key=str.lower):
        if _normalize_key(b) in whitelist_keys:
            continue
        cleaned_block.append(b)

    cleaned_whitelist = sorted(whitelist_set, key=str.lower)
    cleaned_block = [b for b in cleaned_block if not b.startswith('@@')]

    return cleaned_block, cleaned_whitelist


def _process_entry_preserve_abp(
    raw: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
) -> None:
    """Process a single adlist/whitelist entry and add to appropriate set.

    Preserves ABP semantics, validates domains, and routes entries based on
    the to_whitelist flag.
    """
    entry = raw.strip()
    entry = ABP_OPTION_RE.sub('', entry)
    entry = entry.rstrip('|^')
    if not entry or entry.startswith('#'):
        return

    if entry.startswith('@@||'):
        domain_part = entry[4:].rstrip('^')
        if _is_valid_domain_part(domain_part):
            whitelist_set.add(f"@@||{domain_part}^")
        return

    if entry.startswith('@@'):
        rest = entry[2:]
        if rest.startswith('||'):
            domain_part = rest[2:].rstrip('^')
            if _is_valid_domain_part(domain_part):
                whitelist_set.add(f"@@||{domain_part}^")
            return
        entry = rest

    if entry.startswith('||'):
        domain_part = entry[2:].rstrip('^')
        if domain_part.startswith('://'):
            domain_part = domain_part[3:]
        if '://' in domain_part:
            domain_part = domain_part.split('://', 1)[-1]
        if '/' in domain_part:
            domain_part = domain_part.split('/', 1)[0]
        if '@' in domain_part:
            domain_part = domain_part.split('@')[-1]
        if ':' in domain_part:
            domain_part = domain_part.split(':', 1)[0]
        if _is_valid_domain_part(domain_part):
            if to_whitelist:
                whitelist_set.add(f"@@||{domain_part}^")
            else:
                blocklist_set.add(f"||{domain_part}^")
        return

    if (
        REGEX_PATTERN_RE.search(entry)
        or entry.startswith('^')
        or entry.endswith('$')
        or (entry.startswith('/') and entry.endswith('/'))
    ):
        if to_whitelist:
            whitelist_set.add(entry)
        else:
            blocklist_set.add(entry)
        return

    candidate = entry
    if candidate.startswith('*.'):
        candidate = candidate[2:]
    candidate = candidate.replace('*.', '').replace('*', '')

    if _is_valid_domain_part(candidate):
        if to_whitelist:
            whitelist_set.add(candidate)
        else:
            blocklist_set.add(candidate)
    else:
        return


def _normalize_key(x: str) -> str:
    """Normalize ABP entries to a comparable key without prefixes/suffixes."""
    s = x
    if s.startswith('@@'):
        s = s[2:]
    if s.startswith('||'):
        s = s[2:]
    return s.rstrip('^')
