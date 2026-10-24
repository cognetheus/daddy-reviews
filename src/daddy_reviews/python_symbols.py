"""Bounded Python AST import-bound call candidates for a selected definition.

This is deliberately not a runtime call graph or a full Python name resolver.
Ambiguous modules, rebinding and nested import scopes abstain rather than
pretending a syntactic match is a verified invocation.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from .graph import _python_names, build_graph

MAX_CALLS = 100
MAX_ABSTENTIONS = 30


class SymbolImpactError(ValueError):
    pass


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return base + '.' + node.attr if base else ''
    return ''


class _Bindings(ast.NodeVisitor):
    """Conservative names bound in ONE lexical scope (not nested definitions)."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split('.')[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != '*':
                self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Global(self, node: ast.Global) -> None:
        self.names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.names.update(node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    # Comprehension targets belong to their own implicit scope. Calls inside
    # comprehensions are conservatively excluded by _Calls.
    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def _scope_bindings(node: ast.AST) -> set[str]:
    collector = _Bindings()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for arg in ast.walk(node.args):
            if isinstance(arg, ast.arg):
                collector.names.add(arg.arg)
    for stmt in node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else [node.body]:
        collector.visit(stmt)
    return collector.names


def _from_candidates(relative: str, node: ast.ImportFrom) -> set[str]:
    if not node.level:
        return {node.module} if node.module else set()
    names: set[str] = set()
    for current in _python_names(relative):
        parts = current.split('.')
        package = parts if relative.endswith('/__init__.py') or relative == '__init__.py' else parts[:-1]
        if node.level - 1 > len(package):
            continue
        base = package[:len(package) - (node.level - 1)]
        parts = base + (node.module.split('.') if node.module else [])
        if parts:
            names.add('.'.join(parts))
    return names


def _unique(index: dict[str, set[str]], candidates: set[str]) -> str | None:
    matches = set()
    for name in candidates:
        matches.update(index.get(name, set()))
    return next(iter(matches)) if len(matches) == 1 else None


class _Calls(ast.NodeVisitor):
    def __init__(self, path: str, bindings: dict[str, str], target: str, symbol: str) -> None:
        self.path = path
        self.bindings = bindings
        self.target = target
        self.symbol = symbol
        self.scopes: list[set[str]] = []
        self.references: list[dict] = []
        self.abstentions: list[dict] = []
        self.truncated = False

    def _enter(self, node: ast.AST, body: list[ast.stmt]) -> None:
        self.scopes.append(_scope_bindings(node))
        for stmt in body:
            if self.truncated:
                break
            self.visit(stmt)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.scopes.append(_scope_bindings(node))
        self.visit(node.body)
        self.scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Call(self, node: ast.Call) -> None:
        expression = _dotted(node.func)
        head = expression.split('.')[0]
        if expression and self.bindings.get(head) == expression:
            if any(head in scope for scope in self.scopes):
                if len(self.abstentions) < MAX_ABSTENTIONS:
                    self.abstentions.append({'path': self.path, 'line': node.lineno,
                                             'expression': expression, 'reason': 'lexical_binding_or_shadowing'})
            else:
                self.references.append({
                    'path': self.path, 'line': node.lineno, 'expression': expression,
                    'symbol': self.symbol, 'target_path': self.target,
                    'classification': 'python_ast_import_bound_call_candidate',
                })
                if len(self.references) >= MAX_CALLS:
                    self.truncated = True
                    return
        self.generic_visit(node)


def python_symbol_impact(root: Path, changed_path: str, symbol: str) -> dict:
    """Return bounded, conservatively resolved cross-module call candidates."""
    root = root.resolve()
    graph = build_graph(root)
    indexed = {node['path'] for node in graph['nodes']}
    if changed_path not in indexed or not changed_path.endswith('.py'):
        raise SymbolImpactError('Target must be an indexed Python source path')
    if not symbol.isidentifier():
        raise SymbolImpactError('Target symbol must be a Python identifier')
    target_file = root / changed_path
    try:
        target_tree = ast.parse(target_file.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise SymbolImpactError('Target Python source cannot be parsed') from exc
    if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               and n.name == symbol for n in target_tree.body):
        raise SymbolImpactError('Target symbol must be a top-level function or class')

    index: dict[str, set[str]] = defaultdict(set)
    for path in sorted(indexed):
        if path.endswith('.py'):
            for name in _python_names(path):
                index[name].add(path)

    references: list[dict] = []
    abstentions: list[dict] = []
    warnings = list(graph['warnings'])
    truncated = False
    for path in sorted(indexed):
        if not path.endswith('.py') or path == changed_path:
            continue
        try:
            tree = ast.parse((root / path).read_text(encoding='utf-8'))
        except (OSError, UnicodeError, SyntaxError):
            warnings.append(f'{path}: cannot parse Python references')
            continue
        possible: dict[str, list[str]] = defaultdict(list)
        non_import_bindings = _Bindings()
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom):
                candidates = _from_candidates(path, stmt)
                resolved_module = _unique(index, candidates)
                for alias in stmt.names:
                    if alias.name == '*':
                        continue
                    binding = alias.asname or alias.name
                    if resolved_module == changed_path and alias.name == symbol:
                        possible[binding].append(binding)
                    else:
                        submodule = _unique(index, {name + '.' + alias.name for name in candidates})
                        if submodule == changed_path:
                            possible[binding].append(binding + '.' + symbol)
                        else:
                            non_import_bindings.names.add(binding)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    binding = alias.asname or alias.name.split('.')[0]
                    resolved = _unique(index, {alias.name})
                    if resolved == changed_path:
                        expression = binding + '.' + symbol if alias.asname else alias.name + '.' + symbol
                        possible[binding].append(expression)
                    else:
                        non_import_bindings.names.add(binding)
            else:
                non_import_bindings.visit(stmt)

        bindings = {binding: exprs[0] for binding, exprs in possible.items()
                    if len(exprs) == 1 and binding not in non_import_bindings.names}
        if not bindings:
            continue
        visitor = _Calls(path, bindings, changed_path, symbol)
        for stmt in tree.body:
            if visitor.truncated:
                break
            visitor.visit(stmt)
        for entry in visitor.references:
            if len(references) >= MAX_CALLS:
                truncated = True
                break
            references.append(entry)
        abstentions.extend(visitor.abstentions[:max(0, MAX_ABSTENTIONS - len(abstentions))])
        if visitor.truncated or len(references) >= MAX_CALLS:
            truncated = True
            break
    return {
        'format': 'daddy-reviews-python-symbol-impact-v1',
        'target': {'path': changed_path, 'symbol': symbol},
        'references': references,
        'shadowed_abstentions': abstentions,
        'warnings': warnings,
        'truncated': truncated or bool(warnings),
        'limitations': [
            'Only top-level Python functions/classes and syntactically import-bound call sites are indexed.',
            'This is not runtime reachability, verified invocation, or a compiler/LSP symbol graph.',
            'Nested imports, star imports, reexports, monkey-patching, dynamic calls and comprehensions may be missed.',
            'Lexical shadowing conservatively abstains; missing candidates do not establish isolation.',
        ],
    }
