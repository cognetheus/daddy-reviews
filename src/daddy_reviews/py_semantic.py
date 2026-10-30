"""R7.03: snapshot-bound Python AST semantic candidates, not runtime proof.

Resolve only unambiguous imports and unconditional reexports. Scope and
receiver inference are deliberately conservative. Missing/ambiguous/dynamic
bindings abstain; never turn AST candidates into confirmed findings.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import keyword

from .graph import _python_names
from .python_symbols import _Bindings, _from_candidates
from .semantic_contracts import (
    SemanticContractError, SourceSpan, SemanticSymbol, SemanticReference,
    bound_span, capture_worktree, context_bundle, validate_snapshot,
    verify_worktree, _safe_path,
)

FORMAT = "daddy-reviews-python-semantic-v1"
MAX_FILES = 800
MAX_BYTES = 5_000_000
MAX_REFERENCES = 200
MAX_ABSTENTIONS = 40
MAX_REEXPORT_HOPS = 8


class PythonSemanticError(ValueError):
    pass


def _result(status, reason, state, symbol):
    return {
        "format": FORMAT, "status": status,
        "snapshot_id": state["snapshot_id"], "target": symbol,
        "definition": None, "references": [], "abstentions": [],
        "warnings": [reason] if reason else [], "context_bundle": None,
        "runtime_calls_proven": False,
        "limitations": [
            "AST import and receiver inference are candidates, not verified runtime calls.",
            "Dynamic imports, monkey-patching, star imports and arbitrary DI abstain.",
            "No language server or third-party type checker is invoked in R7.03.",
        ],
    }


def _imports(path, stmt, module_index):
    """Produce static import bindings: local -> module-path plus exported name.

    Each binding is a (module path, optional exported name). None denotes
    ambiguous or unsupported import; never select a path arbitrarily.
    """
    output = {}
    if isinstance(stmt, ast.ImportFrom):
        modules = _from_candidates(path, stmt)
        destinations = {p for m in modules for p in module_index.get(m, ())}
        for alias in stmt.names:
            local = alias.asname or alias.name
            if alias.name == "*" or len(destinations) != 1:
                output[local] = None
            else:
                output[local] = (next(iter(destinations)), alias.name)
    elif isinstance(stmt, ast.Import):
        for alias in stmt.names:
            paths = module_index.get(alias.name, set())
            local = alias.asname or alias.name.split(".")[0]
            # 'import pkg.mod' binds pkg, not pkg.mod. Resolve only explicit
            # module aliases or non-dotted imports to avoid invented members.
            output[local] = (next(iter(paths)), None) if (
                len(paths) == 1 and (alias.asname or "." not in alias.name)
            ) else None
    return output


def _resolve_export(path, name, target_path, target_name, trees, index,
                    visited=()):
    """Prove only static import provenance, not actual module execution."""
    if path == target_path and name == target_name:
        return (path,)
    if path in visited or len(visited) >= MAX_REEXPORT_HOPS:
        return None
    tree = trees.get(path)
    if tree is None:
        return None
    candidates = []
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name != "*" and (alias.asname or alias.name) == name:
                    source = _imports(path, stmt, index).get(name)
                    if source and source[1] is not None:
                        rest = _resolve_export(source[0], source[1], target_path,
                                               target_name, trees, index, visited + (path,))
                        if rest:
                            candidates.append((path,) + rest)
                        else:
                            return None
        else:
            bindings = _Bindings()
            bindings.visit(stmt)
            if name in bindings.names:
                return None
    return candidates[0] if len(candidates) == 1 else None


def _qualified(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _qualified(node.value)
        return left + "." + node.attr if left else ""
    return ""


def _scope_blocked(stmts, args=None):
    collector = _Bindings()
    if args is not None:
        for node in ast.walk(args):
            if isinstance(node, ast.arg):
                collector.names.add(node.arg)
    for stmt in stmts:
        if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
            collector.visit(stmt)
    return collector.names


class _StoreCounts(ast.NodeVisitor):
    """Count binding writes in a lexical scope including conditional branches.

    Do not attribute writes inside nested functions/classes or comprehensions
    to their parent's scope.
    """

    def __init__(self):
        self.counts = defaultdict(int)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.counts[node.id] += 1

    def visit_FunctionDef(self, node):
        self.counts[node.name] += 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.counts[node.name] += 1

    def visit_Import(self, node):
        for alias in node.names:
            self.counts[alias.asname or alias.name.split(".")[0]] += 1

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name != "*":
                self.counts[alias.asname or alias.name] += 1

    def visit_ExceptHandler(self, node):
        if node.name:
            self.counts[node.name] += 1
        self.generic_visit(node)

    def visit_ListComp(self, node):
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def _local_imports(stmts, path, index, trees, target_path, target_name):
    proposed = defaultdict(list)
    for stmt in stmts:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for name, value in _imports(path, stmt, index).items():
                proposed[name].append((value, stmt.lineno))
    return {name: values[0] for name, values in proposed.items()
            if len(values) == 1}


class _References(ast.NodeVisitor):
    def __init__(self, path, target_path, target_name, kind, trees, index):
        self.path = path
        self.target_path = target_path
        self.target_name = target_name
        self.kind = kind
        self.trees = trees
        self.index = index
        self.refs = []
        self.abstentions = []
        self.env = {}
        self.depth = 0

    def _note(self, node, reason):
        if len(self.abstentions) < MAX_ABSTENTIONS:
            self.abstentions.append({"path": self.path,
                                     "line": getattr(node, "lineno", 1),
                                     "reason": reason})

    def _push_reference(self, node, relationship, via):
        if len(self.refs) >= MAX_REFERENCES:
            return
        self.refs.append({"path": self.path, "line": node.lineno,
                          "relationship": relationship, "provenance_modules": list(via)})

    def _binding(self, value, local, available_after):
        if value is None:
            return None
        path, imported = value
        # Module aliases are resolved only for imported modules, never through
        # attribute chains guessed from package names.
        if imported is None:
            return ("module", path, (), available_after)
        provenance = _resolve_export(path, imported, self.target_path,
                                     self.target_name, self.trees, self.index)
        if provenance:
            return ("target", path, provenance, available_after)
        # Method target: consumer imports its owner class, not the method.
        if "." in self.target_name:
            owner = self.target_name.split(".", 1)[0]
            provenance = _resolve_export(path, imported, self.target_path,
                                         owner, self.trees, self.index)
            if provenance:
                return ("owner", path, provenance, available_after)
        return None

    def _resolve(self, expression):
        """Return (binding category, provenance) for a simple identifier."""
        if not isinstance(expression, ast.Name):
            return None
        value = self.env.get(expression.id)
        if value and len(value) == 4 and expression.lineno <= value[3]:
            self._note(expression, "use_before_unconditional_import")
            return None
        return value

    def _target_expression(self, expression):
        """Resolve direct imported target, module.member, or owner.method."""
        if isinstance(expression, ast.Name):
            bound = self._resolve(expression)
            if bound and bound[0] == "target":
                return bound[2]
            return None
        if isinstance(expression, ast.Attribute):
            qualifier = self._resolve(expression.value)
            last = self.target_name.split(".")[-1]
            if qualifier:
                if qualifier[0] == "module" and expression.attr == self.target_name:
                    chain = _resolve_export(qualifier[1], self.target_name,
                                            self.target_path, self.target_name,
                                            self.trees, self.index)
                    return chain
                if qualifier[0] in ("owner", "instance") and expression.attr == last:
                    return qualifier[2]
            if isinstance(expression.value, ast.Call):
                maker = self._resolve(expression.value.func)
                if maker and maker[0] == "owner" and expression.attr == last:
                    return maker[2]
        return None

    def _walk_body(self, statements, local=False, args=None):
        previous = self.env
        # Bind only unconditional imports, and reject all conflicting lexical
        # stores (even stores which occur after the call).
        blocked = _scope_blocked(statements, args)
        proposed = _local_imports(statements, self.path, self.index, self.trees,
                                  self.target_path, self.target_name)
        # Any import in this scope shadows the inherited name even when its
        # resolution is unknown, duplicated, or conditional.
        imported = {alias.asname or alias.name.split(".")[0]
                    for stmt in statements if isinstance(stmt, ast.Import)
                    for alias in stmt.names}
        imported.update(alias.asname or alias.name
                        for stmt in statements if isinstance(stmt, ast.ImportFrom)
                        for alias in stmt.names if alias.name != "*")
        env = {k: v for k, v in previous.items() if k not in blocked | imported}
        for name, (value, line) in proposed.items():
            if name not in blocked:
                bound = self._binding(value, name, line)
                if bound:
                    env[name] = bound
        if args is not None:
            for arg in ast.walk(args):
                if isinstance(arg, ast.arg) and isinstance(arg.annotation, ast.Name):
                    maker = env.get(arg.annotation.id)
                    if maker and maker[0] == "owner":
                        env[arg.arg] = ("instance", maker[1], maker[2], 0)
        # Safe constructor/typed receiver inference: one assignment per name,
        # no further stores anywhere in the current scope. It is a candidate.
        assigned = defaultdict(list)
        for stmt in statements:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                destinations = (stmt.targets if isinstance(stmt, ast.Assign)
                                else [stmt.target])
                for dest in destinations:
                    if isinstance(dest, ast.Name):
                        assigned[dest.id].append(stmt)
        counter = _StoreCounts()
        for stmt in statements:
            counter.visit(stmt)
        arg_names = {arg.arg for arg in ast.walk(args) if isinstance(arg, ast.arg)} if args else set()
        for name, defs in assigned.items():
            if len(defs) != 1 or counter.counts[name] != 1 or name in arg_names:
                continue
            node = defs[0]
            value = node.value
            annotation = node.annotation if isinstance(node, ast.AnnAssign) else None
            creator = value.func if isinstance(value, ast.Call) else annotation
            maker = env.get(creator.id) if isinstance(creator, ast.Name) else None
            if maker and len(maker) == 4 and maker[3] >= node.lineno:
                maker = None
            if maker and maker[0] == "owner":
                env[name] = ("instance", maker[1], maker[2], node.lineno)
        self.env = env
        self.depth += 1
        for stmt in statements:
            self.visit(stmt)
        self.depth -= 1
        self.env = previous

    def visit_Module(self, node):
        self._walk_body(node.body)

    def visit_FunctionDef(self, node):
        # Decorators/annotations resolve in the defining (outer) scope.
        for deco in node.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            chain = self._target_expression(target)
            if chain:
                self._push_reference(deco, "decorator_reference", chain)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            if arg.annotation:
                chain = self._target_expression(arg.annotation)
                if chain:
                    self._push_reference(arg.annotation, "type_annotation_candidate", chain)
                self.visit(arg.annotation)
        if node.returns:
            chain = self._target_expression(node.returns)
            if chain:
                self._push_reference(node.returns, "type_annotation_candidate", chain)
            self.visit(node.returns)
        self._walk_body(node.body, local=True, args=node.args)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for deco in node.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            chain = self._target_expression(target)
            if chain:
                self._push_reference(deco, "decorator_reference", chain)
        for base in node.bases:
            chain = self._target_expression(base)
            if chain:
                self._push_reference(base, "heritage_reference", chain)
        # Class scope does not become the global lookup environment for methods.
        self._walk_body(node.body)

    def visit_AnnAssign(self, node):
        chain = self._target_expression(node.annotation)
        if chain:
            self._push_reference(node.annotation, "type_annotation_candidate", chain)
        self.generic_visit(node)

    def visit_Call(self, node):
        chain = self._target_expression(node.func)
        if chain:
            relation = "constructor_candidate" if self.kind == "class" and isinstance(
                node.func, ast.Name) else ("member_call_candidate" if "." in self.target_name
                else "direct_call_candidate")
            self._push_reference(node, relation, chain)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # Avoid emitting untyped arbitrary .method lookups as proven members.
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id == self.target_name and node.id not in self.env:
            self._note(node, "unresolved_or_shadowed_identifier")


def index_python(root: Path, changed_path: str, symbol: str,
                 snapshot: dict | None = None) -> dict:
    """AST-anchored references across local, unambiguous module boundaries."""
    root = root.resolve()
    if (not root.is_dir() or not _safe_path(changed_path)
            or not changed_path.endswith(".py")
            or not isinstance(symbol, str) or len(symbol) > 255
            or not all(part.isidentifier() and not keyword.iskeyword(part)
                        for part in symbol.split("."))
            or len(symbol.split(".")) > 2):
        raise PythonSemanticError("Expected Python source path and Symbol or Class.method")
    state = capture_worktree(root) if snapshot is None else validate_snapshot(snapshot)
    result = _result("incomplete", "", state, {"path": changed_path, "symbol": symbol})
    if not state["complete"]:
        return _result("incomplete", "Source snapshot is incomplete", state, result["target"])
    if not verify_worktree(root, state)["verified"]:
        return _result("stale", "Worktree differs from captured source snapshot", state, result["target"])
    python_files = [e for e in state["files"] if e["path"].endswith(".py")]
    if len(python_files) > MAX_FILES or sum(e["size_bytes"] for e in python_files) > MAX_BYTES:
        return _result("incomplete", "Python semantic indexing budget exceeded", state, result["target"])
    if changed_path not in {e["path"] for e in python_files}:
        return _result("unresolved", "Target is not in captured Python source", state, result["target"])
    trees = {}
    warnings = []
    for entry in python_files:
        candidate = root / entry["path"]
        if candidate.is_symlink():
            return _result("stale", "Symlink source appeared", state, result["target"])
        try:
            raw = candidate.read_bytes()
            import hashlib
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                return _result("stale", "Source changed during indexing", state, result["target"])
            trees[entry["path"]] = ast.parse(raw.decode("utf-8"), filename=entry["path"])
        except (OSError, UnicodeError, SyntaxError, ValueError):
            warnings.append(f"{entry['path']}: unsupported or malformed Python source")
    if changed_path not in trees:
        return _result("incomplete", "Target source cannot be parsed", state, result["target"])
    names = symbol.split(".")
    target = trees[changed_path]
    top = [n for n in target.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
           and n.name == names[0]]
    if len(top) != 1:
        return _result("ambiguous" if top else "unresolved",
                       "Target declaration is missing or ambiguous", state, result["target"])
    selected = top[0]
    if len(names) == 2:
        if not isinstance(selected, ast.ClassDef):
            return _result("unresolved", "Method owner is not a class", state, result["target"])
        members = [n for n in selected.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == names[1]]
        if len(members) != 1:
            return _result("ambiguous" if members else "unresolved",
                           "Method declaration is missing or ambiguous", state, result["target"])
        selected = members[0]
    for stmt in target.body:
        if stmt is top[0]:
            continue
        binds = _Bindings()
        binds.visit(stmt)
        if names[0] in binds.names:
            return _result("ambiguous", "Target has competing module-level bindings",
                           state, result["target"])
    if len(names) == 2:
        for stmt in top[0].body:
            if stmt is selected:
                continue
            binds = _Bindings()
            binds.visit(stmt)
            if names[1] in binds.names:
                return _result("ambiguous", "Method has competing class-level bindings",
                               state, result["target"])
    index = defaultdict(set)
    for path in trees:
        for name in _python_names(path):
            index[name].add(path)
    # Avoid a misleading answer if target module has conflicting resolutions.
    if any(len(index[name]) > 1 for name in _python_names(changed_path)):
        return _result("ambiguous", "Target module path is ambiguous", state, result["target"])
    definition = bound_span(state, changed_path, selected.lineno, selected.lineno,
                            "ast", "candidate")
    references, abstentions = [], []
    provenance = defaultdict(set)
    for path, tree in sorted(trees.items()):
        if path == changed_path:
            continue
        visitor = _References(path, changed_path, symbol,
                              "class" if isinstance(selected, ast.ClassDef) else "function",
                              trees, index)
        visitor.visit(tree)
        for item in visitor.refs:
            if len(references) >= MAX_REFERENCES:
                warnings.append("Reference budget exhausted")
                break
            try:
                span = bound_span(state, path, item["line"], item["line"],
                                  "ast", "candidate")
                references.append(SemanticReference(symbol, item["relationship"],
                                                    span, definition))
                provenance[(span.path, span.start_line, item["relationship"])].add(
                    tuple(item["provenance_modules"]))
            except SemanticContractError:
                warnings.append(f"{path}: ungrounded reference location")
                break
        abstentions.extend(visitor.abstentions[:max(0, MAX_ABSTENTIONS - len(abstentions))])
        if len(references) >= MAX_REFERENCES:
            break
    if not verify_worktree(root, state)["verified"]:
        return _result("stale", "Worktree changed during AST analysis", state, result["target"])
    answer = _result("partial" if warnings else "complete", "", state, result["target"])
    answer["definition"] = asdict(definition)
    ordered = sorted(references, key=lambda r: (
        r.location.path, r.location.start_line, r.relationship))
    answer["references"] = [
        {**asdict(r), "provenance_modules": list(sorted(provenance[(
            r.location.path, r.location.start_line, r.relationship)]))}
        for r in ordered
    ]
    answer["abstentions"] = abstentions
    answer["warnings"] = warnings[:40]
    answer["context_bundle"] = context_bundle(
        state, [SemanticSymbol(symbol, "python_ast_declaration", definition)], references)
    return answer
