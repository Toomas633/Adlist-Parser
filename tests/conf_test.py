"""Pylint configuration sanity tests.

These tests verify that test discovery and environment wiring behave as expected.
"""

# pylint: disable=missing-function-docstring
from pathlib import Path
from sys import path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in path:
    path.insert(0, str(ROOT))
