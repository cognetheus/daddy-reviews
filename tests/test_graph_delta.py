import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from daddy_reviews.graph import build_graph
from daddy_reviews.graph_delta import (
    GraphSnapshotError, compare_snapshots, read_snapshot, validate_snapshot,
)


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _graph(nodes, edges=(), warnings=()):
    return {
        'format': 'daddy-reviews-module-graph-v1',
        'nodes': [{'path': p, 'language': 'python', 'sha256': _hash(content)}
                  for p, content in nodes.items()],
        'edges': [{'source': source, 'target': target, 'kind': 'python_import',
                   'line': line, 'evidence': 'static_import_candidate'}
                  for source, target, line in edges],
        'warnings': list(warnings),
    }


def test_source_hash_change_and_transitive_impact():
    old = _graph({'api.py': 'import service', 'service.py': 'import core', 'core.py': 'v1'},
                 [('api.py', 'service.py', 1), ('service.py', 'core.py', 1)])
    new = _graph({'api.py': 'import service', 'service.py': 'import core', 'core.py': 'v2'},
                 [('api.py', 'service.py', 1), ('service.py', 'core.py', 1)])
    report = compare_snapshots(old, new)
    assert report['node_changes']['counts'] == {'added': 0, 'removed': 0, 'modified': 1}
    assert report['node_changes']['modified'][0]['path'] == 'core.py'
    assert report['edge_changes']['counts'] == {'added': 0, 'removed': 0}
    assert [x['path'] for x in report['reverse_impact']['after']['direct_consumers']] == ['service.py']
    assert [x['path'] for x in report['reverse_impact']['after']['transitive_consumers']] == ['api.py']
    assert report['reverse_impact']['new_candidate_consumers'] == []
    assert not report['truncated']


def test_import_edges_change_without_source_hash_change():
    old = _graph({'api.py': 'import alias', 'first.py': 'v', 'second.py': 'v'},
                 [('api.py', 'first.py', 3)])
    new = _graph({'api.py': 'import alias', 'first.py': 'v', 'second.py': 'v'},
                 [('api.py', 'second.py', 8)])
    report = compare_snapshots(old, new)
    assert report['node_changes']['counts']['modified'] == 0
    assert report['edge_changes']['counts'] == {'added': 1, 'removed': 1}
    assert {'first.py', 'second.py'} <= set(report['reverse_impact']['changed_or_affected_modules'])


def test_line_only_shifts_and_order_are_not_edge_changes():
    nodes = {'a.py': 'import b', 'b.py': 'pass'}
    before = _graph(nodes, [('a.py', 'b.py', 1)])
    after = _graph(nodes, [('a.py', 'b.py', 25)])
    after['nodes'].reverse()
    assert compare_snapshots(before, after)['edge_changes']['counts'] == {'added': 0, 'removed': 0}


def test_removed_module_keeps_before_reverse_impact():
    before = _graph({'consumer.py': 'import gone', 'gone.py': 'pass'},
                    [('consumer.py', 'gone.py', 1)])
    after = _graph({'consumer.py': 'import gone'})
    report = compare_snapshots(before, after)
    assert report['node_changes']['removed'] == ['gone.py']
    assert report['reverse_impact']['before']['direct_consumers'][0]['path'] == 'consumer.py'
    assert report['reverse_impact']['no_longer_candidate_consumers'] == ['consumer.py']


@pytest.mark.parametrize('mutator', [
    lambda graph: graph['nodes'].append(dict(graph['nodes'][0])),
    lambda graph: graph['nodes'][0].update(path='../secret.py'),
    lambda graph: graph['nodes'][0].update(sha256='not-a-sha'),
    lambda graph: graph['edges'].append({'source': 'a.py', 'target': 'missing.py',
                                        'kind': 'python_import', 'line': 1}),
    lambda graph: graph['edges'].append({'source': 'a.py', 'target': 'a.py',
                                        'kind': 'python_import', 'line': True}),
])
def test_rejects_malformed_snapshot(mutator):
    graph = _graph({'a.py': 'pass'})
    mutator(graph)
    with pytest.raises(GraphSnapshotError):
        validate_snapshot(graph)


def test_read_wrapped_cli_snapshot_and_invalid_json():
    with TemporaryDirectory() as td:
        path = Path(td) / 'graph.json'
        graph = _graph({'a.py': 'pass'})
        path.write_text(json.dumps({'graph': graph, 'impact': None}))
        assert read_snapshot(path)['nodes'][0]['path'] == 'a.py'
        path.write_text('{no')
        with pytest.raises(GraphSnapshotError):
            read_snapshot(path)


def test_read_rejects_symlink_and_budget(monkeypatch):
    import daddy_reviews.graph_delta as module
    with TemporaryDirectory() as td:
        root = Path(td)
        target = root / 'source.json'
        target.write_text(json.dumps(_graph({'a.py': 'pass'})))
        link = root / 'link.json'
        link.symlink_to(target)
        with pytest.raises(GraphSnapshotError):
            read_snapshot(link)
        monkeypatch.setattr(module, 'MAX_SNAPSHOT_BYTES', 3)
        with pytest.raises(GraphSnapshotError):
            read_snapshot(target)


def test_detail_limits_and_graph_warnings_explicit():
    before = _graph({'a.py': 'old', 'b.py': 'old'})
    after = _graph({'a.py': 'new', 'b.py': 'new'}, warnings=['index budget reached'])
    report = compare_snapshots(before, after, max_details=1)
    assert report['node_changes']['counts']['modified'] == 2
    assert len(report['node_changes']['modified']) == 1
    assert report['truncated']
    assert any('index warnings' in x for x in report['warnings'])


def test_graph_snapshot_roundtrip_real_python_imports():
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / 'a.py').write_text('import b\n')
        (root / 'b.py').write_text('pass\n')
        before = build_graph(root)
        (root / 'b.py').write_text('value = 42\n')
        after = build_graph(root)
        result = compare_snapshots(before, after)
        assert result['node_changes']['modified'][0]['path'] == 'b.py'
        assert result['reverse_impact']['after']['direct_consumers'][0]['path'] == 'a.py'


def test_python_from_import_multiple_submodules_have_separate_edges():
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / 'pkg').mkdir()
        (root / 'pkg/__init__.py').write_text('')
        (root / 'pkg/a.py').write_text('value = 1\n')
        (root / 'pkg/b.py').write_text('value = 2\n')
        (root / 'consumer.py').write_text('from pkg import a, b\n')
        graph = build_graph(root)
        pairs = {(e['source'], e['target']) for e in graph['edges']}
        assert ('consumer.py', 'pkg/a.py') in pairs
        assert ('consumer.py', 'pkg/b.py') in pairs
