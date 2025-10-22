"""Project-wide constants and compiled regular expressions used by Adlist-Parser.

These values define default input/output paths and the conservative regex
patterns used throughout parsing (hosts lines, ABP rules, Pi-hole regex
conversion, comments, and inline options). The module is stdlib-only and the
paths are repository-relative and OS-agnostic.
"""

from re import IGNORECASE
from re import compile as re_compile

ADLISTS = "data/adlists.json"
ADLIST_OUTPUT = "output/adlist.txt"
OLD_ADLIST = "data/old_adlist.txt"
WHITELISTS = "data/whitelists.json"
WHITELIST_OUTPUT = "output/whitelist.txt"

COMMENT_LINE_RE = re_compile(r"^\s*(#|!|//|;)")
INLINE_COMMENT_RE = re_compile(r"\s+(#|!|//|;).*$")
DOMAIN_RE = re_compile(
    r"(?i)^(?:\*\.)?"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$"
)
HTML_TAG_RE = re_compile(
    r"(?:^\s*<|<(?:[a-z/!?]|meta\s|script|style|link|html|body|div|head|title)|data-[a-z-]+=)",
    IGNORECASE,
)
ABP_PATTERN_RE = re_compile(r"^(?:\|\||@@)")
REGEX_PATTERN_RE = re_compile(r"(?:^/.*/$|^\(.*\)\$$|[\[\](){}*+?|\\])")
PIHOLE_REGEX_RE = re_compile(r"^\([^)]+\)(.+)\$$")
ABP_WILDCARD_RE = re_compile(r"^(@@)?\|\|(.+?)\^?$")
HOSTS_LINE_RE = re_compile(r"^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+(.+)$")
LEADING_IP_RE = re_compile(r"^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s*")
SCHEME_ABP_RE = re_compile(r"^\|https?://([^/\^]+)")
SINGLE_PIPE_RE = re_compile(r"^\|([^\^/]+)\^?")
ELEMENT_HIDING_RE = re_compile(r"#@?#")
ABP_OPTION_RE = re_compile(r"\$.*$")

DOMAIN_PREFIX_CAPTURE = r"([a-z0-9-]+\.)*"
DOMAIN_PREFIX_NOCAPTURE = r"(?:[a-z0-9-]+\.)*"
PIHOLE_SUBDOMAIN_ANCHOR = "(^|\\.)"
ANCHOR_START = "^"
ANCHOR_END = "$"
