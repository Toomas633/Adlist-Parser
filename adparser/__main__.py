"""Module entrypoint to run the CLI with `python -m adparser`."""

from asyncio import run

from .cli import main

if __name__ == "__main__":
    raise SystemExit(run(main()))
