"""R8.01 — bounded, permissioned read-only engineering investigation tools.

Seven typed tool contracts. Every tool executes over one R7.01 source snapshot,
never executes project source, and carries untrusted-source provenance.
The dispatcher is intentionally independent from LLM agents or GitHub posting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable

from .compiled_semantic import index_compiled
from .context_engine import LANGUAGES, retrieve_context
from .contracts import _json_schema, METHODS
from .py_semantic import index_python
from .semantic_contracts import (
    SemanticContractError, _safe_path, bound_span, capture_worktree,
    validate_snapshot, verify_worktree,
)
from .ts_semantic import index_typescript

FORMAT = "daddy-reviews-investigation-v1"
TOOLS = frozenset({
    "read_file", "find_symbol", "find_references", "query_dependencies",
    "inspect_contract", "find_tests", "inspect_history",
})
MAX_CALLS = 12
MAX_BYTES = 128_000
MAX_PER_CALL = 32_000
MAX_READ_LINES = 100
MAX_HISTORY = 12
MAX_DEPTH = 4
MAX_REFERENCES = 40
SYMBOL = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?$", re.ASCII)
TEST_FILE = re.compile(r"(?:^|/)(?:tests?/|test_[^/]+\.py$|[^/]+\.(?:test|spec)\.[cm]?[jt]sx?$)")


class InvestigationError(ValueError):
    """Invalid tool request, not an assertion of any code issue."""


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    path: str
    symbol: str | None = None
    route: str | None = None
    method: str | None = None
    start_line: int = 1
    end_line: int = 40
    limit: int = 8
    depth: int = 3

    def __post_init__(self):
        if self.tool not in TOOLS or not _safe_path(self.path):
            raise InvestigationError("Unknown tool or unsafe source path")
        if type(self.start_line) is not int or type(self.end_line) is not int or (
                not 1 <= self.start_line <= self.end_line or
                self.end_line - self.start_line + 1 > MAX_READ_LINES):
            raise InvestigationError("Line selection must be 1–100 lines")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_REFERENCES:
            raise InvestigationError("Result limit must be 1–40")
        if type(self.depth) is not int or not 1 <= self.depth <= MAX_DEPTH:
            raise InvestigationError("Dependency depth must be 1–4")
        if self.tool in ("find_symbol", "find_references"):
            if not isinstance(self.symbol, str) or not SYMBOL.fullmatch(self.symbol):
                raise InvestigationError("Symbol tool needs a valid Symbol or Class.method")
        if self.tool == "inspect_contract":
            if (not isinstance(self.route, str) or not 1 <= len(self.route) <= 300
                    or not self.route.startswith("/") or self.route.startswith("//")
                    or self.method not in {m.upper() for m in METHODS}):
                raise InvestigationError("Contract inspection requires a literal route and HTTP method")


def _reply(tool, status, snapshot, data=None, evidence=None, warnings=None):
    return {
        "format": FORMAT, "tool": tool, "status": status,
        "snapshot_id": snapshot["snapshot_id"],
        "data": data if data is not None else {},
        "evidence": evidence or [],
        "warnings": warnings or [],
        "trust": "untrusted_repository_source",
        "runtime_calls_proven": False,
    }


def _read_source(root, snapshot, path):
    """Return exact captured bytes only; symlinks, traversal and drift abstain."""
    by_path = {f["path"]: f for f in snapshot["files"]}
    entry = by_path.get(path)
    if entry is None:
        return None, None
    file = root / path
    if file.is_symlink():
        raise InvestigationError("Source symlink appeared after capture")
    try:
        resolved = file.resolve(strict=True)
        resolved.relative_to(root)
        data = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise InvestigationError("Source is inaccessible or left the worktree") from exc
    if len(data) != entry["size_bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise InvestigationError("Source bytes changed since snapshot")
    try:
        return data.decode("utf-8"), entry
    except UnicodeError as exc:
        raise InvestigationError("Only UTF-8 source can be inspected") from exc


def _span(snapshot, path, line):
    return asdict(bound_span(snapshot, path, line, line, "manual", "candidate"))


def _read_file(root, snapshot, req):
    source, entry = _read_source(root, snapshot, req.path)
    if entry is None:
        return _reply(req.tool, "not_found", snapshot, warnings=["File absent from captured source inventory"])
    if req.start_line > entry["line_count"]:
        return _reply(req.tool, "not_found", snapshot, warnings=["Starting line outside captured source"])
    lines = source.split("\n")
    if source.endswith("\n"):
        lines.pop()
    end = min(req.end_line, len(lines))
    snippet = "\n".join(
        f"{line}: {lines[line - 1]}" for line in range(req.start_line, end + 1)
    )
    # A long minified line cannot be returned as complete evidence.
    if len(snippet.encode("utf-8")) > 12_000:
        return _reply(req.tool, "partial", snapshot,
                      {"path": req.path, "requested_lines": [req.start_line, end]},
                      [_span(snapshot, req.path, req.start_line)],
                      ["Source selection exceeds safe excerpt budget; narrow the range"])
    return _reply(req.tool, "complete", snapshot,
                  {"path": req.path, "start_line": req.start_line,
                   "end_line": end, "text": snippet},
                  [asdict(bound_span(snapshot, req.path, req.start_line, end,
                                     "manual", "candidate"))])


def _semantic(root, snapshot, req):
    language = LANGUAGES.get(Path(req.path).suffix.lower())
    if not language:
        return None
    if language == "python":
        return index_python(root, req.path, req.symbol, snapshot=snapshot)
    if language == "typescript":
        return index_typescript(root, req.path, req.symbol, snapshot=snapshot)
    return index_compiled(root, language, req.path, req.symbol, snapshot=snapshot)


def _symbols(root, snapshot, req):
    language = LANGUAGES.get(Path(req.path).suffix.lower())
    result = _semantic(root, snapshot, req)
    if result is None:
        return _reply(req.tool, "unavailable", snapshot,
                      warnings=["No semantic adapter for source extension"])
    state = result.get("status")
    if state not in ("complete", "partial"):
        return _reply(req.tool, "not_found" if state == "unresolved" else "partial",
                      snapshot,
                      {"adapter_status": state, "adapter_version": result.get("compiler_version")},
                      warnings=result.get("warnings", []) or ["Symbol could not be resolved"])
    definition = result.get("definition")
    if definition is None:
        return _reply(req.tool, "partial", snapshot, warnings=["No grounded declaration"])
    if req.tool == "find_symbol":
        return _reply(req.tool, "complete" if state == "complete" else "partial",
                      snapshot, {"symbol": req.symbol, "definition": definition,
                                 "language": language, "adapter_status": state,
                                 "compiler_version": result.get("compiler_version")},
                      [definition], result.get("warnings", []))
    references = result.get("references", [])
    selected = references[:req.limit]
    warnings = list(result.get("warnings", []))
    if len(references) > req.limit:
        warnings.append("Reference result ceiling reached")
    return _reply(req.tool, "complete" if state == "complete" and not warnings else "partial",
                  snapshot, {"symbol": req.symbol, "definition": definition,
                             "language": language, "adapter_status": state,
                             "references": selected, "total_references": len(references),
                             "truncated": len(references) > req.limit},
                  [definition] + [r["location"] for r in selected], warnings)


def _graph(root, snapshot, req):
    context = retrieve_context(root, [req.path], snapshot=snapshot, max_items=24)
    state = context["status"]
    if state not in ("complete", "partial"):
        return _reply(req.tool, "partial", snapshot,
                      {"context_status": state}, warnings=context.get("warnings", []))
    graph_edges = context["graph_edges"]
    # Separate directed adjacency so callers are not confused with callees.
    incoming, outgoing = {}, {}
    for e in graph_edges:
        incoming.setdefault(e["target"], []).append(e)
        outgoing.setdefault(e["source"], []).append(e)

    def walk(index, neighbor):
        queue = [(req.path, 0)]
        visited = {req.path}
        hits = []
        while queue and len(hits) < req.limit:
            current, depth = queue.pop(0)
            if depth >= req.depth:
                continue
            for edge in sorted(index.get(current, []),
                               key=lambda e: (e["source"], e["target"], e["relationship"])):
                next_path = edge[neighbor]
                if next_path in visited:
                    continue
                visited.add(next_path)
                queue.append((next_path, depth + 1))
                hits.append({"path": next_path, "distance": depth + 1,
                             "relationship": edge["relationship"],
                             "evidence": edge["evidence"],
                             "certainty": edge["certainty"]})
                if len(hits) >= req.limit:
                    break
        return hits, bool(queue)
    upstream, upstream_limited = walk(incoming, "source")
    downstream, downstream_limited = walk(outgoing, "target")
    warnings = list(context.get("warnings", []))
    if upstream_limited or downstream_limited or context["coverage"]["total_candidate_edges"] > len(graph_edges):
        warnings.append("Dependency exploration is bounded; additional edges may exist")
    return _reply(req.tool, "complete" if not warnings and state == "complete" else "partial",
                  snapshot, {"upstream": upstream, "downstream": downstream,
                             "source_kind": "static_candidate",
                             "graph_edge_total": context["coverage"]["total_candidate_edges"]},
                  [item["evidence"] for item in upstream + downstream], warnings)


def _tests(root, snapshot, req):
    # Use only actually connected source-import/call edges. Do not invent
    # tests solely from filenames that resemble the changed target.
    ctx = retrieve_context(root, [req.path], snapshot=snapshot, max_items=24)
    if ctx["status"] not in ("complete", "partial"):
        return _reply(req.tool, "partial", snapshot, warnings=ctx.get("warnings", []))
    reverse = {}
    for edge in ctx["graph_edges"]:
        reverse.setdefault(edge["target"], []).append(edge)
    queue = [(req.path, 0)]
    seen = {req.path}
    tests = []
    while queue and len(tests) < req.limit:
        path, depth = queue.pop(0)
        if depth >= req.depth:
            continue
        for edge in sorted(reverse.get(path, []),
                           key=lambda e: (e["source"], e["relationship"])):
            p = edge["source"]
            if p in seen:
                continue
            seen.add(p)
            if TEST_FILE.search(p):
                tests.append({"path": p, "distance": depth + 1,
                              "reason": "source_linked_candidate",
                              "evidence": edge["evidence"]})
                if len(tests) >= req.limit:
                    break
            else:
                queue.append((p, depth + 1))
    warnings = list(ctx.get("warnings", []))
    if len(tests) >= req.limit:
        warnings.append("Test candidate result limit reached; further tests may exist")
    if ctx["coverage"]["total_candidate_edges"] > len(ctx["graph_edges"]):
        warnings.append("Graph-edge display budget limits test discovery")
    return _reply(req.tool, "complete" if not warnings else "partial",
                  snapshot, {"tests": tests, "exhaustive": False,
                             "note": "No discovered tests is not proof of missing tests."},
                  [t["evidence"] for t in tests], warnings)


def _schema_summary(value):
    if not isinstance(value, dict):
        return {"status": "unknown"}
    props = value.get("properties", {})
    required = value.get("required", [])
    if not isinstance(props, dict) or not isinstance(required, list):
        return {"status": "unsupported"}
    items = []
    for name, spec in sorted(props.items())[:20]:
        if not isinstance(name, str) or not isinstance(spec, dict):
            return {"status": "unsupported"}
        items.append({"name": name[:120], "type": str(spec.get("type", "unknown"))[:40],
                      "required": name in required})
    return {"status": "summarized" if len(props) <= 20 else "truncated",
            "fields": items, "total_fields": len(props)}


def _contract(root, snapshot, req):
    text, entry = _read_source(root, snapshot, req.path)
    if entry is None:
        return _reply(req.tool, "not_found", snapshot,
                      warnings=["OpenAPI JSON is not in the captured source manifest"])
    if Path(req.path).name not in {"openapi.json", "openapi-v3.json", "swagger.json"}:
        return _reply(req.tool, "unavailable", snapshot,
                      warnings=["Only conventional OpenAPI JSON artifact names are supported"])
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return _reply(req.tool, "partial", snapshot, warnings=["Malformed OpenAPI JSON"])
    if (not isinstance(document, dict) or
            not str(document.get("openapi", "")).startswith("3.") or
            not isinstance(document.get("paths"), dict)):
        return _reply(req.tool, "partial", snapshot, warnings=["Expected OpenAPI 3.x JSON paths"])
    operation = document["paths"].get(req.route)
    operation = operation.get(req.method.lower()) if isinstance(operation, dict) else None
    if not isinstance(operation, dict):
        return _reply(req.tool, "not_found", snapshot,
                      {"path": req.path, "method": req.method, "route": req.route},
                      warnings=["Requested literal route/method not declared"])
    response = _json_schema(document, operation, "response")
    request = _json_schema(document, operation, "request")
    if not isinstance(response, dict) and not isinstance(request, dict):
        status = "partial"
        warnings = ["No supported JSON request or response schema found"]
    else:
        status, warnings = "complete", []
    rsp = _schema_summary(response)
    reqs = _schema_summary(request)
    if "truncated" in (rsp["status"], reqs["status"]):
        status = "partial"
        warnings.append("Contract field budget exceeded")
    data = {
        "route": req.route, "method": req.method, "path": req.path,
        "operation_id": str(operation.get("operationId", ""))[:140],
        "request": reqs, "response": rsp,
        "declared_response_statuses": sorted(
            str(k)[:20] for k in operation.get("responses", {})
        )[:20] if isinstance(operation.get("responses"), dict) else [],
        "interpretation": "Declared OpenAPI schema only; not a deployed API guarantee",
    }
    return _reply(req.tool, status, snapshot, data,
                  [_span(snapshot, req.path, 1)], warnings)


def _history(root, snapshot, req):
    _, entry = _read_source(root, snapshot, req.path)
    if entry is None:
        return _reply(req.tool, "not_found", snapshot,
                      warnings=["File absent from working-tree snapshot"])
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    })
    prefix = ["git", "--literal-pathspecs", "-C", str(root),
              "-c", "core.fsmonitor=false"]
    def run(command):
        try:
            proc = subprocess.run(prefix + command, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=5, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode or len(proc.stdout.encode("utf-8")) > 24_000:
            return None
        return proc.stdout.strip()
    top = run(["rev-parse", "--show-toplevel"])
    if top is None or Path(top).resolve() != root:
        return _reply(req.tool, "unavailable", snapshot,
                      warnings=["Git history not available for this exact repository root"])
    head = run(["rev-parse", "HEAD"])
    if not head or not re.fullmatch(r"[a-f0-9]{40,64}", head):
        return _reply(req.tool, "unavailable", snapshot, warnings=["HEAD is unavailable"])
    history = run(["log", "--no-show-signature", "--date=iso-strict",
                   "--format=%H%x09%aI%x09%s", f"--max-count={min(req.limit, MAX_HISTORY)}",
                   "HEAD", "--", req.path])
    if history is None:
        return _reply(req.tool, "unavailable", snapshot,
                      warnings=["Git history command failed or exceeded budget"])
    if run(["rev-parse", "HEAD"]) != head:
        return _reply(req.tool, "partial", snapshot,
                      warnings=["Git HEAD changed while reading history; results withheld"])
    records = []
    for line in history.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and re.fullmatch(r"[a-f0-9]{40,64}", parts[0]):
            records.append({"sha": parts[0], "authored_at": parts[1][:40],
                            "subject": parts[2][:300], "trust": "untrusted_git_metadata"})
    return _reply(req.tool, "complete", snapshot,
                  {"path": req.path, "repository_head": head,
                   "commits": records, "limit": min(req.limit, MAX_HISTORY),
                   "note": "Commit history is metadata, not evidence of runtime behavior"},
                  [_span(snapshot, req.path, 1)] if entry["line_count"] else [])


_HANDLERS: dict[str, Callable] = {
    "read_file": _read_file,
    "find_symbol": _symbols,
    "find_references": _symbols,
    "query_dependencies": _graph,
    "inspect_contract": _contract,
    "find_tests": _tests,
    "inspect_history": _history,
}


class InvestigationSession:
    """Explicit capability allowlist, bounded calls/output and one snapshot."""

    def __init__(self, root: Path, allowed_tools, snapshot: dict | None = None,
                 max_calls: int = MAX_CALLS, max_bytes: int = MAX_BYTES):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise InvestigationError("Repository root must be a directory")
        allowed = set(allowed_tools)
        if not allowed <= TOOLS:
            raise InvestigationError("Unknown investigation tool permission")
        if (type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS or
                type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES):
            raise InvestigationError("Invalid investigation budgets")
        self.allowed = frozenset(allowed)
        self.snapshot = (capture_worktree(self.root) if snapshot is None
                         else validate_snapshot(snapshot))
        self.max_calls = max_calls
        self.max_bytes = max_bytes
        self.calls = 0
        self.bytes_returned = 0

    def execute(self, request: ToolRequest) -> dict:
        if not isinstance(request, ToolRequest):
            raise InvestigationError("Typed ToolRequest is required")
        if request.tool not in self.allowed:
            return _reply(request.tool, "denied", self.snapshot,
                          warnings=["Tool is not in session capability allowlist"])
        if self.calls >= self.max_calls:
            return _reply(request.tool, "budget_exceeded", self.snapshot,
                          warnings=["Investigation call budget exhausted"])
        self.calls += 1
        if not self.snapshot["complete"]:
            return _reply(request.tool, "incomplete", self.snapshot,
                          warnings=["Source manifest is incomplete"])
        if not verify_worktree(self.root, self.snapshot)["verified"]:
            return _reply(request.tool, "stale", self.snapshot,
                          warnings=["Captured worktree is no longer current"])
        try:
            result = _HANDLERS[request.tool](self.root, self.snapshot, request)
        except (InvestigationError, SemanticContractError, OSError, ValueError,
                RecursionError, KeyError, TypeError) as exc:
            result = _reply(request.tool, "partial", self.snapshot,
                            warnings=["Investigation could not validate requested evidence"])
        if not verify_worktree(self.root, self.snapshot)["verified"]:
            return _reply(request.tool, "stale", self.snapshot,
                          warnings=["Worktree changed during tool execution; result withheld"])
        result["budget"] = {"calls_used": self.calls, "calls_limit": self.max_calls,
                            "response_bytes_used": 0,
                            "response_bytes_limit": self.max_bytes}
        # Account for the budget metadata itself (including decimal digit width)
        # rather than undercounting every response by its bookkeeping fields.
        length = 0
        for _ in range(6):
            length = len(json.dumps(result, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8"))
            total = self.bytes_returned + length
            if result["budget"]["response_bytes_used"] == total:
                break
            result["budget"]["response_bytes_used"] = total
        length = len(json.dumps(result, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8"))
        if length > MAX_PER_CALL or self.bytes_returned + length > self.max_bytes:
            return _reply(request.tool, "budget_exceeded", self.snapshot,
                          warnings=["Investigation response budget exceeded; no truncated evidence returned"])
        self.bytes_returned += length
        return result
