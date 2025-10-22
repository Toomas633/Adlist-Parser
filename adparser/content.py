"""Normalization utilities for adlist content.

Parses raw lines into domain tokens and auxiliary rules, safely removes
comments/HTML, retains ABP/regex-like entries for later handling, and
deduplicates while preserving first-seen order.
"""

from typing import Iterable, List, Optional, Set, Tuple

from adparser.constants import (
    ABP_OPTION_RE,
    ABP_PATTERN_RE,
    ABP_WILDCARD_RE,
    ANCHOR_END,
    ANCHOR_START,
    COMMENT_LINE_RE,
    DOMAIN_PREFIX_CAPTURE,
    DOMAIN_PREFIX_NOCAPTURE,
    DOMAIN_RE,
    ELEMENT_HIDING_RE,
    HOSTS_LINE_RE,
    HTML_TAG_RE,
    INLINE_COMMENT_RE,
    LEADING_IP_RE,
    PIHOLE_REGEX_RE,
    PIHOLE_SUBDOMAIN_ANCHOR,
    REGEX_PATTERN_RE,
    SCHEME_ABP_RE,
    SINGLE_PIPE_RE,
)

from .models import Source


def _normalize_abp_wildcards(entry: str) -> str:
    """Normalize clearly broken ABP wildcard patterns.

    Fixes a few conservative cases (e.g., leading "*" without dot, wildcard
    label-only segments, wildcard TLD). Mid-label wildcards are left intact.

    Args:
        entry: ABP-style rule string.

    Returns:
        A normalized ABP rule string.
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
    """Ensure entries ending with '^' have a proper ABP prefix (|| or @@||)."""
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
    """Normalize wildcard usage within the domain portion of an ABP rule."""
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
    """Extract a host from an ABP rule.

    Returns (allowlist, host) when a DNS-relevant host can be derived; None
    for element-hiding or non-host rules.
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
    r"""Convert a simple anchored regex to an ABP-style domain rule.

    Handles common Pi-hole-style anchors like (^|\.)domain\.tld$ and
    slash-delimited patterns. Returns an ABP rule (e.g., ``||domain.tld^``)
    or None if the pattern is too complex.
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
    """Return inner content if the pattern is /.../ wrapped; otherwise return as-is."""
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
    """Return an ABP rule for a validated domain-like pattern.

    Converts an escaped or dotted domain fragment into ``||domain^`` if it
    passes a conservative domain-part validation; otherwise returns None.
    """
    d = dom.strip('.').replace('\\.', '.')
    if _is_valid_domain_part(d):
        return f"||{d}^"
    return None


def _categorize_entry(entry: str) -> Optional[str]:
    """Classify a non-domain entry as 'abp', 'regex', or None.

    Args:
        entry: The non-domain entry to classify.

    Returns:
        'abp' for ABP-style syntax, 'regex' for regex-like lines, or None.
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
    results: List[Tuple[Source, List[str]]],
    sources: List[Source],
    failed_sources: List[Source],
) -> Tuple[List[str], List[str], List[Source]]:
    """Merge fetched lines and split into domains and ABP rules.

    - Domains include plain domains and wildcard tokens (not expanded).
    - ABP rules include AdBlock Plus style rules (e.g., ``||domain^``).
    - Regex patterns that can't be converted to ABP are dropped.
    - Failed sources are passed through unchanged.
    """
    merged = _merge_in_source_order(results, sources)
    domains, non_domains = normalize_lines_split(merged)

    plain_domains = _clean_plain_domains(domains)
    auxiliary: List[str] = []
    for entry in non_domains:
        auxiliary.extend(_aux_from_non_domain(entry))

    return plain_domains, auxiliary, failed_sources


def _merge_in_source_order(
    results: List[Tuple[Source, List[str]]], sources: List[Source]
) -> List[str]:
    """Merge fetched results respecting original source order."""
    label_to_lines: dict[str, List[str]] = {key.raw: lines for key, lines in results}
    merged: List[str] = []
    for s in sources:
        merged.extend(label_to_lines.get(s.raw, []))
    return merged


def _clean_plain_domains(domains: List[str]) -> List[str]:
    """Strip leading '*. ' for wildcard tokens; keep order."""
    out: List[str] = []
    for d in domains:
        out.append(d[2:] if d.startswith('*.') else d)
    return out


def _aux_from_non_domain(entry: str) -> List[str]:
    """Produce auxiliary ABP rules from a non-domain entry, if any."""
    category = _categorize_entry(entry)
    if category == 'abp':
        return _aux_from_abp_entry(entry)
    if category == 'regex':
        return _aux_from_regex_entry(entry)
    return []


