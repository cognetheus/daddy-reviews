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



class _ExportProvenance:
    """Follow only unambiguous, unconditional module-level from-import exports.

    This is a bounded AST provenance chain, not Python import execution.
    Dynamic attributes, star exports, conditional imports and rebinding abstain.
    """

    MAX_HOPS = 8

    def __init__(self, root: Path, index: dict[str, set[str]],
                 target: str, symbol: str) -> None:
        self.root = root
        self.index = index
        self.target = target
        self.symbol = symbol
        self._trees: dict[str, ast.Module | None] = {}

    def trace(self, path: str, name: str, visited: tuple[str, ...] = ()) -> tuple[str, ...] | None:
        if path == self.target and name == self.symbol:
            return (path,)
        if path in visited or len(visited) >= self.MAX_HOPS:
            return None
        if path not in self._trees:
            try:
                self._trees[path] = ast.parse((self.root / path).read_text(encoding='utf-8'))
            except (OSError, UnicodeError, SyntaxError):
                self._trees[path] = None
        tree = self._trees[path]
        if tree is None:
            return None

        imports: list[tuple[ast.ImportFrom, str]] = []
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    if alias.name != '*' and (alias.asname or alias.name) == name:
                        imports.append((stmt, alias.name))
            else:
                collector = _Bindings()
                collector.visit(stmt)
                if name in collector.names:
                    return None
        if len(imports) != 1:
            return None
        statement, exported_name = imports[0]
        module = _unique(self.index, _from_candidates(path, statement))
        if module is None:
            return None
        suffix = self.trace(module, exported_name, visited + (path,))
        return (path,) + suffix if suffix else None

    def exported_names(self, path: str) -> list[tuple[str, tuple[str, ...]]]:
        """Find uniquely proven names in a module that reach the selected target.

        More than one proven name is deliberately left to the caller to
        abstain on rather than arbitrarily choosing an import expression.
        """
        if path == self.target:
            return [(self.symbol, (path,))]
        # Load the module through the same bounded AST cache.
        self.trace(path, self.symbol)
        tree = self._trees.get(path)
        if tree is None:
            return []
        names = {alias.asname or alias.name
                 for stmt in tree.body if isinstance(stmt, ast.ImportFrom)
                 for alias in stmt.names if alias.name != '*'}
        if len(names) > 64:
            return []
        results = []
        for name in sorted(names):
            chain = self.trace(path, name)
            if chain:
                results.append((name, chain))
        return results


def _import_candidates(path: str, stmt: ast.Import | ast.ImportFrom,
                       index: dict[str, set[str]],
                       resolver: _ExportProvenance) -> tuple[dict[str, list[tuple[str, tuple[str, ...]]]], set[str]]:
    """Resolve one import statement to candidates, or conservatively reject names."""
    possible: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    rejected: set[str] = set()
    if isinstance(stmt, ast.ImportFrom):
        candidates = _from_candidates(path, stmt)
        resolved_module = _unique(index, candidates)
        for alias in stmt.names:
            if alias.name == '*':
                continue
            binding = alias.asname or alias.name
            chain = resolver.trace(resolved_module, alias.name) if resolved_module is not None else None
            submodule = _unique(index, {name + '.' + alias.name for name in candidates})
            if chain and submodule is not None:
                rejected.add(binding)
            elif chain:
                possible[binding].append((binding, chain))
            elif submodule is not None:
                exports = resolver.exported_names(submodule)
                if len(exports) == 1:
                    name, via = exports[0]
                    possible[binding].append((binding + '.' + name, via))
                else:
                    rejected.add(binding)
            else:
                rejected.add(binding)
    else:
        for alias in stmt.names:
            binding = alias.asname or alias.name.split('.')[0]
            resolved = _unique(index, {alias.name})
            exports = resolver.exported_names(resolved) if resolved is not None else []
            if len(exports) == 1:
                name, via = exports[0]
                prefix = binding if alias.asname else alias.name
                possible[binding].append((prefix + '.' + name, via))
            else:
                rejected.add(binding)
    return possible, rejected


