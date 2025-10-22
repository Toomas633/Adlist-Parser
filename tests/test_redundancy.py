"""Tests for redundancy analysis utilities in adparser.redundancy."""

# pylint: disable=missing-function-docstring, protected-access
from asyncio import run, sleep
from typing import cast

from adparser import redundancy
from adparser.models import Source
from adparser.status import StatusSpinner


def test_abp_prefix_and_key_and_collect():
    entry = '||https://user@HOST:8080/path^$opt'
    entries = ['||example.com^', '@@||allowed.example^', 'plain']

    keys = redundancy._collect_remote_abp_domains(entries)

    assert redundancy._abp_prefix('@@||a') == '@@||'
    assert redundancy._abp_prefix('||b') == '||'
    assert redundancy._abp_prefix('plain') is None
    assert redundancy._abp_key(entry) == 'host'
    assert redundancy._abp_key('#@#||x') is None
    assert 'example.com' in keys and 'allowed.example' in keys


def test_remote_union_and_iter_local_entries_and_ancestors():
    s1 = {'a', 'b'}
    s2 = {'c'}
    sources = {'lab1': s1, 'lab2': s2}
    labels = {'lab1': Source('http://remote'), 'lab2': Source('file:///local')}
    per = {'lab1': set(), 'lab2': set()}

    union = redundancy._remote_union(sources, labels)
    res = list(redundancy._iter_local_entries(per, labels))

    assert union == s1
    assert res == [('lab2', set())]
    assert redundancy._ancestors('a.b.c') == ['a.b.c', 'b.c', 'c']


def test_entry_covered_by_remote_variants():
    remote = {'example.com', 'other.com'}

    assert redundancy._entry_covered_by_remote('||sub.example.com^', remote) is True
    assert redundancy._entry_covered_by_remote('||-bad-.com^', remote) is False
    assert redundancy._entry_covered_by_remote('x.y.example.com', remote) is True
    assert redundancy._entry_covered_by_remote('*.x.example.com', remote) is True


def test_covered_entries_and_compute_duplicates_and_build_sets():
    entry_set = {'a', 'b', 'c'}
    union_remote = {'b', 'z'}
    remote_abp = {'x'}
    covered = redundancy._covered_entries(entry_set, union_remote, remote_abp)
    assert 'b' in covered

    per_source = {'s1': {'a', 'b'}, 's2': {'a', 'b'}, 's3': {'c'}}
    groups = redundancy._compute_duplicates(per_source)
    assert any(set(g) == {'s1', 's2'} for g in groups)

    src_ok = Source('good.txt')
    src_fail = Source('bad.txt')
    fetch_results = [(src_ok, ['a']), (src_fail, ['b'])]
    failed = [src_fail]
    all_sources = [src_ok, src_fail]
    sets, label_map = redundancy._build_source_sets(fetch_results, failed, all_sources)
    assert 'good.txt' in sets and 'bad.txt' not in sets
    assert label_map['good.txt'].raw == 'good.txt'


def test_compute_local_file_redundancy_and_format_and_generate_messages():
    per_source_sets = {
        'r1': {'a', 'b', 'c'},
        'l1': {'b', 'd', 'e'},
    }
    label_to_source = {'r1': Source('http://remote'), 'l1': Source('localfile.txt')}

    local_cov = redundancy._compute_local_file_redundancy(
        per_source_sets, label_to_source
    )
    assert 'localfile.txt' in local_cov
    covered, total = local_cov['localfile.txt']
    assert 'b' in covered and total == 3

    assert redundancy._format_source_label('http://x').startswith('🌐')
    assert redundancy._format_source_label('file.txt').startswith('📄')

    msg = redundancy._generate_duplicate_sources([['s1', 's2']])
    assert any('Duplicate sources' in m for m in msg)

    many = {str(i) for i in range(30)}
    local_map = {'some.txt': (many, 100)}
    lm = redundancy._generate_local_file_redundancy(local_map)
    assert any('Entries that can be removed' in m for m in lm)
    assert any('... and' in m for m in lm)

    assert not redundancy._generate_duplicate_sources([])
    assert not redundancy._generate_local_file_redundancy({})


def test_exclude_and_is_excluded_helpers(tmp_path):
    abs_path = str(tmp_path / 'output' / 'adlist.txt')
    s2 = Source('other', resolved_path=abs_path)

    assert redundancy.is_excluded_src(
        Source(redundancy.ADLIST_OUTPUT), redundancy.ADLIST_OUTPUT, abs_path
    )
    assert redundancy.is_excluded_src(s2, redundancy.ADLIST_OUTPUT, abs_path)
    assert redundancy.is_excluded_label(
        redundancy.ADLIST_OUTPUT, redundancy.ADLIST_OUTPUT, abs_path
    )
    assert redundancy.is_excluded_label(
        Source(redundancy.ADLIST_OUTPUT), redundancy.ADLIST_OUTPUT, abs_path
    )


def test_generate_redundancy_report_async():
    class SpinnerStub:
        """Minimal stub with the same interface as StatusSpinner for tests."""

        def __init__(self):
            self.updated = None

        async def show_progress(self, message, operation):
            del message
            await sleep(0)
            return await operation

        def update_status(self, text):
            self.updated = text

    spinner: StatusSpinner = cast(StatusSpinner, SpinnerStub())
    res = run(redundancy.generate_redundancy_report([], [], [], spinner, 'Adlist'))

    assert not res
    assert getattr(spinner, 'updated', None) is not None
    updated_msg = getattr(spinner, 'updated', '') or ''
    assert 'No duplicates or local redundancies found' in updated_msg
