"""Adlist-Parser package.

Public entrypoints:
- adparser.cli.main(): async CLI orchestrator

Submodules:
- constants: paths and filenames
- content: normalization and ABP/regex handling
- fetcher: concurrent fetching of sources
- io: JSON loading and file writing helpers
- models: simple data models (e.g., Source)
- redundancy: redundancy analysis
- reporting: final summary output
- status: spinners and grouped status display
"""

from .cli import main  # re-export for convenience

__all__ = ["main"]
