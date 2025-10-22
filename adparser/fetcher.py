"""Concurrent fetching utilities for sources.

Provides thread-pooled fetching for HTTP(S) URLs and local files with
retry/backoff behavior and a custom User-Agent.
"""

from concurrent import futures
from contextlib import closing
from sys import version
from typing import Callable, List, Optional, Tuple
from urllib import parse, request

from .models import Source

USER_AGENT = (
    "Adlist-Parser/1.0 (+https://github.com/Toomas633/Adlist-Parser) Python/"
    + version.split()[0]
)


def fetch(
    sources: List[Source],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[Tuple[str, List[str]]], List[Source]]:
    """Fetch all sources concurrently and return raw lines per source.

    Args:
        sources: List of Source objects to fetch
        progress_callback: Optional callback function that receives (completed, total)

    Returns a tuple of:
    - List of ``(label, lines)`` tuples where ``label`` is the
      source's ``raw`` string and ``lines`` are the split lines of content.
    - List of failed source labels that could not be fetched.
    """
    results: List[Tuple[str, List[str]]] = []
    failed_sources: List[Source] = []
    total_sources = len(sources)
    completed = 0

    with futures.ThreadPoolExecutor(max_workers=max(1, 16)) as ex:
        fut_to_src = {ex.submit(_fetch_one, s): s for s in sources}
        for fut in futures.as_completed(fut_to_src):
            source, lines = fut.result()
            if len(lines) == 1 and lines[0].startswith("# ERROR fetching"):
                failed_sources.append(source)
            results.append((source.raw, lines))
            completed += 1
            if progress_callback:
                progress_callback(completed, total_sources)
    return results, failed_sources


def _fetch_one(source: Source) -> Tuple[Source, List[str]]:
    """Fetch or read one source and return its lines.

    Args:
        source: Source descriptor (URL or local path).
        timeout: Per-request timeout for network fetches.
        retries: Retry count for network fetches.

    Returns:
        A tuple (label, lines) where label is the source identifier and
        lines is a list of raw text lines (or a single error comment line).
    """
    try:
        if source.is_url():
            text = _http_fetch(source.raw)
        elif source.is_file_url():
            path = request.url2pathname(parse.urlparse(source.raw).path)
            text = _read_file(path)
        else:
            path = source.resolved_path or source.raw
            text = _read_file(path)
        lines = text.splitlines()
        return source, lines
    except Exception as e:
        return source, [f"# ERROR fetching {source}: {e}"]


def _read_file(path: str) -> str:
    """Read a text file as UTF-8, replacing invalid sequences."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _http_fetch(url: str) -> str:
    """Fetch text content from an HTTP(S) URL with retries.

    Args:
        url: The HTTP(S) URL to fetch.
        timeout: Per-request timeout in seconds.
        retries: Number of retry attempts on failure.

    Returns:
        The response body decoded as text.

    Raises:
        Exception: The last encountered exception if all retries fail.
    """
    err: Optional[Exception] = None
    try:
        req = request.Request(url, headers={"User-Agent": USER_AGENT})
        with closing(request.urlopen(req, timeout=30.0)) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception as e:
        err = e
    assert err is not None
    raise err
