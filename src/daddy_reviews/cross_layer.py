"""R7.05: source-backed, *candidate* cross-layer dependency and impact graph.

Narrow, explicit static patterns only:
  frontend literal fetch/axios -> unique FastAPI route (same literal path+method)
  FastAPI handler -> import-bound Python service function
  service -> imported/declared SQLAlchemy-style model -> declared table
  publisher -> literal topic -> subscribed consumer function
No dynamic behavior, authorization outcome, actual network request or runtime
reachability is inferred. Unresolved and ambiguous bindings abstain.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib
from pathlib import Path

from .cross_layer_js import extract_http_calls
from .graph import _python_names
from .semantic_contracts import (
    SemanticContractError, _safe_path, bound_span, capture_worktree,
    validate_snapshot, verify_worktree,
)

FORMAT = "daddy-reviews-cross-layer-v1"
MAX_PY_FILES = 800
MAX_JS_FILES = 800
MAX_SOURCE_BYTES = 8_000_000
MAX_EDGES = 4000
MAX_ABSTENTIONS = 200
MAX_RESULTS = 200
MAX_HOPS = 6
_JS_SUFFIX = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
_VERB = {"get": "GET", "post": "POST", "put": "PUT",
         "delete": "DELETE", "patch": "PATCH"}


class CrossLayerError(ValueError):
    pass


def _blank(state, status, warnings):
    return {"format": FORMAT, "status": status, "snapshot_id": state["snapshot_id"],
            "nodes": [], "edges": [], "abstentions": [], "warnings": warnings,
            "limitations": [
                "Static evidence candidates only, not proof of runtime reachability or actual requests.",
                "Supports literal frontend HTTP requests, local FastAPI routes, direct Python imports, "
                "simple SQLAlchemy-like models and literal publish/subscribe topics.",
                "No full NestJS/Express, DRF, Spring, ASP.NET, ORM query planner, DTO serialization, "
                "project config, dynamic routing, reexports or inferred authorization semantics.",
                "Incomplete or ambiguous source cannot be treated as evidence of isolation.",
            ]}


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _attr_call(node, method):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method


def _module_index(trees):
    aliases = defaultdict(set)
    for path in trees:
        for name in _python_names(path):
            aliases[name].add(path)
    return aliases


def _imports(path, tree, aliases):
    """Only statically unambiguous module-level import-bound names."""
    out = {}
    competing = set()
    parts = path.split("/")
    if parts[-1] == "__init__.py":
        package = parts[:-1]
    else:
        package = parts[:-1]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package) + 1:
                    continue
                prefix = package[:len(package) - (node.level - 1)]
                mod = ".".join(prefix + (node.module.split(".") if node.module else []))
            else:
                mod = node.module or ""
            paths = aliases.get(mod, set())
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if local in out:
                    competing.add(local)
                elif len(paths) == 1:
                    out[local] = (next(iter(paths)), alias.name)
                else:
                    competing.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                paths = aliases.get(alias.name, set())
                if local in out:
                    competing.add(local)
                elif len(paths) == 1 and (alias.asname or "." not in alias.name):
                    out[local] = (next(iter(paths)), None)
                else:
                    competing.add(local)
        else:
            # Competing non-import module-level bindings revoke import certainty.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                competing.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for child in ast.walk(target):
                        if isinstance(child, ast.Name):
                            competing.add(child.id)
    return {k: v for k, v in out.items() if k not in competing}


def _function_blocked(fn):
    """Conservatively exclude imports shadowed in function scope or later writes."""
    blocked = {arg.arg for arg in ast.walk(fn.args) if isinstance(arg, ast.arg)}
    for child in ast.walk(fn):
        if child is fn:
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            blocked.add(child.id)
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                blocked.add(alias.asname or alias.name.split(".")[0])
    return blocked


def _calls(fn):
    """Only directly contained calls; never attribute a nested function's work to its parent."""
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.items = []
        def visit_Call(self, node):
            self.items.append(node)
            self.generic_visit(node)
        def visit_FunctionDef(self, node):
            if node is fn:
                for stmt in node.body: self.visit(stmt)
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_ClassDef(self, node):
            pass
    visitor = Visitor()
    visitor.visit(fn)
    return visitor.items


