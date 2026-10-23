"""Bounded, source-derived module graph for change impact and reuse discovery.

Edges are static import evidence, NOT proof of runtime invocation or business impact.
No repository code is executed and the graph is not a language-server replacement.
"""
from __future__ import annotations

import ast
from collections import deque
import hashlib
import os
from pathlib import Path
import re
from typing import Any

from .js_graph import EXTENSIONS, _mask_noncode, _resolve_module
from .inspect import EXCLUDE
from .tsconfig import TsconfigResolver

MAX_FILES = 4000
MAX_BYTES_PER_FILE = 350_000
MAX_TOTAL_BYTES = 24_000_000
PYTHON = '.py'
JS_IMPORT = re.compile(r'''(?m)^[ \t]*(?:import|export)[ \t]+(?:(?:[^;]{0,1500}?)\s+from\s+)?["']([^"'\n]+)["']''')
JS_REQUIRE = re.compile(r'''\b(require|import)\s*\(\s*["']([^"'\n]+)["']\s*\)''')


def _files(root: Path) -> tuple[list[Path], list[str]]:
    selected: list[Path] = []
    warnings: list[str] = []
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            file = Path(directory) / name
            if file.suffix not in (EXTENSIONS | {PYTHON}) or file.is_symlink():
                continue
            try:
                size = file.stat().st_size
            except OSError:
                continue
            if size > MAX_BYTES_PER_FILE:
                warnings.append(f'{file.relative_to(root).as_posix()}: too large to index')
                continue
            if len(selected) >= MAX_FILES or total + size > MAX_TOTAL_BYTES:
                warnings.append('Index budget exhausted; graph is incomplete')
                return selected, warnings
            selected.append(file)
            total += size
    return selected, warnings


def _python_names(relative: str) -> set[str]:
    parts = list(Path(relative).parts)
    if not parts or not parts[-1].endswith('.py'):
        return set()
    if parts[-1] == '__init__.py':
        parts.pop()
    else:
        parts[-1] = parts[-1][:-3]
    candidates = [parts]
    for i, part in enumerate(parts):
        if part == 'src' and i + 1 < len(parts):
            candidates.append(parts[i + 1:])
    return {'.'.join(seq) for seq in candidates if seq}


def _python_target(index: dict[str, set[str]], current: str, imported: str, level: int,
                   members: list[str], package_init: bool) -> str | None:
    if level:
        module = current.split('.') if current else []
        package = module if package_init else module[:-1]
        if level - 1 > len(package):
            return None
        base = package[:len(package) - (level - 1)]
        prefix = '.'.join(base + ([imported] if imported else []))
    else:
        prefix = imported
    possibilities = [prefix + '.' + member for member in members if member != '*'] + [prefix]
    for candidate in possibilities:
        match = index.get(candidate, set())
        if len(match) == 1:
            return next(iter(match))
    return None


def build_graph(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f'Not a directory: {root}')
    files, warnings = _files(root)
    pyindex: dict[str, set[str]] = {}
    for file in files:
        rel = file.relative_to(root).as_posix()
        if file.suffix == PYTHON:
            for alias in _python_names(rel):
                pyindex.setdefault(alias, set()).add(rel)
    tsresolver = TsconfigResolver(root, {file.relative_to(root).as_posix() for file in files if file.suffix in EXTENSIONS})
    nodes: list[dict] = []
    edges: list[dict] = []
    edge_keys: set[tuple] = set()

    def edge(source: str, target: str, kind: str, line: int) -> None:
        if source == target:
            return
        key = (source, target, kind, line)
        if key not in edge_keys:
            edge_keys.add(key)
            edges.append({'source': source, 'target': target, 'kind': kind, 'line': line,
                          'evidence': 'static_import_candidate'})

    for file in files:
        rel = file.relative_to(root).as_posix()
        try:
            source = file.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            warnings.append(f'{rel}: unreadable UTF-8 source')
            continue
        nodes.append({'path': rel, 'language': 'python' if file.suffix == PYTHON else 'javascript/typescript',
                      'sha256': hashlib.sha256(source.encode('utf-8')).hexdigest()})
        if file.suffix == PYTHON:
            try:
                tree = ast.parse(source)
            except SyntaxError:
                warnings.append(f'{rel}: invalid Python syntax, imports not indexed')
                continue
            current_names = _python_names(rel)
            module = sorted(current_names, key=lambda s: (len(s.split('.')), len(s)))[0] if current_names else ''
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        path = _python_target(pyindex, module, alias.name, 0, [], False)
                        if path:
                            edge(rel, path, 'python_import', node.lineno)
                elif isinstance(node, ast.ImportFrom):
                    # A from-import can name independently indexed submodules.
                    members = [alias.name for alias in node.names if alias.name != '*']
                    for member in members or ['*']:
                        target = _python_target(pyindex, module, node.module or '', node.level,
                                                [member] if member != '*' else [],
                                                rel.endswith('/__init__.py') or rel == '__init__.py')
                        if target:
                            edge(rel, target, 'python_from_import', node.lineno)
        elif file.suffix in EXTENSIONS:
            masked = _mask_noncode(source)
            for found in JS_IMPORT.finditer(source):
                location = found.start()
                if not re.match(r'\s*(?:import|export)\b', masked[location:location+16]):
                    continue
                specifier = found.group(1)
                relative = specifier.startswith(('./', '../'))
                target = _resolve_module(root, rel, specifier) if relative else tsresolver.resolve(rel, specifier)
                if target:
                    kind = 'js_static_import_or_export' if relative else 'js_tsconfig_alias_import_or_export'
                    edge(rel, target, kind, source.count('\n', 0, location) + 1)
            for found in JS_REQUIRE.finditer(source):
                location = found.start()
                if not re.match(r'(?:require|import)\s*\(', masked[location:location+20]):
                    continue
                specifier = found.group(2)
                relative = specifier.startswith(('./', '../'))
                target = _resolve_module(root, rel, specifier) if relative else tsresolver.resolve(rel, specifier)
                if target:
                    kind = 'js_literal_' + found.group(1) if relative else 'js_tsconfig_alias_literal_' + found.group(1)
                    edge(rel, target, kind, source.count('\n', 0, location) + 1)
    warnings.extend(tsresolver.warnings)
    return {'format': 'daddy-reviews-module-graph-v1', 'nodes': sorted(nodes, key=lambda n: n['path']),
            'edges': sorted(edges, key=lambda e: (e['source'], e['target'], e['line'], e['kind'])),
            'warnings': warnings, 'limitations': [
                'Imports are syntactic candidates; Python shadowing, TS config inheritance, package exports and runtime imports may be unresolved.',
                'Edges model source imports, not verified calls, actual side effects, runtime reachability or business impact.',
                'Python ambiguous module names are intentionally not resolved. Missing edges do not prove isolation.',
            ]}


