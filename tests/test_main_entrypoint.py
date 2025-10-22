"""Tests for package import and __main__ entrypoint behavior."""

# pylint: disable=missing-function-docstring
from asyncio import sleep
from runpy import run_module
from sys import modules
from types import ModuleType

from pytest import raises


def _with_fake_cli(return_code=0):
    """Context manager to inject a fake adparser.cli with async main() returning return_code."""

    class _Ctx:
        def __init__(self, code):
            self.code = code
            self._orig = None

        def __enter__(self):
            self._orig = modules.get("adparser.cli")
            fake_cli = ModuleType("adparser.cli")

            async def main():
                await sleep(0)
                return self.code

            setattr(fake_cli, "main", main)
            modules["adparser.cli"] = fake_cli

        def __exit__(self, exc_type, exc, tb):
            if self._orig is not None:
                modules["adparser.cli"] = self._orig
            else:
                modules.pop("adparser.cli", None)
            return False

    return _Ctx(return_code)


def _run_module_and_capture():
    """Run the package as a module (like `python -m adparser`) and capture SystemExit."""
    with raises(SystemExit) as excinfo:
        run_module("adparser", run_name="__main__")
    return excinfo.value


def test_package_entrypoint_exits_with_cli_code_zero():
    with _with_fake_cli(return_code=0):
        exit_exc = _run_module_and_capture()
    assert exit_exc.code == 0


def test_package_entrypoint_propagates_nonzero_exit_code():
    with _with_fake_cli(return_code=2):
        exit_exc = _run_module_and_capture()
    assert exit_exc.code == 2