def _route_bindings(tree):
    from_fastapi = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "fastapi":
            from_fastapi.update(a.asname or a.name for a in stmt.names
                                if a.name in {"FastAPI", "APIRouter"})
    variables = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Name) and func.id in from_fastapi:
                # Router prefixes cannot be matched by this standalone adapter.
                if stmt.value.args or stmt.value.keywords:
                    continue
                variables.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
    return variables


def _route(fn, variables):
    candidates = []
    for decorator in fn.decorator_list:
        if (not isinstance(decorator, ast.Call) or
                not isinstance(decorator.func, ast.Attribute) or
                not isinstance(decorator.func.value, ast.Name) or
                decorator.func.value.id not in variables):
            continue
        method = _VERB.get(decorator.func.attr)
        if method is None or len(decorator.args) != 1:
            continue
        if any(kw.arg != "response_model" for kw in decorator.keywords):
            continue
        response = next((kw.value for kw in decorator.keywords
                         if kw.arg == "response_model"), None)
        url = _string(decorator.args[0])
        if (not url or len(url) > 300 or not url.startswith("/") or
                url.startswith("//") or "{" in url or "}" in url or "?" in url):
            continue
        candidates.append((method, url, decorator.lineno, response))
    return candidates


def _dto_class(class_node, tree):
    pydantic_bases = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "pydantic":
            pydantic_bases.update(alias.asname or alias.name for alias in stmt.names
                                  if alias.name == "BaseModel")
    return bool(pydantic_bases and any(
        isinstance(base, ast.Name) and base.id in pydantic_bases
        for base in class_node.bases
    ))


def _alembic_op(tree):
    aliases = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "alembic":
            aliases.update(a.asname or a.name for a in stmt.names if a.name == "op")
        elif isinstance(stmt, ast.Import):
            aliases.update(a.asname for a in stmt.names
                           if a.name == "alembic.op" and a.asname)
    return aliases


def _table(class_node):
    values = []
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets):
                values.append((_string(stmt.value), stmt.lineno))
    if len(values) == 1 and values[0][0] and len(values[0][0]) <= 120:
        return values[0]
    return None


