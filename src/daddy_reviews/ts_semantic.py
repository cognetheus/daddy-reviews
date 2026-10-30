"""Optional R7.02 TypeScript 6 semantic index, bound to R7.01 source hashes.

Runs the pinned TypeScript compiler in a separate, bounded Node process with
only explicitly selected project source bytes supplied on stdin. It does NOT
execute repository code or install dependencies. Compiler-backed is about
symbol *identity*, not runtime reachability or absence of defects.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .semantic_contracts import (
    SemanticContractError, SemanticReference, SemanticSymbol,
    bound_span, capture_worktree, context_bundle, validate_snapshot,
    verify_worktree, _safe_path,
)

TS_VERSION = "6.0.3"
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
MAX_INDEX_FILES = 800
MAX_SOURCE_BYTES = 5_000_000
MAX_OUTPUT_BYTES = 512_000
MAX_REQUEST_BYTES = 7_000_000
JS_SCRIPT = Path(__file__).resolve().parents[2] / "tooling" / "typescript" / "semantic-index.cjs"
TS_INSTALL = JS_SCRIPT.parent / "node_modules" / "typescript" / "package.json"
IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$", re.ASCII)


class TypeScriptSemanticError(ValueError):
    pass


def _result(status: str, reason: str, snapshot: dict | None = None) -> dict:
    return {
        "format": "daddy-reviews-typescript-semantic-v1",
        "status": status,
        "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
        "compiler_version": None,
        "definition": None,
        "references": [],
        "context_bundle": None,
        "warnings": [reason],
        "runtime_calls_proven": False,
    }


def _read_verified(root: Path, entry: dict) -> str:
    name = entry["path"]
    candidate = root / name
    if not _safe_path(name) or candidate.is_symlink():
        raise TypeScriptSemanticError("Unsafe or symlinked snapshot source")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.stat().st_size != entry["size_bytes"]:
            raise TypeScriptSemanticError("Snapshot source changed")
        data = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise TypeScriptSemanticError("Snapshot source is missing or unreadable") from exc
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise TypeScriptSemanticError("Snapshot source content hash changed")
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise TypeScriptSemanticError("Only UTF-8 project source is supported") from exc


def index_typescript(root: Path, changed_path: str, symbol: str,
                     snapshot: dict | None = None, timeout: float = 20) -> dict:
    """Resolve a declared symbol and its call-site references using TypeScript.

    No silent lexical fallback: missing compiler gives 'unavailable', and
    incomplete manifests refuse to report resolved symbol identity.
    """
    root = root.resolve()
    if not root.is_dir() or not _safe_path(changed_path) or (
        Path(changed_path).suffix not in SOURCE_SUFFIXES
    ) or not isinstance(symbol, str) or not IDENTIFIER.fullmatch(symbol):
        raise TypeScriptSemanticError("Need a valid TS/JS source path and symbol name")
    if (type(timeout) not in (int, float) or not 1 <= timeout <= 120):
        raise TypeScriptSemanticError("Compiler timeout must be 1..120 seconds")
    state = capture_worktree(root) if snapshot is None else validate_snapshot(snapshot)
    if not state["complete"]:
        return _result("incomplete", "Source snapshot is incomplete; compiler evidence withheld", state)
    if not verify_worktree(root, state)["verified"]:
        return _result("stale", "Source snapshot does not match the current working tree", state)
    entries = [e for e in state["files"] if Path(e["path"]).suffix in SOURCE_SUFFIXES
               or e["path"] in ("tsconfig.json", "jsconfig.json")]
    code_files = [e for e in entries if Path(e["path"]).suffix in SOURCE_SUFFIXES]
    if not any(e["path"] == changed_path for e in code_files):
        return _result("unresolved", "Target is missing from indexed sources", state)
    if len(code_files) > MAX_INDEX_FILES or sum(e["size_bytes"] for e in entries) > MAX_SOURCE_BYTES:
        return _result("incomplete", "TypeScript indexing file or byte budget exceeded", state)
    if not JS_SCRIPT.is_file() or not TS_INSTALL.is_file() or shutil.which("node") is None:
        return _result("unavailable", "Optional TypeScript 6.0.3/Node indexer is not installed", state)
    try:
        install = json.loads(TS_INSTALL.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return _result("unavailable", "Cannot validate local TypeScript compiler installation", state)
    if install.get("version") != TS_VERSION:
        return _result("unavailable", "TypeScript compiler version mismatch (requires 6.0.3)", state)
    try:
        sources = [{"path": e["path"], "text": _read_verified(root, e)} for e in entries]
    except TypeScriptSemanticError as exc:
        return _result("stale", str(exc), state)
    payload = json.dumps({"root": str(root), "sources": sources,
                          "target": {"path": changed_path, "symbol": symbol}},
                         separators=(",", ":"), ensure_ascii=False)
    if len(payload.encode()) > MAX_REQUEST_BYTES:
        return _result("incomplete", "Compiler request exceeds input budget", state)
    try:
        completed = subprocess.run(
            ["node", str(JS_SCRIPT)], input=payload, text=True, capture_output=True,
            timeout=timeout, cwd=root, check=False,
            env={"PATH": os.environ.get("PATH", ""),
                 "HOME": str(root), "NODE_OPTIONS": ""},
        )
    except (OSError, subprocess.TimeoutExpired):
        return _result("incomplete", "TypeScript compiler timed out or failed to start", state)
    if (completed.returncode or len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES):
        return _result("incomplete", "TypeScript compiler failed or output budget exceeded", state)
    try:
        reply = json.loads(completed.stdout)
    except ValueError:
        return _result("incomplete", "TypeScript compiler output was not JSON", state)
    if (not isinstance(reply, dict) or reply.get("compiler_version") != TS_VERSION or
            reply.get("format") != "daddy-reviews-ts-semantic-v1"):
        return _result("incomplete", "TypeScript compiler output contract or version mismatch", state)
    status = reply.get("status")
    if status not in {"complete", "partial", "unresolved", "ambiguous", "incomplete", "invalid"}:
        return _result("incomplete", "TypeScript compiler returned invalid status", state)
    if not verify_worktree(root, state)["verified"]:
        return _result("stale", "Repository changed during compiler analysis", state)
    answer = _result(status, "", state)
    answer["warnings"] = list(reply.get("warnings", []))[:20]
    answer["compiler_version"] = TS_VERSION
    if status not in {"complete", "partial"}:
        return answer
    definition = reply.get("target", {}).get("definition")
    refs = reply.get("references")
    if (not isinstance(definition, dict) or not isinstance(refs, list) or len(refs) > 500):
        return _result("incomplete", "Malformed compiler symbol or reference output", state)
    try:
        def_span = bound_span(state, definition["path"], definition["line"],
                              definition["line"], "compiler", "resolved")
        if def_span.path != changed_path:
            raise SemanticContractError("Compiler target definition escaped requested path")
        candidates = []
        for r in refs:
            if (not isinstance(r, dict) or
                    r.get("relationship") not in {"direct_call", "constructor_call",
                                                  "member_call", "property_reference"}):
                raise SemanticContractError("Malformed compiler reference")
            source = bound_span(state, r["path"], r["line"], r["line"],
                                "compiler", "resolved")
            candidates.append(SemanticReference(symbol, r["relationship"], source, def_span))
        bundle = context_bundle(state, [SemanticSymbol(symbol, "ts_js_declaration", def_span)],
                                candidates, [])
    except (KeyError, TypeError, ValueError, SemanticContractError):
        return _result("incomplete", "Compiler reported invalid or ungrounded source locations", state)
    answer["definition"] = asdict(def_span)
    answer["references"] = [asdict(r) for r in candidates]
    answer["context_bundle"] = bundle
    answer["runtime_calls_proven"] = False
    return answer
