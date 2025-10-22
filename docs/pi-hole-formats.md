# Pi-hole adlists, accepted formats, and recommended conversions

This document is a project-agnostic reference covering everything relevant to adlists and accepted input formats for Pi-hole (FTLDNS / gravity). It collects the authoritative formats, parsing rules, conversion recipes, DB/CLI notes, regex guidance, and examples contributors or tools can rely on when preparing lists for Pi-hole.

Use this document when building exporters, converters, or when curating adlists for Pi-hole. It intentionally stays generic and implementation-agnostic.

## Summary — what Pi-hole accepts

- Hosts-style entries (common in public blocklists): `0.0.0.0 example.com` or `127.0.0.1 example.com` — gravity extracts hostnames.
- Plain domain names: `example.com` (one per line) — treated as a domain block entry.
- Regex patterns: FTLDNS supports POSIX Extended Regular Expressions (egrep-like). Regex filters are stored separately and applied by FTLDNS.
- Allowlist (whitelist) entries and allowlist-regex: Pi-hole supports exact and regex allowlist entries which take precedence over block rules.
- Pi-hole does not natively implement Adblock Plus (ABP) operators — many ABP rules must be converted to domains or regex to be effective in Pi-hole.

## Contract (inputs / outputs / success criteria)

- Inputs: arbitrary lines from adlists (hosts files, ABP/adblock rules, domains, regexes, comments, local files, remote URLs).
- Outputs for Pi-hole consumption (recommended):
  - Domains-only list (line-delimited domain names) suitable for gravity domain ingestion.
  - POSIX ERE regex list for FTLDNS's regex table.
  - Allowlist (whitelist) list for exceptions.
- Success criteria: outputs are valid for Pi-hole ingestion (or via `pihole` CLI), deduplicated, validated, and minimize false positives / expensive regex.

## Parsing & normalization priority (apply in this order)

1. Trim and normalize whitespace; preserve case only for explicit regex sections if necessary.
2. Skip blank lines and whole-line comments (leading `#`, `;`, `//`, or obvious HTML/XML fragments when lists embed markup).
3. Hosts-file detection: if a line starts with an IP (e.g., `0.0.0.0`, `127.0.0.1`, `::1`) extract following hostname tokens as domain entries.
4. Recognize ABP/adblock rule patterns (start with `||`, `|`, `@@`, contain `^`, `*`, `|`, or element-hiding `##`). Route to ABP normalization.
5. Detect slash-delimited or anchored regex (`/pattern/`, `^pattern$`, `pattern$`) and validate/convert to POSIX ERE.
6. Otherwise, treat token as a plain domain (validate with a domain regex/IDN conversion) and add to domain output.

## Common input types and recommended handling

- Hosts-file lines

  - Example: `0.0.0.0 ads.example.com # comment`
  - Action: extract `ads.example.com` and include as domain entry. If multiple hostnames are present, include all.

- Plain domains

  - Example: `tracker.example.net`
  - Action: add to the domains-only output after validation (underscore or invalid characters should be rejected).

- ABP (Adblock Plus / uBlock Origin) style lines — normalize where possible

  - `||example.com^` → extract and emit `example.com` (domain output) or convert to an anchored regex to preserve subdomain semantics when needed.
  - `@@||example.com^` → convert to an allowlist (whitelist) entry: `example.com`.
  - `|http://example.com/path` → extract host `example.com` (strip scheme/path).
  - Element-hiding rules (`example.com##.ad`) — not DNS-relevant: drop for Pi-hole or preserve in an auxiliary ABP file for non-DNS blockers.

- ABP wildcards

  - `||*.cdn.example.com^` or `||*cdn.example.com^`
    - Option 1 (conservative): emit `cdn.example.com` (broader match, safe and performant).
    - Option 2 (precise): convert to a POSIX ERE like `(^|\.)[^.]+\.cdn\.example\.com$` (ensure safe/performance-tested).
    - Recommendation: prefer Option 1 for automated pipelines; use Option 2 when a strict sublabel match is required and regex cost is acceptable.

- Regex inputs

  - Pi-hole/FTLDNS uses POSIX Extended Regular Expressions. Acceptable forms include anchored patterns like `(^|\.)example\.com$` or `^example\.com$`.
  - JS-style or complex regex (lookarounds, JS-only constructs) may not be convertible — place in a review list or in an auxiliary ABP file.

