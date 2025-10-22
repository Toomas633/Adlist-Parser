"""Lightweight data models for Adlist-Parser."""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class Source:
    """Adlist source reference.

    Attributes:
        raw: Original string (URL, local path, or file URI).
        resolved_path: Absolute filesystem path for local files, if resolved.
    """

    raw: str
    resolved_path: Optional[str] = None

    def is_url(self) -> bool:
        """Return True if this source is an HTTP(S) URL.

        file:// URIs are treated as local paths.
        """
        parsed = urlparse(self.raw)
        return parsed.scheme in {"http", "https"}

    def is_file_url(self) -> bool:
        """Return True if this source is a file:// URL."""
        parsed = urlparse(self.raw)
        return parsed.scheme == "file"


__all__ = ["Source"]