def _aux_from_abp_entry(entry: str) -> List[str]:
    """Derive auxiliary ABP rules from a single ABP-style entry.

    Prefers extracting a concrete host from the rule; otherwise normalizes
    wildcards conservatively and emits an ABP rule when the host validates.
    """
    out: List[str] = []
    extracted = _extract_host_from_abp(entry)
    if extracted:
        allow, host = extracted
        clean_host = host.lstrip('*.').replace('*.', '').replace('*', '')
        if clean_host and _is_valid_domain_part(clean_host):
            out.append(('@@||' if allow else '||') + clean_host + '^')
        return out

    normalized = _normalize_abp_wildcards(entry)
    m = ABP_WILDCARD_RE.match(normalized)
    if m:
        host = m.group(2).lstrip('*.').replace('*.', '').replace('*', '')
        if _is_valid_domain_part(host):
            out.append(('@@||' if normalized.startswith('@@') else '||') + host + '^')
    return out


def _aux_from_regex_entry(entry: str) -> List[str]:
    """Convert a simple regex-like entry to ABP, if possible."""
    converted = _convert_regex_to_abp(entry)
    return [converted] if converted else []


def _strip_inline_comment(line: str) -> str:
    """Remove trailing inline comments introduced by #, !, //, or ;."""
    return INLINE_COMMENT_RE.sub("", line)


def _maybe_extract_domain(token: str) -> Optional[str]:
    """Validate and normalize a domain or wildcard token.

    Returns the lowercased domain (no trailing dot) or None if invalid.
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
    except UnicodeError:
        return None

    if wildcard:
        puny = '*.' + puny

    if DOMAIN_RE.match(puny):
        return puny.rstrip('.').lower()

    return None


def normalize_lines_split(lines: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Normalize lines and split into (domains, non-domains).

    - Keeps non-domain lines (after inline comment removal) as-is.
    - Adds plain domains and wildcards to domains (no expansion).
    - Filters out HTML-ish content.
    """
    domains: List[str] = []
    non_domains: List[str] = []
    for raw in lines:
        if _should_skip_raw(raw):
            continue
        line = _strip_inline_comment(raw).strip()
        if not line:
            continue

        hosts_domains = _extract_domains_from_hosts(line)
        if hosts_domains is not None:
            domains.extend(hosts_domains)
            continue

        ip_domains = _extract_domains_from_leading_ip(line)
        if ip_domains is not None:
            domains.extend(ip_domains)
            continue

        dom = _maybe_extract_domain(line)
        if dom:
            domains.append(dom)
            continue

        non_domains.append(line)
    return domains, non_domains


def _should_skip_raw(raw: str) -> bool:
    """Return True if a raw line should be ignored (comments/HTML)."""
    return bool(COMMENT_LINE_RE.search(raw) or HTML_TAG_RE.search(raw))


def _extract_domains_from_hosts(line: str) -> Optional[List[str]]:
    """Extract domains from a full hosts-format line if matched."""
    m = HOSTS_LINE_RE.match(line)
    if not m:
        return None
    tokens = m.group(1).split()
    out: List[str] = []
    for t in tokens:
        d = _maybe_extract_domain(t)
        if d:
            out.append(d)
    return out


def _extract_domains_from_leading_ip(line: str) -> Optional[List[str]]:
    """Strip a leading hosts IP and extract domain tokens if present."""
    m = LEADING_IP_RE.match(line)
    if not m:
        return None
    rest = line[m.end() :].strip()
    if not rest:
        return []
    out: List[str] = []
    for t in rest.split():
        d = _maybe_extract_domain(t)
        if d:
            out.append(d)
    return out


