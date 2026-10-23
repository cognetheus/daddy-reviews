"""Read-only, bounded comparison of two independently captured module graph snapshots.

A graph delta is source-index evidence, not a verified runtime change or a Git diff.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .graph import impact

MAX_SNAPSHOT_BYTES = 32_000_000
MAX_NODES = 4_000
MAX_EDGES = 120_000
MAX_WARNINGS = 1_000
MAX_DETAILS = 200
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


class GraphSnapshotError(ValueError):
    """An invalid, unsupported or oversized graph snapshot."""


def _valid_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if '\\' in value or '\0' in value or value.startswith('/'):
        return False
    parts = value.split('/')
    return (all(part not in ('', '.', '..') for part in parts)
            and PurePosixPath(value).as_posix() == value)


def validate_snapshot(payload: Any) -> dict:
    """Validate an exported graph or the JSON envelope produced by graph CLI."""
    if isinstance(payload, dict) and 'graph' in payload:
        payload = payload['graph']
    if not isinstance(payload, dict) or payload.get('format') != 'daddy-reviews-module-graph-v1':
        raise GraphSnapshotError('Expected daddy-reviews-module-graph-v1 graph or graph CLI envelope')
    nodes = payload.get('nodes')
    edges = payload.get('edges')
    warnings = payload.get('warnings', [])
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise GraphSnapshotError('Invalid or oversized graph nodes')
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        raise GraphSnapshotError('Invalid or oversized graph edges')
    if (not isinstance(warnings, list) or len(warnings) > MAX_WARNINGS or
            any(not isinstance(w, str) or len(w) > 2000 for w in warnings)):
        raise GraphSnapshotError('Invalid graph warnings')
    seen_nodes: set[str] = set()
    clean_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphSnapshotError('Invalid graph node')
        path = node.get('path')
        sha = node.get('sha256')
        if (not _valid_path(path) or path in seen_nodes or
                not isinstance(sha, str) or not SHA256.fullmatch(sha) or
                node.get('language') not in ('python', 'javascript/typescript')):
            raise GraphSnapshotError('Invalid, duplicate or unsafe graph node')
        seen_nodes.add(path)
        clean_nodes.append({'path': path, 'sha256': sha, 'language': node['language']})
    seen_edges: set[tuple[str, str, str, int]] = set()
    clean_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            raise GraphSnapshotError('Invalid graph edge')
        source = edge.get('source')
        target = edge.get('target')
        kind = edge.get('kind')
        line = edge.get('line')
        if (not isinstance(source, str) or not isinstance(target, str) or
                source not in seen_nodes or target not in seen_nodes or
                not isinstance(kind, str) or not kind or len(kind) > 128 or
                not isinstance(line, int) or isinstance(line, bool) or not 0 < line <= 10_000_000):
            raise GraphSnapshotError('Invalid edge, line or missing endpoint')
        key = (source, target, kind, line)
        if key in seen_edges:
            raise GraphSnapshotError('Duplicate graph edge')
        seen_edges.add(key)
        clean_edges.append({'source': source, 'target': target, 'kind': kind, 'line': line,
                            'evidence': 'static_import_candidate'})
    return {'format': payload['format'], 'nodes': clean_nodes, 'edges': clean_edges,
            'warnings': warnings}


def read_snapshot(path: Path) -> dict:
    """Read JSON only, without executing repository code or following symlink snapshots."""
    try:
        if path.is_symlink():
            raise GraphSnapshotError('Snapshot symlinks are not accepted')
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise GraphSnapshotError('Graph snapshot exceeds size budget')
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GraphSnapshotError(f'Cannot read graph snapshot: {exc}') from exc
    return validate_snapshot(payload)


def _edge_index(graph: dict) -> dict[tuple[str, str, str], dict]:
    """Collapse repeated same-module import edges; line-only shifts are not semantic changes."""
    indexed = {}
    for edge in graph['edges']:
        key = (edge['source'], edge['target'], edge['kind'])
        if key not in indexed or edge['line'] < indexed[key]['line']:
            indexed[key] = edge
    return indexed


def _consumers(report: dict) -> set[str]:
    return {item['path'] for item in report['direct_consumers'] + report['transitive_consumers']}


def compare_snapshots(before: dict, after: dict, max_depth: int = 3,
                      max_details: int = 100) -> dict:
    """Compare hashes/import identities and trace bounded reverse import candidates."""
    old = validate_snapshot(before)
    new = validate_snapshot(after)
    max_details = max(1, min(max_details, MAX_DETAILS))
    old_nodes = {item['path']: item for item in old['nodes']}
    new_nodes = {item['path']: item for item in new['nodes']}
    added = sorted(new_nodes.keys() - old_nodes.keys())
    removed = sorted(old_nodes.keys() - new_nodes.keys())
    modified = sorted(p for p in old_nodes.keys() & new_nodes.keys()
                      if old_nodes[p]['sha256'] != new_nodes[p]['sha256']
                      or old_nodes[p]['language'] != new_nodes[p]['language'])
    old_edges = _edge_index(old)
    new_edges = _edge_index(new)
    added_edges = sorted(new_edges.keys() - old_edges.keys())
    removed_edges = sorted(old_edges.keys() - new_edges.keys())
    # Config changes may change import edges even when source hashes are identical.
    affected = sorted(set(added + removed + modified)
                      | {edge[1] for edge in added_edges + removed_edges})
    old_impact = impact(old, [p for p in affected if p in old_nodes], max_depth=max_depth)
    new_impact = impact(new, [p for p in affected if p in new_nodes], max_depth=max_depth)
    old_consumers = _consumers(old_impact)
    new_consumers = _consumers(new_impact)
    warnings = []
    if old['warnings']:
        warnings.append('Before snapshot has index warnings; comparison may be incomplete.')
    if new['warnings']:
        warnings.append('After snapshot has index warnings; comparison may be incomplete.')
    if len(added) > max_details or len(removed) > max_details or len(modified) > max_details:
        warnings.append('Node-change detail limit reached.')
    if len(added_edges) > max_details or len(removed_edges) > max_details:
        warnings.append('Edge-change detail limit reached.')
    if old_impact['truncated'] or new_impact['truncated']:
        warnings.append('Reverse impact is bounded or index warnings were present.')
    return {
        'format': 'daddy-reviews-module-graph-delta-v1',
        'node_changes': {
            'counts': {'added': len(added), 'removed': len(removed), 'modified': len(modified)},
            'added': added[:max_details], 'removed': removed[:max_details],
            'modified': [{'path': p, 'before_sha256': old_nodes[p]['sha256'],
                          'after_sha256': new_nodes[p]['sha256']} for p in modified[:max_details]],
        },
        'edge_changes': {
            'counts': {'added': len(added_edges), 'removed': len(removed_edges)},
            'added': [new_edges[key] for key in added_edges[:max_details]],
            'removed': [old_edges[key] for key in removed_edges[:max_details]],
            'identity': 'source, target and kind (line-only movement is ignored)',
        },
        'reverse_impact': {
            'changed_or_affected_modules': affected[:max_details],
            'affected_modules_count': len(affected),
            'before': old_impact, 'after': new_impact,
            'new_candidate_consumers': sorted(new_consumers - old_consumers)[:max_details],
            'no_longer_candidate_consumers': sorted(old_consumers - new_consumers)[:max_details],
        },
        'warnings': warnings,
        'truncated': bool(warnings) or len(affected) > max_details
                     or len(new_consumers - old_consumers) > max_details
                     or len(old_consumers - new_consumers) > max_details,
        'limitations': [
            'Graph snapshots are not authenticated to Git revisions; verify provenance independently.',
            'Source SHA-256 changes and static import edge deltas do not prove runtime behavior or defects.',
            'Missing imports, generated files, config inheritance, and build-dependent resolution may be unindexed.',
            'Changed tsconfig/jsconfig content is not itself a graph node; changed alias edges are candidates only.',
            'The before/after consumer comparison is bounded and may omit deeper or unresolved paths.',
        ],
    }
