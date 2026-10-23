"""Conservative changed-symbol / possible-consumer discovery.

Symbol references are *candidates* and are not proof of runtime invocation.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
from .diff import FileDiff
from .inspect import walk


@dataclass(frozen=True)
class ChangedSymbol:
    name: str
    kind: str
    path: str
    line: int
    end_line: int


def safe_source(root: Path, relative: str) -> Path | None:
    if not relative or relative.startswith('-'):
        return None
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return None
    return target


def changed_python_symbols(root: Path, changes: list[FileDiff]) -> list[ChangedSymbol]:
    symbols: dict[tuple[str, int, str], ChangedSymbol] = {}
    for change in changes:
        if not change.new_path.endswith('.py') or not change.added_lines:
            continue
        path = safe_source(root, change.new_path)
        if path is None:
            continue
        try:
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError):
            continue
        changed = set(change.added_lines)
        candidates=[]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = node.end_lineno or node.lineno
                if any(node.lineno <= n <= end for n in changed):
                    candidates.append((end - node.lineno, ChangedSymbol(node.name, type(node).__name__, change.new_path, node.lineno, end)))
        # Include matched specific functions/classes; the owning class may be useful too.
        for _, sym in sorted(candidates, key=lambda s: s[0]):
            symbols[(sym.path, sym.line, sym.name)] = sym
    return list(symbols.values())


def possible_consumers(root: Path, symbols: list[ChangedSymbol], limit: int = 40) -> list[dict]:
    """Find bounded textual references; not a sound call graph or semantic match."""
    result=[]
    for sym in symbols:
        if len(sym.name) < 4 or sym.name.startswith('_') or len(result) >= limit:
            continue
        pattern = re.compile(r'\b' + re.escape(sym.name) + r'\b')
        for path in walk(root):
            relative = path.relative_to(root).as_posix()
            if relative == sym.path:
                continue
            try:
                for idx, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    if pattern.search(line):
                        result.append({'symbol':sym.name,'defined_in':sym.path,'path':relative,
                                       'line':idx,'evidence':line.strip()[:200],
                                       'classification':'textual_reference_candidate'})
                        if len(result) >= limit:
                            return result
            except (OSError,UnicodeError):
                continue
    return result


def test_candidates(root: Path, changes: list[FileDiff]) -> list[str]:
    """Find available matching test paths as hints, not assertions of coverage."""
    names={Path(c.new_path).stem.lower().removeprefix('test_') for c in changes if c.new_path}
    results=[]
    for p in root.rglob('*'):
        if not p.is_file() or any(x in {'.git', '.venv','node_modules','dist','build'} for x in p.relative_to(root).parts):
            continue
        rel=p.relative_to(root).as_posix()
        if not re.search(r'(test|spec)', rel, re.IGNORECASE):
            continue
        if p.suffix.lower() not in {'.py','.js','.jsx','.ts','.tsx','.cs','.java'}:
            continue
        if any(n and n in p.stem.lower() for n in names):
            results.append(rel)
    return sorted(results)[:50]


def exact_python_body_candidates(root: Path, changed: list[ChangedSymbol], limit: int = 25) -> list[dict]:
    """AST structural equality candidates, not proof of redundant domain behavior."""
    changed_keys={(x.path,x.name) for x in changed if x.kind in {'FunctionDef','AsyncFunctionDef'}}
    if not changed_keys:
        return []
    hashes: dict[str,list[tuple[str,str,int]]] = {}
    import hashlib
    for p in walk(root):
        if p.suffix != '.py':
            continue
        try:
            tree=ast.parse(p.read_text(encoding='utf-8'))
        except (SyntaxError,UnicodeError,OSError):
            continue
        rel=p.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and len(node.body)>1 and (node.end_lineno or 0)-node.lineno>=4:
                serialized=ast.dump(ast.Module(body=node.body,type_ignores=[]),include_attributes=False)
                digest=hashlib.sha256(serialized.encode()).hexdigest()
                hashes.setdefault(digest,[]).append((rel,node.name,node.lineno))
    result=[]
    for group in hashes.values():
        if len(group)<2 or not any((p,n) in changed_keys for p,n,_ in group):
            continue
        result.append({'match_type':'identical_function_body_ast','locations':[
            {'path':p,'name':n,'line':line} for p,n,line in group],
            'interpretation':'Reuse candidate only; domain semantics and ownership require review.'})
        if len(result)>=limit:
            break
    return result
