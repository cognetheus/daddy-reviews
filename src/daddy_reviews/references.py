"""Conservative Python AST import and direct-call linkage.

These links are syntax-derived candidates, not a full symbol resolver: local
shadowing, runtime monkey-patching, dynamic imports, and re-exports are not
modeled. They are stronger evidence than unrestricted textual matches.
"""
from __future__ import annotations

import ast
from pathlib import PurePosixPath, Path
from .impact import ChangedSymbol
from .inspect import walk


def module_of(relative_path: str) -> str:
    parts = list(PurePosixPath(relative_path).parts)
    if not parts or not parts[-1].endswith('.py'):
        return ''
    if parts[0] == 'src':
        parts.pop(0)
    if parts[-1] == '__init__.py':
        parts.pop()
    else:
        parts[-1] = parts[-1][:-3]
    return '.'.join(parts)


def _target_module(node: ast.ImportFrom, current_module: str, is_package_init: bool) -> str:
    if not node.level:
        return node.module or ''
    own = current_module.split('.') if current_module else []
    package = own if is_package_init else own[:-1]
    climbs = node.level - 1
    if climbs > len(package):
        return ''
    base = package[:len(package) - climbs]
    return '.'.join(base + (node.module.split('.') if node.module else []))


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return parent + '.' + node.attr if parent else ''
    return ''


def import_call_candidates(root: Path, changed_symbols: list[ChangedSymbol], limit: int = 60) -> list[dict]:
    """Discover calls whose syntactic imports point at changed Python definitions."""
    targets: dict[tuple[str, str], ChangedSymbol] = {
        (module_of(s.path), s.name): s for s in changed_symbols
        if s.kind in {'FunctionDef', 'AsyncFunctionDef', 'ClassDef'} and module_of(s.path)
    }
    if not targets:
        return []
    output: list[dict] = []
    seen: set[tuple[str, int, str, str]] = set()
    for path in walk(root):
        if path.suffix != '.py':
            continue
        relative = path.relative_to(root).as_posix()
        current_module = module_of(relative)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
        except (OSError, UnicodeError, SyntaxError):
            continue
        imported: dict[str, tuple[str, str]] = {}
        imported_modules: dict[str, str] = {}
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.ImportFrom):
                mod = _target_module(stmt, current_module, relative.endswith('/__init__.py'))
                for alias in stmt.names:
                    if alias.name != '*':
                        imported[alias.asname or alias.name] = (mod, alias.name)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    local = alias.asname or alias.name.split('.')[0]
                    imported_modules[local] = alias.name if alias.asname else alias.name.split('.')[0]
        for stmt in ast.walk(tree):
            if not isinstance(stmt, ast.Call):
                continue
            expression = _dotted(stmt.func)
            if not expression:
                continue
            target = imported.get(expression)
            if not target and '.' in expression:
                prefix, member = expression.rsplit('.', 1)
                head, dot, suffix = prefix.partition('.')
                module = imported_modules.get(head)
                if module:
                    target = (module + ('.' + suffix if dot else ''), member)
            if target not in targets:
                continue
            sym = targets[target]
            if relative == sym.path:
                continue
            key = (relative, stmt.lineno, sym.path, sym.name)
            if key in seen:
                continue
            seen.add(key)
            output.append({
                'path': relative, 'line': stmt.lineno, 'symbol': sym.name,
                'target_path': sym.path, 'target_module': target[0],
                'expression': expression, 'kind': 'import_linked_call_candidate',
                'caveat': 'Static syntax link; local shadowing, re-exports, and dynamic behavior not resolved.'
            })
            if len(output) >= limit:
                return output
    return output
