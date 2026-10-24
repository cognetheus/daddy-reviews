"""Incremental resolved-edge cache: conservative invalidation and safety."""
import json
from pathlib import Path

from daddy_reviews.graph import build_graph
from daddy_reviews.graph_cache import graph_with_cache


def _repo(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'lib.py').write_text('def f(): return 1\n')
    (root / 'service.py').write_text('from lib import f\n')
    (root / 'app.py').write_text('import service\n')
    (root / 'untouched.py').write_text('x = 2\n')
    return root, tmp_path / 'graph.json'


def test_single_file_edit_reparses_only_changed_module(tmp_path):
    root, cache = _repo(tmp_path)
    first, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 4
    (root / 'lib.py').write_text('def f(): return 2\n')
    graph, info = graph_with_cache(root, cache)
    assert info['status'] == 'stored'
    assert info['parsed_files'] == 1
    assert info['reused_files'] == 3
    assert graph == build_graph(root)
    assert first['nodes'] != graph['nodes']


def test_changed_import_updates_edges_while_reusing_others(tmp_path):
    root, cache = _repo(tmp_path)
    graph_with_cache(root, cache)
    (root / 'service.py').write_text('import app\n')
    graph, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 1
    assert info['reused_files'] == 3
    assert ('service.py', 'app.py') in {(e['source'], e['target']) for e in graph['edges']}
    assert ('service.py', 'lib.py') not in {(e['source'], e['target']) for e in graph['edges']}
    assert graph == build_graph(root)


def test_add_or_remove_module_forces_full_reresolution(tmp_path):
    root, cache = _repo(tmp_path)
    (root / 'service.py').write_text('import extra\n')
    graph_with_cache(root, cache)
    (root / 'extra.py').write_text('value = 1\n')
    added, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 5 and info['reused_files'] == 0
    assert any(e['source'] == 'service.py' and e['target'] == 'extra.py' for e in added['edges'])
    (root / 'extra.py').unlink()
    removed, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 4 and info['reused_files'] == 0
    assert not any(e['target'] == 'extra.py' for e in removed['edges'])
    assert removed == build_graph(root)


def test_alias_config_change_forces_full_reresolution(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'a.ts').write_text('export const a = 1\n')
    (root / 'b.ts').write_text('export const b = 2\n')
    (root / 'consumer.ts').write_text('import { a } from "@lib"\n')
    config = root / 'tsconfig.json'
    config.write_text(json.dumps({'compilerOptions': {'paths': {'@lib': ['./a']}}}))
    cache = tmp_path / 'graph.json'
    graph_with_cache(root, cache)
    config.write_text(json.dumps({'compilerOptions': {'paths': {'@lib': ['./b']}}}))
    graph, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 3 and info['reused_files'] == 0
    assert any(e['target'] == 'b.ts' for e in graph['edges'])
    assert not any(e['target'] == 'a.ts' for e in graph['edges'])
    assert graph == build_graph(root)


def test_js_edit_reuses_other_modules(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'model.ts').write_text('export const value = 1\n')
    (root / 'api.ts').write_text('import { value } from "./model"\n')
    cache = tmp_path / 'graph.json'
    graph_with_cache(root, cache)
    (root / 'model.ts').write_text('export const value = 2\n')
    graph, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 1 and info['reused_files'] == 1
    assert graph == build_graph(root)


def test_corrupted_cached_edge_abstains_and_rebuilds(tmp_path):
    root, cache = _repo(tmp_path)
    graph_with_cache(root, cache)
    payload = json.loads(cache.read_text())
    payload['graph']['edges'][0]['target'] = '../outside.py'
    cache.write_text(json.dumps(payload))
    (root / 'lib.py').write_text('def f(): return 2\n')
    graph, info = graph_with_cache(root, cache)
    assert info['parsed_files'] == 4 and info['reused_files'] == 0
    assert graph == build_graph(root)


def test_legacy_cache_rebuilds_without_trusting_old_format(tmp_path):
    root, cache = _repo(tmp_path)
    graph_with_cache(root, cache)
    payload = json.loads(cache.read_text())
    payload['format'] = 'daddy-reviews-graph-cache-v1'
    cache.write_text(json.dumps(payload))
    graph, info = graph_with_cache(root, cache)
    assert info['status'] == 'stored'
    assert info['parsed_files'] == 4
    assert graph == build_graph(root)


def test_cache_hit_reports_zero_parsed_files(tmp_path):
    root, cache = _repo(tmp_path)
    graph_with_cache(root, cache)
    graph, info = graph_with_cache(root, cache)
    assert info['status'] == 'hit'
    assert info['parsed_files'] == 0
    assert info['reused_files'] == 4
    assert graph == build_graph(root)