def build_cross_layer(root: Path, snapshot: dict | None = None) -> dict:
    """Create a deterministic, bounded graph without executing repository code."""
    root = root.resolve()
    if not root.is_dir():
        raise CrossLayerError("Root is not a directory")
    state = capture_worktree(root) if snapshot is None else validate_snapshot(snapshot)
    if not state["complete"]:
        return _blank(state, "incomplete", ["Incomplete source manifest; no edges emitted"])
    if not verify_worktree(root, state)["verified"]:
        return _blank(state, "stale", ["Snapshot differs from current worktree"])
    source_entries = [f for f in state["files"]
                      if f["path"].endswith(".py") or Path(f["path"]).suffix in _JS_SUFFIX]
    if (sum(f["path"].endswith(".py") for f in source_entries) > MAX_PY_FILES or
            sum(Path(f["path"]).suffix in _JS_SUFFIX for f in source_entries) > MAX_JS_FILES or
            sum(f["size_bytes"] for f in source_entries) > MAX_SOURCE_BYTES):
        return _blank(state, "incomplete", ["Cross-layer indexing budget exceeded"])
    sources = {}
    for record in source_entries:
        path = record["path"]
        full = root / path
        if full.is_symlink():
            return _blank(state, "stale", ["Source symlink appeared during scan"])
        try:
            resolved = full.resolve(strict=True)
            resolved.relative_to(root)
            data = resolved.read_bytes()
            if len(data) != record["size_bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                return _blank(state, "stale", ["Source hash changed during scan"])
            sources[path] = data.decode("utf-8")
        except (ValueError, OSError, UnicodeError):
            return _blank(state, "stale", ["Source unavailable or not UTF-8"])
    trees = {}
    warnings = []
    for path, text in sources.items():
        if path.endswith(".py"):
            try:
                trees[path] = ast.parse(text, filename=path)
            except (SyntaxError, ValueError):
                warnings.append(f"{path}: Python AST syntax error; file skipped")
    aliases = _module_index(trees)
    imported = {path: _imports(path, tree, aliases) for path, tree in trees.items()}
    functions = {}
    classes = {}
    dto_keys = set()
    competing = set()
    nodes = {}
    edges = {}
    abstentions = []

    def abstain(path, line, reason):
        if len(abstentions) < MAX_ABSTENTIONS:
            abstentions.append({"path": path, "line": line, "reason": reason})

    def node(kind, path, line, name):
        if len(nodes) >= 3000:
            raise CrossLayerError("Node budget exhausted")
        span = bound_span(state, path, line, line, "ast" if path.endswith(".py") else "lexical", "candidate")
        key = f"{kind}:{path}:{line}:{name}"
        nodes[key] = {"id": key, "kind": kind, "name": name, "source": span.__dict__}
        return key

    def resource(kind, name, path, line):
        key = f"{kind}:{name}"
        if key not in nodes:
            node(kind, path, line, name)
            original = nodes.pop(f"{kind}:{path}:{line}:{name}")
            original["id"] = key
            nodes[key] = original
        return key

    def edge(src, dst, relation, path, line):
        if len(edges) >= MAX_EDGES:
            raise CrossLayerError("Edge budget exhausted")
        span = bound_span(state, path, line, line, "ast" if path.endswith(".py") else "lexical", "candidate")
        key = (src, dst, relation, path, line)
        edges[key] = {"source": src, "target": dst, "relationship": relation,
                      "evidence": span.__dict__, "certainty": "candidate"}

    for path, tree in sorted(trees.items()):
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                key = (path, item.name)
                if key in functions or key in classes:
                    competing.add(key)
                    abstain(path, item.lineno, "duplicate_module_declaration")
                    continue
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[key] = item
                    node("function", path, item.lineno, item.name)
                else:
                    classes[key] = item
                    table = _table(item)
                    if table:
                        cls = node("model", path, item.lineno, item.name)
                        target = resource("table", table[0], path, table[1])
                        edge(cls, target, "declares_table_candidate", path, table[1])
                    elif _dto_class(item, tree):
                        dto_keys.add(key)
                        node("dto", path, item.lineno, item.name)
    for key in competing:
        functions.pop(key, None)
        classes.pop(key, None)
        dto_keys.discard(key)
    # Discard ambiguous declaration nodes and their model/table edges.
    stale_ids = {key for key, record in nodes.items()
                 if record["kind"] in ("function", "model", "dto") and
                 (record["source"]["path"], record["name"]) in competing}
    for stale in stale_ids:
        nodes.pop(stale, None)
    edges = {k: e for k, e in edges.items()
             if e["source"] not in stale_ids and e["target"] not in stale_ids}

    def function_id(path, fn):
        return f"function:{path}:{fn.lineno}:{fn.name}"
    def model_id(path, cl):
        return f"model:{path}:{cl.lineno}:{cl.name}"

    routes = defaultdict(list)
    route_contracts = []
    route_handlers = []
    for path, tree in sorted(trees.items()):
        variables = _route_bindings(tree)
        for (p, name), fn in sorted(functions.items()):
            if p != path:
                continue
            for method, url, line, response in _route(fn, variables):
                endpoint = node("http_route", path, line, f"{method} {url}")
                routes[(method, url)].append(endpoint)
                route_handlers.append((path, fn, endpoint))
                edge(endpoint, function_id(path, fn), "route_handler_candidate", path, line)
                if response is not None:
                    route_contracts.append((path, endpoint, response, line))
    # Model lookup is grounded by explicit imports / declarations, not class spelling.
    def resolve_name(path, name, blocked):
        if name in blocked:
            return None
        bindings = imported[path]
        if name in bindings:
            target_path, declared = bindings[name]
            return target_path, declared
        if (path, name) in functions or (path, name) in classes:
            return path, name
        return None

    def dto_id(path, declared):
        cls = classes.get((path, declared))
        if cls is None or (path, declared) not in dto_keys:
            return None
        return f"dto:{path}:{cls.lineno}:{cls.name}"

    for path, endpoint, response, line in route_contracts:
        if isinstance(response, ast.Name):
            target = resolve_name(path, response.id, set())
            dto = dto_id(*target) if target else None
            if dto and dto in nodes:
                edge(endpoint, dto, "http_response_dto_candidate", path, line)
            else:
                abstain(path, line, "response_dto_unresolved")
        else:
            abstain(path, line, "dynamic_response_dto")
    for path, fn, endpoint in route_handlers:
        for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
            if isinstance(arg.annotation, ast.Name):
                target = resolve_name(path, arg.annotation.id, set())
                dto = dto_id(*target) if target else None
                if dto and dto in nodes:
                    edge(endpoint, dto, "http_request_dto_candidate", path, arg.lineno)

    def expression_target(path, expression, blocked):
        if isinstance(expression, ast.Name):
            return resolve_name(path, expression.id, blocked)
        if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
            binding = imported[path].get(expression.value.id)
            if binding and binding[1] is None and expression.value.id not in blocked:
                return binding[0], expression.attr
        return None

    for (path, _name), fn in sorted(functions.items()):
        here = function_id(path, fn)
        blocked = _function_blocked(fn)
        for call in _calls(fn):
            found = expression_target(path, call.func, blocked)
            if found in functions and found != (path, fn.name):
                dst = function_id(found[0], functions[found])
                edge(here, dst, "python_function_call_candidate", path, call.lineno)
            elif found and found[0] != path and found not in classes:
                # Don't silently treat an import as a resolved callable.
                abstain(path, call.lineno, "imported_function_unresolved")
            if isinstance(call.func, ast.Attribute):
                method = call.func.attr
                if method in ("query", "add") and call.args:
                    argument = call.args[0]
                    if method == "add" and isinstance(argument, ast.Call):
                        argument = argument.func
                    if isinstance(argument, ast.Name):
                        target = resolve_name(path, argument.id, blocked)
                        if target in classes and model_id(target[0], classes[target]) in nodes:
                            edge(here, model_id(target[0], classes[target]),
                                 "orm_model_use_candidate", path, call.lineno)
                        else:
                            abstain(path, call.lineno, "orm_receiver_or_model_unresolved")
                if method in ("publish", "emit", "send") and call.args:
                    topic = _string(call.args[0])
                    if topic and len(topic) <= 120:
                        channel = resource("topic", topic, path, call.lineno)
                        edge(here, channel, "event_publish_candidate", path, call.lineno)
                    else:
                        abstain(path, call.lineno, "dynamic_event_topic")
            # SQLAlchemy select(User) with an imported or in-file model.
            if isinstance(call.func, ast.Name) and call.func.id == "select" and call.args:
                candidate = call.args[0]
                if isinstance(candidate, ast.Name):
                    target = resolve_name(path, candidate.id, blocked)
                    if target in classes and model_id(target[0], classes[target]) in nodes:
                        edge(here, model_id(target[0], classes[target]),
                             "orm_model_select_candidate", path, call.lineno)
    # Alembic declaration candidates: never equate a create_table call with
    # a deployed schema or a successful migration.
    for path, tree in sorted(trees.items()):
        op_names = _alembic_op(tree)
        if not op_names:
            continue
        for (owner, name), fn in sorted(functions.items()):
            if owner != path or name != "upgrade":
                continue
            for call in _calls(fn):
                if (not isinstance(call.func, ast.Attribute) or
                        call.func.attr != "create_table" or
                        not isinstance(call.func.value, ast.Name) or
                        call.func.value.id not in op_names):
                    continue
                table = _string(call.args[0]) if call.args else None
                if table and len(table) <= 120:
                    migration = node("migration", path, fn.lineno, "upgrade")
                    target = resource("table", table, path, call.lineno)
                    edge(migration, target, "migration_create_table_candidate",
                         path, call.lineno)
                else:
                    abstain(path, call.lineno, "dynamic_migration_table")

    # Topic subscriptions produce an explicit topic -> subscribed function edge.
    for (path, _name), fn in sorted(functions.items()):
        for deco in fn.decorator_list:
            if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ("subscribe", "consumer") and len(deco.args) == 1):
                topic = _string(deco.args[0])
                if topic and len(topic) <= 120:
                    channel = resource("topic", topic, path, deco.lineno)
                    edge(channel, function_id(path, fn), "event_subscriber_candidate", path, deco.lineno)
                else:
                    abstain(path, deco.lineno, "dynamic_subscription_topic")
    # Match only a unique literal method/path; ambiguity must abstain.
    for path, source in sorted(sources.items()):
        if Path(path).suffix not in _JS_SUFFIX:
            continue
        calls, missing = extract_http_calls(path, source)
        abstentions.extend(missing[:max(0, MAX_ABSTENTIONS - len(abstentions))])
        for call in calls:
            client = node("http_client", path, call["line"],
                          f'{call["method"]} {call["url"]}')
            matches = routes.get((call["method"], call["url"]), [])
            if len(matches) == 1:
                edge(client, matches[0], "literal_http_route_candidate",
                     path, call["line"])
            else:
                abstain(path, call["line"],
                        "unmatched_http_route" if not matches else "ambiguous_http_route")

    if not verify_worktree(root, state)["verified"]:
        return _blank(state, "stale", ["Worktree changed during cross-layer analysis"])
    output = _blank(state, "partial" if warnings else "complete", warnings)
    output["nodes"] = [nodes[k] for k in sorted(nodes)]
    output["edges"] = [edges[k] for k in sorted(edges)]
    output["abstentions"] = sorted(abstentions, key=lambda a: (a["path"], a["line"], a["reason"]))
    output["coverage"] = {
        "python_files_parsed": len(trees),
        "js_ts_files_scanned": sum(Path(p).suffix in _JS_SUFFIX for p in sources),
        "candidate_edges": len(edges),
        "unresolved_or_unsupported_candidates": len(abstentions),
        "note": "Complete means supported scan completed, not complete repository understanding.",
    }
    return output