class _Calls(ast.NodeVisitor):
    def __init__(self, path: str, bindings: dict[str, str], target: str, symbol: str,
                 provenance: dict[str, tuple[str, ...]] | None = None,
                 index: dict[str, set[str]] | None = None,
                 resolver: _ExportProvenance | None = None) -> None:
        self.path = path
        self.bindings = bindings
        self.target = target
        self.symbol = symbol
        self.provenance = provenance or {}
        self.index = index or {}
        self.resolver = resolver
        self.scopes: list[set[str]] = []
        # Only imports directly in a function body are eligible. Imports in
        # branches, nested definitions and class bodies are not promoted.
        self.local_imports: list[dict[str, tuple[str, tuple[str, ...], int]]] = []
        self.references: list[dict] = []
        self.abstentions: list[dict] = []
        self.truncated = False

    def _enter(self, node: ast.AST, body: list[ast.stmt]) -> None:
        local: dict[str, tuple[str, tuple[str, ...], int]] = {}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and self.resolver:
            proposed: dict[str, list[tuple[str, tuple[str, ...], int]]] = defaultdict(list)
            excluded = _Bindings()
            for stmt in body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    options, rejected = _import_candidates(self.path, stmt, self.index, self.resolver)
                    excluded.names.update(rejected)
                    for name, entries in options.items():
                        proposed[name].extend((expr, chain, stmt.lineno) for expr, chain in entries)
                else:
                    excluded.visit(stmt)
            local = {name: entries[0] for name, entries in proposed.items()
                     if len(entries) == 1 and name not in excluded.names}
        self.scopes.append(_scope_bindings(node))
        self.local_imports.append(local)
        for stmt in body:
            if self.truncated:
                break
            self.visit(stmt)
        self.local_imports.pop()
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.scopes.append(_scope_bindings(node))
        self.local_imports.append({})
        self.visit(node.body)
        self.local_imports.pop()
        self.scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Call(self, node: ast.Call) -> None:
        expression = _dotted(node.func)
        head = expression.split('.')[0]
        local = self.local_imports[-1].get(head) if self.local_imports else None
        chain: tuple[str, ...] | None = None
        if expression and local and local[0] == expression:
            if node.lineno > local[2]:
                chain = local[1]
            elif len(self.abstentions) < MAX_ABSTENTIONS:
                self.abstentions.append({'path': self.path, 'line': node.lineno,
                                         'expression': expression, 'reason': 'call_not_after_local_import'})
        elif expression and self.bindings.get(head) == expression:
            if any(head in scope for scope in self.scopes):
                if len(self.abstentions) < MAX_ABSTENTIONS:
                    self.abstentions.append({'path': self.path, 'line': node.lineno,
                                             'expression': expression, 'reason': 'lexical_binding_or_shadowing'})
            else:
                chain = self.provenance.get(head, ())
        if chain is not None:
            self.references.append({
                'path': self.path, 'line': node.lineno, 'expression': expression,
                'symbol': self.symbol, 'target_path': self.target,
                'classification': 'python_ast_import_bound_call_candidate',
                'provenance_modules': list(chain),
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
    declarations = [n for n in target_tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and n.name == symbol]
    if len(declarations) != 1:
        raise SymbolImpactError('Target symbol must have exactly one top-level function or class declaration')
    for statement in target_tree.body:
        if statement is declarations[0]:
            continue
        bindings = _Bindings()
        bindings.visit(statement)
        if symbol in bindings.names:
            raise SymbolImpactError('Target symbol has conflicting module-level bindings')

    index: dict[str, set[str]] = defaultdict(set)
    for path in sorted(indexed):
        if path.endswith('.py'):
            for name in _python_names(path):
                index[name].add(path)

    provenance_resolver = _ExportProvenance(root, index, changed_path, symbol)
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
        possible: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
        non_import_bindings = _Bindings()
        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                options, rejected = _import_candidates(path, stmt, index, provenance_resolver)
                non_import_bindings.names.update(rejected)
                for name, entries in options.items():
                    possible[name].extend(entries)
            else:
                non_import_bindings.visit(stmt)

        bindings = {binding: entries[0][0] for binding, entries in possible.items()
                    if len(entries) == 1 and binding not in non_import_bindings.names}
        provenance = {binding: entries[0][1] for binding, entries in possible.items()
                      if binding in bindings}
        visitor = _Calls(path, bindings, changed_path, symbol, provenance, index, provenance_resolver)
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
            'Only unconditional direct function-body imports are considered; conditional, class-body, nested-definition and star imports may be missed.',
            'Function-local imports require calls on later lines and no competing lexical bindings; closures and comprehensions remain conservative.',
            'Dynamic exports, conditional reexports, monkey-patching and dynamic calls are not resolved.',
            'Only unambiguous, unconditional, bounded module-level from-import reexport chains are traced.',
            'Lexical shadowing conservatively abstains; missing candidates do not establish isolation.',
        ],
    }