def impact(graph: dict, changed: list[str], max_depth: int = 3, max_consumers: int = 100) -> dict:
    """Reverse dependency BFS, shortest path toward changed module; bounded/cycle safe."""
    max_depth = max(0, min(max_depth, 8))
    max_consumers = max(1, min(max_consumers, 500))
    known = {n['path'] for n in graph['nodes']}
    changed = sorted(set(changed))
    reverse: dict[str, set[str]] = {}
    for e in graph['edges']:
        reverse.setdefault(e['target'], set()).add(e['source'])
    visited: dict[str, tuple[int, list[str]]] = {}
    frontier = deque()
    for path in changed:
        if path in known:
            frontier.append((path, 0, [path]))
    while frontier:
        node, depth, chain = frontier.popleft()
        if depth >= max_depth:
            continue
        for source in sorted(reverse.get(node, set())):
            if source in changed or source in visited:
                continue
            new_path = [source] + chain
            visited[source] = (depth + 1, new_path)
            if len(visited) >= max_consumers:
                frontier.clear()
                break
            frontier.append((source, depth + 1, new_path))
    consumers = [{'path': p, 'distance': d, 'via': path, 'classification': 'static_reverse_import_candidate'}
                 for p, (d, path) in sorted(visited.items(), key=lambda i: (i[1][0], i[0]))]
    return {'changed': changed, 'unindexed_changed': sorted(set(changed) - known),
            'direct_consumers': [x for x in consumers if x['distance'] == 1],
            'transitive_consumers': [x for x in consumers if x['distance'] > 1],
            'max_depth': max_depth, 'truncated': len(visited) >= max_consumers or bool(graph.get('warnings')),
            'interpretation': 'Import-based impact hypothesis; not proof that the consumer calls or executes changed code.'}


def import_cycles(graph: dict, limit: int = 30) -> list[list[str]]:
    """Bounded iterative DFS for simple back-edge cycle candidates."""
    adjacent: dict[str, set[str]] = {}
    for item in graph['edges']:
        adjacent.setdefault(item['source'], set()).add(item['target'])
    seen: set[str] = set()
    active: list[str] = []
    positions: dict[str, int] = {}
    found: set[tuple[str, ...]] = set()
    for start in sorted(node['path'] for node in graph['nodes']):
        if start in seen or len(found) >= limit:
            continue
        seen.add(start)
        active.append(start)
        positions[start] = 0
        stack = [(start, iter(sorted(adjacent.get(start, set()))))]
        while stack:
            node, neighbors = stack[-1]
            nxt = next(neighbors, None)
            if nxt is None:
                stack.pop()
                active.pop()
                positions.pop(node, None)
                continue
            if nxt in positions:
                cycle = active[positions[nxt]:]
                offset = min(range(len(cycle)), key=lambda i: cycle[i])
                found.add(tuple(cycle[offset:] + cycle[:offset]))
                if len(found) >= limit:
                    break
            elif nxt not in seen:
                seen.add(nxt)
                positions[nxt] = len(active)
                active.append(nxt)
                stack.append((nxt, iter(sorted(adjacent.get(nxt, set())))))
    return [list(item) for item in sorted(found)[:limit]]