def cross_layer_impact(graph: dict, changed: list[str], depth: int = 4) -> dict:
    if not isinstance(graph, dict) or graph.get("format") != FORMAT:
        raise CrossLayerError("Unsupported cross-layer graph")
    if type(depth) is not int or not 1 <= depth <= MAX_HOPS:
        raise CrossLayerError("Impact depth must be between 1 and 6")
    if not isinstance(changed, list) or len(changed) > 50 or any(
        not isinstance(p, str) or not _safe_path(p) for p in changed
    ):
        raise CrossLayerError("Changed files must be bounded safe paths")
    nodes = {n["id"]: n for n in graph["nodes"]}
    roots = {n["id"] for n in graph["nodes"] if n["source"]["path"] in changed
             and n["kind"] in ("function", "model", "dto", "migration", "http_route", "http_client")}
    forward, reverse = defaultdict(list), defaultdict(list)
    for e in graph["edges"]:
        forward[e["source"]].append(e["target"])
        reverse[e["target"]].append(e["source"])
    def walk(adjacency):
        seen = set(roots)
        queue = deque((x, [x]) for x in sorted(roots))
        result = []
        while queue and len(result) < MAX_RESULTS:
            current, via = queue.popleft()
            if len(via) > depth:
                continue
            for next_id in sorted(set(adjacency[current])):
                if next_id in seen:
                    continue
                seen.add(next_id)
                route = via + [next_id]
                result.append({"id": next_id, "kind": nodes[next_id]["kind"],
                               "path": nodes[next_id]["source"]["path"],
                               "distance": len(route)-1, "via": route})
                queue.append((next_id, route))
                if len(result) >= MAX_RESULTS:
                    break
        return result, bool(queue)
    known = {n["source"]["path"] for n in graph["nodes"]}
    inbound, inbound_truncated = walk(reverse)
    outbound, outbound_truncated = walk(forward)
    return {
        "changed": sorted(set(changed)),
        "unindexed_changed": sorted(set(changed) - known),
        "inbound_dependents": inbound,
        "outbound_dependencies": outbound,
        "max_depth": depth,
        "classification": "source-backed_static_candidate_only",
        "truncated": inbound_truncated or outbound_truncated or len(graph["abstentions"]) >= MAX_ABSTENTIONS,
        "interpretation": "Candidate impact chains, not confirmed executed paths or defects.",
    }
