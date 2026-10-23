"""Opt-in, source-hash-validated persistent graph cache.

This is a whole-graph cache: unchanged trees avoid parsing, but any source or
configuration change triggers a complete rebuild. It is NOT incremental parsing.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from .graph import _files, build_graph
from .graph_delta import GraphSnapshotError, MAX_SNAPSHOT_BYTES, validate_snapshot
from .inspect import EXCLUDE
from .tsconfig import MAX_CONFIG_BYTES

FORMAT = 'daddy-reviews-graph-cache-v1'
MAX_CONFIG_FILES = 256
MAX_CONFIG_TOTAL_BYTES = 2_000_000


class GraphCacheError(ValueError):
    """Unsafe cache destination or an invalid cache configuration."""


def _cache_path(path: Path) -> Path:
    path = path.absolute()
    if path.name in ('tsconfig.json', 'jsconfig.json') or path.suffix != '.json':
        raise GraphCacheError('Cache destination must be a .json file other than tsconfig.json/jsconfig.json')
    if path.is_symlink():
        raise GraphCacheError('Cache destination must not be a symlink')
    if not path.parent.is_dir():
        raise GraphCacheError('Cache parent directory must already exist')
    return path


def _update(hasher: Any, path: str, contents: bytes) -> None:
    # Length-prefix the name and digest to prevent concatenation ambiguities.
    name = path.encode('utf-8')
    hasher.update(len(name).to_bytes(4, 'big'))
    hasher.update(name)
    hasher.update(hashlib.sha256(contents).digest())


def _fingerprint(root: Path) -> tuple[str | None, str | None]:
    """Hash indexed source and all relevant config paths/bytes, with scan budgets."""
    files, warnings = _files(root)
    if warnings:
        return None, 'Source scan incomplete: ' + '; '.join(warnings[:3])
    h = hashlib.sha256()
    h.update(FORMAT.encode('ascii') + b'\0')
    h.update(str(root).encode('utf-8') + b'\0')
    h.update(f'python-{sys.version_info.major}.{sys.version_info.minor}'.encode('ascii') + b'\0')
    try:
        for file in files:
            if file.is_symlink():
                return None, 'Source symlink appeared during indexing'
            _update(h, file.relative_to(root).as_posix(), file.read_bytes())
        config_count = 0
        config_bytes = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                if name not in ('tsconfig.json', 'jsconfig.json'):
                    continue
                config = Path(directory) / name
                if config.is_symlink():
                    return None, 'Config symlink prevents cache validation'
                size = config.stat().st_size
                config_count += 1
                config_bytes += size
                if config_count > MAX_CONFIG_FILES or size > MAX_CONFIG_BYTES or config_bytes > MAX_CONFIG_TOTAL_BYTES:
                    return None, 'Config scan budget exhausted'
                _update(h, config.relative_to(root).as_posix(), config.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        return None, 'Unable to fingerprint source/config: ' + str(exc)
    return h.hexdigest(), None


def _read(path: Path, fingerprint: str) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise GraphCacheError('Cache destination became a symlink')
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('format') != FORMAT:
            return None
        if payload.get('fingerprint') != fingerprint:
            return None
        graph = validate_snapshot(payload.get('graph'))
        if graph['warnings']:
            return None
        original = payload['graph']
        limitations = original.get('limitations', [])
        if (not isinstance(limitations, list) or len(limitations) > 30
                or any(not isinstance(item, str) or len(item) > 2000 for item in limitations)):
            return None
        graph['limitations'] = limitations
        return graph
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError,
            GraphSnapshotError, TypeError, ValueError):
        return None


def _write(path: Path, fingerprint: str, graph: dict) -> None:
    """Atomic replacement; no project source is executed and no cache is trusted."""
    payload = {'format': FORMAT, 'fingerprint': fingerprint, 'graph': graph}
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.daddy-graph-', suffix='.tmp', delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(payload, stream, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise GraphCacheError('Cache destination became a symlink')
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def graph_with_cache(root: Path, cache_file: Path) -> tuple[dict, dict]:
    """Return graph plus transparent cache metadata; never silently trust stale data."""
    root = root.resolve()
    cache = _cache_path(cache_file)
    fingerprint, reason = _fingerprint(root)
    if fingerprint is None:
        return build_graph(root), {'status': 'bypassed', 'reason': reason}
    cached = _read(cache, fingerprint)
    if cached is not None:
        return cached, {'status': 'hit', 'fingerprint': fingerprint}
    graph = build_graph(root)
    if graph['warnings']:
        return graph, {'status': 'bypassed', 'reason': 'Graph warnings prevent caching'}
    # Do not persist a graph if the tree changed while it was being indexed.
    after, reason = _fingerprint(root)
    if after is None or after != fingerprint:
        return graph, {'status': 'volatile', 'reason': reason or 'Repository changed during graph build'}
    try:
        _write(cache, fingerprint, graph)
    except (OSError, GraphCacheError) as exc:
        return graph, {'status': 'write_failed', 'reason': str(exc)}
    return graph, {'status': 'stored', 'fingerprint': fingerprint}
