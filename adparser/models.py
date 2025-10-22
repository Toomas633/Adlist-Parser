"""Lightweight data models used by Adlist-Parser."""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class Source:
    """A single adlist source reference.

    Attributes:
        raw: The original source string (URL, file path, or file URI).
        resolved_path: Absolute file system path if resolved for local files.
    """

    raw: str
    resolved_path: Optional[str] = None

    def is_url(self) -> bool:
        """Return True if this source is an HTTP(S) URL.

        Note: file:// URIs are treated as local paths, not URLs to fetch over HTTP.
        """
        parsed = urlparse(self.raw)
        return parsed.scheme in {"http", "https"}

    def is_file_url(self) -> bool:
        """Return True if this source is a file:// URL."""
        parsed = urlparse(self.raw)
        return parsed.scheme == "file"


__all__ = ["Source"]