## Conversion recipes (patterns to implement)

- Hosts-line extraction

  - Pattern: `^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+(\S+(?:\s+\S+)*)` → split and validate host tokens.

- ABP prefix rules

  - `^@@?\|\|(.*?)\^?$` → capture the host spec, strip ABP tokens; if `@@` present mark as allowlist.
  - `^\|https?://([^/]+)` → capture hostname from scheme-prefixed ABP rule.

- Fallback

  - If a line contains no ABP markers and is not hosts-style or regex-like, treat as a domain and validate with a domain regex.

## Regex flavor, validation, and performance

- FTLDNS implements POSIX Extended Regular Expressions (egrep-like) with some Pi-hole-specific augmentations. Favor anchored, simple expressions.
- Avoid catastrophic or overly broad regex like unbounded `.*` across label separators — these are expensive and may degrade FTL performance.
- For conversions that produce expensive regex, prefer emitting a domain-level fallback instead of the complex regex.

## Gravity, CLI, and DB notes

- Gravity is the Pi-hole process that downloads subscribed lists, attempts domain extraction, dedupes and writes the final domain set to the `gravity` table in `/etc/pihole/gravity.db`.
- Use the `pihole` CLI for safe modifications where possible:
  - `pihole --regex '^example\.com$'` — add regex manually
  - `pihole allow example.com` — add exact allowlist entry
  - `pihole -g` — run gravity (rebuild lists)
  - `pihole reloadlists` — reload lists without restarting the DNS service
- DB: gravity writes to DB tables like `adlist`, `domainlist`, `gravity`, and `regex` — upstream schema may evolve, so prefer CLI where available.

## Output recommendations (formats/files)

- Domains-only list: newline-delimited domain names, LF endings. Suitable for Pi-hole gravity ingestion.
- Regex list: newline-delimited POSIX ERE expressions; keep entries anchored where possible.
- Allowlist: newline-delimited exact domains for exceptions.
- Auxiliary ABP file (optional): preserve ABP-specific rules and element-hiding directives for other blockers (AdGuard/uBO), or for manual review.

## Validation rules and IDN handling

- Domain validation essentials: labels <= 63 chars, total domain <= 253 chars, allowed characters per label (letters, digits, hyphen, no leading/trailing hyphen), no control characters/spaces.
- Convert IDNs to punycode when preparing outputs for Pi-hole (use `idna` encoding).

## Edge-cases and recommended defaults

- Prefer safe broadening: when precise conversion would create unsafe or costly regex, emit a broader domain-level entry.
- Do not add IP literals or CNAME-only lines as domain blocks — they are not valid domain names.
- Ensure deduplication across outputs: allowlist wins over blocklist; if a domain is allowlisted exclude it from block outputs.

## Testing checklist and verification

Add tests or verification steps covering:

1. Hosts-line parsing (multiple hostnames).
2. ABP → domain conversion, including `||` and `@@` cases.
3. ABP wildcard handling: confirm conservative (domain) and precise (regex) behaviors.
4. Regex acceptance: ensure converted/kept regex are valid POSIX ERE.
5. Element-hiding rules are not included in domain/regex outputs.

## Implementation guidance for converters / toolchains

- Provide a small, single-responsibility `normalize_line(line)` helper that returns a typed result: `('skip'|'domain'|'regex'|'allow'|'abp-preserve', value)`.
- Keep an append-only auxiliary file for unconvertible ABP lines so they can be re-used by non-DNS tools.
- Provide a conservative default path (emit domain) and an opt-in precise path (emit regex) for ABP wildcards.

## References (authoritative)

- Pi-hole docs (pihole CLI & gravity): https://docs.pi-hole.net/main/pihole-command/
- FTLDNS / Regex: https://docs.pi-hole.net/regex/
- Pi-hole GitHub wiki: https://github.com/pi-hole/pi-hole/wiki/
- Community forum: https://discourse.pi-hole.net/

---

Revision: generic, project-agnostic reference for Pi-hole adlists and formats. Keep links current and update when Pi-hole upstream behavior changes.
