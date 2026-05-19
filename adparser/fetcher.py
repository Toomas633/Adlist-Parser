"""Concurrent fetcher for HTTP(S) and local sources.

Uses a thread pool and a custom User-Agent to retrieve text content from
URLs and local files.
"""

from concurrent import futures
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from sys import version
from typing import Callable, List, Optional, Tuple
from urllib import parse, request

from .constants import FETCH_CACHE_DIR
from .models import Source

USER_AGENT = (
    "Adlist-Parser/1.0 (+https://github.com/Toomas633/Adlist-Parser) Python/"
    + version.split()[0]
)


def fetch(
    sources: List[Source],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[Tuple[Source, List[str]]], List[Source]]:
    """Fetch all sources concurrently and return raw lines per source.

    Args:
        sources: List of Source objects to fetch
        progress_callback: Optional callback function that receives (completed, total)

    Returns a tuple of:
    - List of ``(label, lines)`` tuples where ``label`` is the
      source's ``raw`` string and ``lines`` are the split lines of content.
    - List of failed source labels that could not be fetched.
    """
    results: List[Tuple[Source, List[str]]] = []
    failed_sources: List[Source] = []
    total_sources = len(sources)
    completed = 0

    with futures.ThreadPoolExecutor(max_workers=max(1, 16)) as ex:
        fut_to_src = {ex.submit(_fetch_one, s): s for s in sources}
        for fut in futures.as_completed(fut_to_src):
            source, lines = fut.result()
            if len(lines) == 1 and lines[0].startswith("# ERROR fetching"):
                failed_sources.append(source)
            results.append((source, lines))
            completed += 1
            if progress_callback:
                progress_callback(completed, total_sources)
    return results, failed_sources


def _cache_path(url: str) -> Path:
    """Return the cache file path for a URL, keyed by its SHA-256 hash."""
    key = sha256(url.encode()).hexdigest()
    return Path(FETCH_CACHE_DIR) / f"{key}.txt"


def _save_to_cache(url: str, text: str) -> None:
    """Persist fetched content to the cache (non-fatal on write errors)."""
    try:
        cache_dir = Path(FETCH_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(url).with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(_cache_path(url))
    except OSError:
        pass


def _load_from_cache(url: str) -> Optional[str]:
    """Return cached content for a URL, or None if not cached."""
    try:
        path = _cache_path(url)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return None


def _fetch_one(source: Source) -> Tuple[Source, List[str]]:
    """Fetch or read one source and return its split lines.

    Args:
        source: Source descriptor (URL, file:// URI, or local path).

    Returns:
        ``(source, lines)`` where ``lines`` are the text lines (or a single
        error marker line starting with ``# ERROR fetching``).
    """
    try:
        if source.is_url():
            text = _http_fetch(source.raw)
            _save_to_cache(source.raw, text)
        elif source.is_file_url():
            path = request.url2pathname(parse.urlparse(source.raw).path)
            text = _read_file(path)
        else:
            path = source.resolved_path or source.raw
            text = _read_file(path)
        lines = text.splitlines()
        return source, lines
    except (OSError, ValueError) as e:
        if source.is_url():
            cached = _load_from_cache(source.raw)
            if cached is not None:
                return source, cached.splitlines()
        return source, [f"# ERROR fetching {source}: {e}"]


def _read_file(path: str) -> str:
    """Read a text file as UTF-8, replacing invalid sequences."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _http_fetch(url: str) -> str:
    """Fetch text content from an HTTP(S) URL.

    Uses a 30s request timeout. Propagates network-related errors.
    """
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    with closing(request.urlopen(req, timeout=30.0)) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")
