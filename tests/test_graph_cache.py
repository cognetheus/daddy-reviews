import json
from pathlib import Path

import pytest

from daddy_reviews.graph_cache import GraphCacheError, graph_with_cache


def _fixture(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'core.py').write_text('value = 1\n')
    (root / 'api.py').write_text('import core\n')
    return root, tmp_path / 'graph-cache.json'


def test_cache_hit_avoids_reparsing(tmp_path, monkeypatch):
    root, cache = _fixture(tmp_path)
    first, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert cache.exists()
    import daddy_reviews.graph_cache as module
    def unexpected(_root):
        raise AssertionError('build_graph must not run on a cache hit')
    monkeypatch.setattr(module, 'build_graph', unexpected)
    second, status = graph_with_cache(root, cache)
    assert status['status'] == 'hit'
    assert first == second


def test_mutation_addition_deletion_invalidate(tmp_path):
    root, cache = _fixture(tmp_path)
    graph_with_cache(root, cache)
    (root / 'core.py').write_text('value = 2\n')
    updated, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert updated['nodes'][1]['path'] == 'core.py'
    (root / 'extra.py').write_text('import core\n')
    added, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert len(added['nodes']) == 3
    (root / 'extra.py').unlink()
    removed, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert len(removed['nodes']) == 2


def test_alias_config_change_invalidates_without_source_change(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'a.ts').write_text('export const a = 1\n')
    (root / 'b.ts').write_text('export const b = 2\n')
    (root / 'consumer.ts').write_text('import { a } from "@lib"\n')
    config = root / 'tsconfig.json'
    config.write_text(json.dumps({'compilerOptions': {'paths': {'@lib': ['./a']}}}))
    cache = tmp_path / 'cache.json'
    before, _ = graph_with_cache(root, cache)
    assert any(e['target'] == 'a.ts' for e in before['edges'])
    config.write_text(json.dumps({'compilerOptions': {'paths': {'@lib': ['./b']}}}))
    after, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert any(e['target'] == 'b.ts' for e in after['edges'])
    assert not any(e['target'] == 'a.ts' for e in after['edges'])


def test_invalid_cache_and_malicious_snapshot_rebuild(tmp_path):
    root, cache = _fixture(tmp_path)
    graph_with_cache(root, cache)
    cache.write_text('{broken')
    graph, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'
    assert graph['nodes']
    payload = json.loads(cache.read_text())
    payload['graph']['nodes'][0]['path'] = '../escape.py'
    cache.write_text(json.dumps(payload))
    _, status = graph_with_cache(root, cache)
    assert status['status'] == 'stored'


def test_symlink_cache_is_rejected_without_overwriting_target(tmp_path):
    root, cache = _fixture(tmp_path)
    target = tmp_path / 'valuable.json'
    target.write_text('do not overwrite')
    cache.symlink_to(target)
    with pytest.raises(GraphCacheError, match='symlink'):
        graph_with_cache(root, cache)
    assert target.read_text() == 'do not overwrite'


def test_cache_path_cannot_replace_tsconfig_or_source(tmp_path):
    root, _ = _fixture(tmp_path)
    with pytest.raises(GraphCacheError):
        graph_with_cache(root, root / 'tsconfig.json')
    with pytest.raises(GraphCacheError):
        graph_with_cache(root, root / 'api.py')


def test_budget_warnings_bypass_cache(tmp_path, monkeypatch):
    root, cache = _fixture(tmp_path)
    import daddy_reviews.graph as graph_module
    monkeypatch.setattr(graph_module, 'MAX_FILES', 1)
    # graph_cache imported _files by reference; _files uses graph module budgets.
    _, status = graph_with_cache(root, cache)
    assert status['status'] == 'bypassed'
    assert not cache.exists()


def test_changed_during_scan_does_not_persist(tmp_path, monkeypatch):
    root, cache = _fixture(tmp_path)
    import daddy_reviews.graph_cache as module
    real = module._fingerprint
    calls = [0]
    def unstable(r):
        calls[0] += 1
        value, reason = real(r)
        if calls[0] == 2:
            return '0' * 64, None
        return value, reason
    monkeypatch.setattr(module, '_fingerprint', unstable)
    _, status = graph_with_cache(root, cache)
    assert status['status'] == 'volatile'
    assert not cache.exists()


def test_cache_bound_to_repository_path(tmp_path):
    first, cache = _fixture(tmp_path)
    graph_with_cache(first, cache)
    second = tmp_path / 'another'
    second.mkdir()
    for name in ('core.py', 'api.py'):
        (second / name).write_bytes((first / name).read_bytes())
    _, status = graph_with_cache(second, cache)
    assert status['status'] == 'stored'


def test_cache_cli_and_snapshot_envelope(tmp_path, capsys):
    from daddy_reviews.cli import main
    root, cache = _fixture(tmp_path)
    main(['graph', '--root', str(root), '--cache-file', str(cache), '--changed', 'core.py'])
    first = json.loads(capsys.readouterr().out)
    assert first['cache']['status'] == 'stored'
    assert first['impact']['direct_consumers'][0]['path'] == 'api.py'
    main(['graph', '--root', str(root), '--cache-file', str(cache)])
    second = json.loads(capsys.readouterr().out)
    assert second['cache']['status'] == 'hit'
    main(['capabilities', '--root', str(root), '--cache-file', str(cache), '--query', 'core'])
    result = json.loads(capsys.readouterr().out)
    assert result['cache']['status'] == 'hit'
