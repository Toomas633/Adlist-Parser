"""Tests for adparser.io and adparser.fetcher modules."""

# pylint: disable=missing-function-docstring
from json import dumps
from pathlib import Path

from adparser import io
from adparser.fetcher import fetch
from adparser.models import Source


def test_load_sources_various_json_shapes(tmp_path: Path):
    p_list = tmp_path / "lists.json"
    p_list.write_text(
        dumps(
            [
                str(tmp_path / "a.txt"),
                "https://example.com/list.txt",
                "file:///C:/Windows/hosts",
            ]
        ),
        encoding="utf-8",
    )

    sources = io.load_sources(str(p_list))

    assert len(sources) == 3
    assert sources[0].resolved_path and Path(sources[0].resolved_path).is_absolute()
    assert sources[1].resolved_path is None
    assert sources[2].resolved_path is None

    p_dict = tmp_path / "dict.json"
    p_dict.write_text(
        dumps(
            {
                "lists": ["a.txt"],
                "urls": ["https://a"],
                "adlists": ["b.txt"],
                "sources": ["https://b"],
            }
        ),
        encoding="utf-8",
    )
    sources2 = io.load_sources(str(p_dict))
    raw_set = {s.raw for s in sources2}

    assert {"a.txt", "https://a", "b.txt", "https://b"} <= raw_set

    locals_resolved = [s for s in sources2 if s.resolved_path]
    for s in locals_resolved:
        assert s.resolved_path is not None
        assert Path(s.resolved_path).is_absolute()


def test_fetcher_reads_local_file(tmp_path: Path):
    p = tmp_path / "sample.txt"
    p.write_text("one\n# comment\ntwo\n", encoding="utf-8")

    src = Source(raw=str(p), resolved_path=str(p))

    progress_updates = []

    def cb(done, total):
        progress_updates.append((done, total))

    results, failed = fetch([src], progress_callback=cb)

    assert not failed
    assert len(results) == 1
    (returned_src, lines) = results[0]
    assert returned_src.raw == src.raw
    assert lines == ["one", "# comment", "two"]
    assert progress_updates[-1][0] == 1 and progress_updates[-1][1] == 1
