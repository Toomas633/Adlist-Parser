"""File utilities for loading sources and writing outputs.

Parses flexible JSON formats for adlist sources and resolves relative
paths based on the JSON file's location. Also provides an LF-ending writer.
"""

from json import load
from os import makedirs, path
from re import I, search
from typing import List
from urllib import parse

from .models import Source


def load_sources(file: str) -> List[Source]:
    """Load source strings from input JSON and resolve relative file paths.

    Args:
        path: Path to the JSON file describing adlist sources.

    Returns:
        A list of ``Source`` objects with ``resolved_path`` set for local files.
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
    """Return True if the given string looks like a URL (has a scheme)."""
    parsed = parse.urlparse(s)
    return bool(parsed.scheme)


def _looks_like_path(s: str) -> bool:
    """Heuristically determine if a string looks like a filesystem path.

    Uses presence of path separators or typical text list extensions.
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
    """Write lines to a file ensuring parent directory exists and LF endings.

    Appends a trailing LF only when ``lines`` is non-empty.

    Args:
        file: Output file path.
        lines: Lines to write.
        header: Optional header comment block to prepend.
    """
    makedirs(path.dirname(path.abspath(file)) or ".", exist_ok=True)
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        if header:
            f.write(header)
            if not header.endswith("\n"):
                f.write("\n")
        f.write("\n".join(lines) + ("\n" if lines else ""))
