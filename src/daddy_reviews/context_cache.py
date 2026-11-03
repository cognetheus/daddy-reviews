"""R7.06: snapshot-validated local graph cache, never a source-code cache.

On exact source hash hit, reusable module/cross-layer graphs are read from a
bounded, validated local cache. On a changed source/config the complete graph
is rebuilt, and affected old dependents are conservatively invalidated.

The cache contains graph metadata, file hashes and relative paths, not source
snippets, model prompts, file bytes, or Git credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .semantic_contracts import (
    SemanticContractError, validate_snapshot, _safe_path,
)

FORMAT = "daddy-reviews-context-cache-v1"
MAX_CACHE_BYTES = 12_000_000
MAX_NODES = 4_000
MAX_EDGES = 7_000
_SHA = set("0123456789abcdef")


class ContextCacheError(ValueError):
    pass


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in _SHA for c in value)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _path(cache_file: Path) -> Path:
    path = cache_file.absolute()
    if path.suffix != ".json" or path.name in {"tsconfig.json", "jsconfig.json", "package.json"}:
        raise ContextCacheError("Context cache must be a dedicated .json path")
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise ContextCacheError("Cache must be in an existing, non-symlinked directory")
    return path


def _check_span(span, manifest):
    if not isinstance(span, dict) or set(span) != {
        "snapshot_id", "path", "source_sha256", "start_line", "end_line",
        "origin", "certainty",
    }:
        return False
    if (span["snapshot_id"] != manifest["snapshot_id"] or
            not _safe_path(span["path"])):
        return False
    entry = next((f for f in manifest["files"] if f["path"] == span["path"]), None)
    return bool(entry and span["source_sha256"] == entry["sha256"] and
                type(span["start_line"]) is int and type(span["end_line"]) is int and
                1 <= span["start_line"] <= span["end_line"] <= entry["line_count"] and
                span["certainty"] in ("resolved", "candidate", "unknown") and
                span["origin"] in ("compiler", "language_server", "ast", "lexical",
                                  "manual", "test", "runtime"))


def _validate_graphs(payload):
    snapshot = validate_snapshot(payload["snapshot"])
    if not snapshot["complete"]:
        raise ContextCacheError("Incomplete manifest cannot be cached")
    cross, module = payload["cross"], payload["module"]
    if (not isinstance(cross, dict) or cross.get("format") != "daddy-reviews-cross-layer-v1"
            or cross.get("snapshot_id") != snapshot["snapshot_id"]
            or cross.get("status") != "complete"
            or not isinstance(cross.get("nodes"), list)
            or not isinstance(cross.get("edges"), list)
            or len(cross["nodes"]) > MAX_NODES or len(cross["edges"]) > MAX_EDGES
            or not isinstance(module, dict)
            or module.get("format") != "daddy-reviews-module-graph-v1"
            or not isinstance(module.get("nodes"), list)
            or not isinstance(module.get("edges"), list)
            or len(module["nodes"]) > MAX_NODES or len(module["edges"]) > MAX_EDGES
            or cross.get("warnings") or module.get("warnings")):
        raise ContextCacheError("Graph cache schema mismatch")
    cross_ids = set()
    for n in cross["nodes"]:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            raise ContextCacheError("Invalid graph node")
        if n["id"] in cross_ids or not _check_span(n.get("source"), snapshot):
            raise ContextCacheError("Graph node provenance mismatch")
        cross_ids.add(n["id"])
    for e in cross["edges"]:
        if (not isinstance(e, dict) or e.get("source") not in cross_ids
                or e.get("target") not in cross_ids or e.get("certainty") != "candidate"
                or not _check_span(e.get("evidence"), snapshot)):
            raise ContextCacheError("Graph edge provenance mismatch")
    index = {f["path"]: f["sha256"] for f in snapshot["files"]}
    module_paths = set()
    for n in module["nodes"]:
        if (not isinstance(n, dict) or not _safe_path(n.get("path")) or
                index.get(n["path"]) != n.get("sha256") or n["path"] in module_paths):
            raise ContextCacheError("Import graph node provenance mismatch")
        module_paths.add(n["path"])
    for e in module["edges"]:
        if (not isinstance(e, dict) or e.get("source") not in module_paths
                or e.get("target") not in module_paths or type(e.get("line")) is not int
                or e["line"] < 1 or e["line"] > next(
                    f["line_count"] for f in snapshot["files"] if f["path"] == e["source"]
                )):
            raise ContextCacheError("Invalid source-backed import edge")
    return snapshot, cross, module


def read_cache(cache_file: Path, root: Path):
    """Read untrusted local cache envelope. Corrupt cache is a miss, not proof."""
    path = _path(cache_file)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(raw, dict) or raw.get("format") != FORMAT
                or raw.get("root") != str(root.resolve())
                or not _sha(raw.get("integrity"))
                or set(raw) != {"format", "root", "snapshot", "cross", "module", "integrity"}):
            return None
        signed = {k: v for k, v in raw.items() if k != "integrity"}
        if _digest(signed) != raw["integrity"]:
            return None
        _validate_graphs(raw)
        return raw
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError,
            SemanticContractError, ContextCacheError):
        return None


def save_cache(cache_file: Path, root: Path, snapshot, cross, module):
    """Atomically write non-secret graph metadata with restricted permissions."""
    path = _path(cache_file)
    unsigned = {"format": FORMAT, "root": str(root.resolve()),
                "snapshot": snapshot, "cross": cross, "module": module}
    _validate_graphs(unsigned)
    payload = {**unsigned, "integrity": _digest(unsigned)}
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_CACHE_BYTES:
        raise ContextCacheError("Graph exceeds safe persistence budget")
    temp = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".daddy-context-", suffix=".tmp", dir=path.parent)
        temp = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ContextCacheError("Cache became a symlink")
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def invalidated_paths(previous, current, module, cross):
    """Conservatively expand changed paths across old import/cross graph edges."""
    old = {f["path"]: f["sha256"] for f in previous["files"]}
    new = {f["path"]: f["sha256"] for f in current["files"]}
    changed = set(old.keys() ^ new.keys())
    changed.update(p for p in old.keys() & new.keys() if old[p] != new[p])
    # Any path/config mutation can alter import or route resolution. Include
    # reverse direct/transitive consumers of both pre-change graph families.
    reverse = {}
    for e in module["edges"]:
        reverse.setdefault(e["target"], set()).add(e["source"])
    nodes = {n["id"]: n for n in cross["nodes"]}
    for e in cross["edges"]:
        src, dst = nodes[e["source"]]["source"]["path"], nodes[e["target"]]["source"]["path"]
        reverse.setdefault(dst, set()).add(src)
    frontier = set(changed)
    impacted = set(changed)
    for _ in range(8):
        upcoming = {owner for p in frontier for owner in reverse.get(p, ())} - impacted
        if not upcoming:
            break
        impacted.update(upcoming)
        frontier = upcoming
    # Resolution may change for unrelated sources if new modules/config paths
    # shadow imports, so a cache miss always rebuilds *all* graph edges.
    return {"changed": sorted(changed), "affected": sorted(impacted),
            "scope": "entire_graph_rebuilt_on_snapshot_change",
            "note": "Affected is a conservative known-dependents set; unknown dynamic consumers are not covered."}