def _is_valid_domain_part(domain: str) -> bool:
    """Return True if the domain labels are syntactically valid."""
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
    """Separate entries into blocklist and whitelist and clean them.

    - Moves @@|| entries from adlist into whitelist.
    - Validates domain parts and drops invalid items.
    - Deduplicates and removes block entries shadowed by whitelist.

    Args:
        adlist_entries: Current adlist entries (may include @@|| items).
        whitelist_entries: Current whitelist entries.

    Returns:
        (cleaned_adlist, cleaned_whitelist).
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

    blocklist_set = _filter_covered(blocklist_set, '||')
    whitelist_set = _filter_covered(whitelist_set, '@@||')

    whitelist_keys = {_normalize_key(x) for x in whitelist_set}
    cleaned_block = []
    for b in sorted(blocklist_set, key=str.lower):
        if _normalize_key(b) in whitelist_keys:
            continue
        cleaned_block.append(b)

    cleaned_whitelist = sorted(whitelist_set, key=str.lower)
    cleaned_block = [b for b in cleaned_block if not b.startswith('@@')]

    return cleaned_block, cleaned_whitelist


def _ancestors(domain: str) -> List[str]:
    """Return a list of ancestor domains from most-specific to TLD.

    Example: ``a.b.c`` -> ``['a.b.c', 'b.c', 'c']``
    """
    parts = domain.split('.')
    return ['.'.join(parts[i:]) for i in range(len(parts))]


def _filter_covered(entries: Set[str], abp_prefix: str) -> Set[str]:
    """Remove entries covered by broader ABP rules and keep regex-like ones.

    For ABP-prefixed entries, ensures no parent entry already exists; for
    non-ABP entries, keeps regex-like lines and drops domain tokens covered
    by existing ABP rules.
    """
    abp_domains = {_normalize_key(e) for e in entries if e.startswith(abp_prefix)}

    def covered_by_abp(dom: str) -> bool:
        for anc in _ancestors(dom):
            if anc in abp_domains:
                return True
        return False

    filtered: Set[str] = set()

    for e in (x for x in entries if x.startswith(abp_prefix)):
        key = _normalize_key(e)
        parents = _ancestors(key)[1:]
        if any(p in abp_domains for p in parents):
            continue
        filtered.add(e if e.endswith('^') else (abp_prefix + key + '^'))

    for e in (x for x in entries if not x.startswith(abp_prefix)):
        if _is_regex_like_entry(e):
            filtered.add(e)
            continue
        dom = e.lstrip('*.')
        if covered_by_abp(dom):
            continue
        filtered.add(e)

    return filtered


def _is_regex_like_entry(entry: str) -> bool:
    """Heuristic to decide if an entry should be treated as regex-like."""
    return bool(
        REGEX_PATTERN_RE.search(entry)
        or entry.startswith('^')
        or entry.endswith('$')
        or (entry.startswith('/') and entry.endswith('/'))
    )


def _process_entry_preserve_abp(
    raw: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
) -> None:
    """Process one entry and route it to blocklist or whitelist.

    Preserves ABP semantics and validates domain syntax.
    This function is intentionally small and delegates work to helpers
    to reduce cognitive complexity.
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

    if _handle_abp_like(entry, to_whitelist, blocklist_set, whitelist_set):
        return

    if _handle_regex_like(entry, to_whitelist, blocklist_set, whitelist_set):
        return

    _handle_candidate_domain(entry, to_whitelist, blocklist_set, whitelist_set)


def _handle_abp_like(
    entry: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
) -> bool:
    """Return True if entry was recognized and handled as ABP-style.

    This delegates the pipe-prefixed handling to a focused helper to keep
    complexity low.
    """
    if entry.startswith('@@'):
        rest = entry[2:]
        if rest.startswith('||'):
            domain_part = rest[2:].rstrip('^')
            if _is_valid_domain_part(domain_part):
                whitelist_set.add(f"@@||{domain_part}^")
            return True
        entry = rest

    if entry.startswith('||') or entry.startswith('|'):
        return _handle_pipe_entry(entry, to_whitelist, blocklist_set, whitelist_set)

    return False


def _handle_pipe_entry(
    entry: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
) -> bool:
    """Handle entries starting with '||' or '|' and add to the sets.

    Returns True when handled (even if domain invalid), False otherwise.
    """
    domain_part = entry[2:] if entry.startswith('||') else entry.lstrip('|')
    domain_part = domain_part.rstrip('^')

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
    return True


def _handle_regex_like(
    entry: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
) -> bool:
    """Return True if entry was recognized and handled as regex-like."""
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
        return True
    return False


def _handle_candidate_domain(
    entry: str,
    to_whitelist: bool,
    blocklist_set: Set[str],
    whitelist_set: Set[str],
):
    """Normalize wildcard candidate and add to appropriate set if valid."""
    candidate = entry
    if candidate.startswith('*.'):
        candidate = candidate[2:]
    candidate = candidate.replace('*.', '').replace('*', '')

    if _is_valid_domain_part(candidate):
        if to_whitelist:
            whitelist_set.add(candidate)
        else:
            blocklist_set.add(candidate)


def _normalize_key(x: str) -> str:
    """Normalize an entry to a comparable key without ABP prefixes/suffixes."""
    s = x
    if s.startswith('@@'):
        s = s[2:]
    if s.startswith('||'):
        s = s[2:]
    return s.rstrip('^')
