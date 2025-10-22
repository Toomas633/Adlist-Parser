"""I/O helpers for source loading and output writing.

Parses flexible JSON shapes, resolves relative file paths against the JSON
location, and writes text outputs with LF endings.
"""

from json import load
from os import makedirs, path
from re import I, search
from typing import List
from urllib import parse

from .models import Source


def load_sources(file: str) -> List[Source]:
    """Load sources from JSON and resolve relative file paths.

    Args:
        file: Path to the JSON file that lists adlist sources.

    Returns:
        A list of ``Source`` objects; local files include an absolute
        ``resolved_path``.
    """
    base_dir = path.dirname(path.abspath(file))
    with open(file, "r", encoding="utf-8") as f:
        data = load(f)

    items = _extract_items_from_json(data)
    if not items:
        raise ValueError("No sources found in input JSON")

    sources: List[Source] = []
    for raw in items:
        if _looks_like_path(raw) and not _is_urlish(raw):
            abs_path = (
                raw if path.isabs(raw) else path.abspath(path.join(base_dir, raw))
            )
            sources.append(Source(raw=raw, resolved_path=abs_path))
        else:
            sources.append(Source(raw=raw))

    return sources


def _is_urlish(s: str) -> bool:
    """Return True if the string looks like a URL we fetch via HTTP(S) or file URI.

    Notes:
        On Windows, absolute paths like "C:\\path\\to\\file.txt" may be parsed
        by ``urlparse`` as having a single-letter scheme ("c"). We avoid
        misclassifying such paths by only treating http/https/file schemes as URLish
        and by requiring the typical "://" delimiter for other cases.
    """
    parsed = parse.urlparse(s)
    if parsed.scheme in {"http", "https", "file"}:
        return True
    return "://" in s


def _looks_like_path(s: str) -> bool:
    """Heuristically check if a string resembles a filesystem path.

    Uses presence of path separators or common list/hosts extensions.
    """
    return any(sep in s for sep in ("/", "\\")) or bool(
        search(r"\.(txt|list|hosts)$", s, I)
    )


def _extract_items_from_json(data: object) -> List[str]:
    """Extract source strings from supported JSON shapes.

    Supported shapes:
      - list[str]
      - dict with keys: "lists", "urls", "adlists", "sources"
    """
    if isinstance(data, list):
        return [str(x) for x in data]
    if isinstance(data, dict):
        items: List[str] = []
        for key in ("lists", "urls", "adlists", "sources"):
            val = data.get(key)
            if isinstance(val, list):
                items.extend(str(x) for x in val)
        return items
    raise ValueError(
        "Unsupported JSON format: expected array or object with lists/urls/adlists/sources"
    )


def write_output(file: str, lines: List[str], header: str = ""):
    """Write lines to a file (LF endings), creating parent directory.

    Appends a trailing LF only when ``lines`` is non-empty.

    Args:
        file: Output file path.
        lines: Lines to write.
        header: Optional header text to prepend.
    """
    makedirs(path.dirname(path.abspath(file)) or ".", exist_ok=True)
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        if header:
            f.write(header)
            if not header.endswith("\n"):
                f.write("\n")
        f.write("\n".join(lines) + ("\n" if lines else ""))
