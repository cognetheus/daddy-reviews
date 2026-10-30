"""R7.04 compiler adapters for Java (JDK javac) and C# (SDK Roslyn).

Separate, opt-in subprocesses inspect only hash-verified, bounded source
snapshots staged in a temporary folder. No reviewed build scripts, project
hooks, source compilation output, NuGet restore or annotation processors.
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
from tempfile import TemporaryDirectory

from .semantic_contracts import (
    SemanticContractError, SemanticReference, SemanticSymbol, _safe_path,
    bound_span, capture_worktree, context_bundle, validate_snapshot, verify_worktree,
)

FORMAT = "daddy-reviews-compiled-semantic-v1"
MAX_FILES = 800
MAX_SOURCE_BYTES = 5_000_000
MAX_OUTPUT_BYTES = 512_000
JAVA_HELPER = Path(__file__).resolve().parents[2] / "tooling/java/JavaSymbolIndex.java"
CS_HELPER = (Path(__file__).resolve().parents[2] /
             "tooling/dotnet/bin/Release/net8.0/DaddySemanticIndexer.dll")
SYMBOL = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?$")


class CompiledSemanticError(ValueError):
    pass


def _result(language, status, snapshot, warning="", version=None):
    return {
        "format": FORMAT,
        "language": language, "status": status,
        "snapshot_id": snapshot["snapshot_id"],
        "compiler_version": version,
        "definition": None, "references": [],
        "context_bundle": None,
        "warnings": [warning] if warning else [],
        "runtime_calls_proven": False,
        "limitations": [
            "Static compiler symbol identity does not establish runtime reachability.",
            "Standalone snapshot compilation omits full Maven/Gradle/MSBuild project context.",
            "Unresolved dependencies and compiler errors cause partial coverage, not clean approval.",
        ],
    }


def index_compiled(root: Path, language: str, changed_path: str, symbol: str,
                   snapshot: dict | None = None, timeout: float = 30) -> dict:
    """Resolve a class or Class.method via actual JDK/Roslyn symbol identity."""
    if language not in ("java", "csharp"):
        raise CompiledSemanticError("Language must be java or csharp")
    extension = ".java" if language == "java" else ".cs"
    if (not isinstance(changed_path, str) or not _safe_path(changed_path)
            or not changed_path.endswith(extension)
            or not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol)
            or type(timeout) not in (int, float) or not 1 <= timeout <= 120):
        raise CompiledSemanticError("Expected source path, Class or Class.method, and valid timeout")
    root = root.resolve()
    if not root.is_dir():
        raise CompiledSemanticError("Root must be a directory")
    state = capture_worktree(root) if snapshot is None else validate_snapshot(snapshot)
    if not state["complete"]:
        return _result(language, "incomplete", state, "Source snapshot is incomplete")
    if not verify_worktree(root, state)["verified"]:
        return _result(language, "stale", state, "Source snapshot is stale")
    sources = [e for e in state["files"] if e["path"].endswith(extension)]
    if changed_path not in {e["path"] for e in sources}:
        return _result(language, "unresolved", state, "Target absent from captured sources")
    if (len(sources) > MAX_FILES or
            sum(e["size_bytes"] for e in sources) > MAX_SOURCE_BYTES):
        return _result(language, "incomplete", state, "Compiler indexing budget exceeded")
    if language == "java":
        if shutil.which("java") is None or not JAVA_HELPER.is_file():
            return _result(language, "unavailable", state, "JDK 17+ or trusted Java helper missing")
        try:
            info = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=5)
            detected = re.search(r'version "(\d+)', info.stderr)
            if not detected or int(detected.group(1)) < 17:
                return _result(language, "unavailable", state, "JDK 17+ is required")
        except (OSError, subprocess.TimeoutExpired):
            return _result(language, "unavailable", state, "Cannot verify Java version")
    else:
        if shutil.which("dotnet") is None or not CS_HELPER.is_file():
            return _result(language, "unavailable", state,
                           "Built .NET 8 Roslyn helper is required; see tooling/dotnet")
    with TemporaryDirectory(prefix="daddy-reviews-semantic-") as temporary:
        stage = Path(temporary).resolve()
        for entry in sources:
            rel = entry["path"]
            target = root / rel
            if target.is_symlink():
                return _result(language, "stale", state, "Source symlink changed")
            try:
                resolved = target.resolve(strict=True)
                resolved.relative_to(root)
                data = target.read_bytes()
                if (len(data) != entry["size_bytes"] or
                        hashlib.sha256(data).hexdigest() != entry["sha256"]):
                    return _result(language, "stale", state, "Source content changed")
                # Never pass project scripts or runtime imports to subprocess.
                data.decode("utf-8")
            except (OSError, ValueError, UnicodeError):
                return _result(language, "stale", state, "Untrusted or missing source bytes")
            destination = stage / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        paths = [e["path"] for e in sources]
        if language == "java":
            argv = ["java", "--source", "17", str(JAVA_HELPER),
                    str(stage), changed_path, symbol, *paths]
        else:
            argv = ["dotnet", str(CS_HELPER),
                    str(stage), changed_path, symbol, *paths]
        try:
            run = subprocess.run(argv, cwd=stage, capture_output=True, text=True,
                                 encoding="utf-8", timeout=timeout, check=False)
        except (OSError, UnicodeError, subprocess.TimeoutExpired):
            return _result(language, "incomplete", state, "Compiler timed out or failed")
        if run.returncode != 0 or len(run.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
            return _result(language, "incomplete", state, "Compiler error or output budget exceeded")
        try:
            reply = json.loads(run.stdout)
        except ValueError:
            return _result(language, "incomplete", state, "Compiler returned invalid JSON")
    if not verify_worktree(root, state)["verified"]:
        return _result(language, "stale", state, "Worktree changed during compiler analysis")
    expected = "daddy-reviews-javac-v1" if language == "java" else "daddy-reviews-roslyn-v1"
    if (not isinstance(reply, dict) or reply.get("format") != expected
            or reply.get("status") not in {"complete", "partial", "ambiguous", "unresolved",
                                           "invalid", "incomplete", "unavailable"}
            or not isinstance(reply.get("compiler_version"), str)):
        return _result(language, "incomplete", state, "Compiler output contract mismatch")
    result = _result(language, reply["status"], state,
                     version=reply["compiler_version"])
    raw_warnings = reply.get("warnings")
    if (not isinstance(raw_warnings, list) or len(raw_warnings) > 30
            or any(not isinstance(x, str) or len(x)>300 for x in raw_warnings)):
        return _result(language, "incomplete", state, "Untrusted compiler warnings")
    result["warnings"] = raw_warnings
    if reply["status"] not in {"complete", "partial"}:
        return result
    definition, references = reply.get("definition"), reply.get("references")
    if (not isinstance(definition, dict) or not isinstance(references, list)
            or len(references) > 500):
        return _result(language, "incomplete", state, "Invalid compiler references")
    try:
        if (set(definition) != {"path", "line"} or
                definition["path"] != changed_path):
            raise SemanticContractError("Target definition outside requested file")
        origin = bound_span(state, definition["path"], definition["line"],
                            definition["line"], "compiler", "resolved")
        resolved = []
        allowed = {"method_call", "constructor_call", "type_reference"}
        for ref in references:
            if (not isinstance(ref, dict) or set(ref) != {"path", "line", "relationship"}
                    or ref["relationship"] not in allowed):
                raise SemanticContractError("Invalid reference type")
            span = bound_span(state, ref["path"], ref["line"], ref["line"],
                              "compiler", "resolved")
            if span.path == changed_path:
                raise SemanticContractError("Unexpected same-source reference")
            resolved.append(SemanticReference(symbol, ref["relationship"], span, origin))
        bundle = context_bundle(state, [SemanticSymbol(symbol, "compiled_declaration", origin)],
                                resolved, [])
    except (SemanticContractError, ValueError, TypeError, KeyError):
        return _result(language, "incomplete", state, "Ungrounded compiler source location")
    result["definition"] = asdict(origin)
    result["references"] = [asdict(x) for x in resolved]
    result["context_bundle"] = bundle
    return result
