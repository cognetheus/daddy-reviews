"""R7.06: ranked reviewer-facing context from source-provenanced graph evidence.

The reader supplies one bounded, immutable working-tree manifest; all adapters
must share it. No repository code is executed. Content remains untrusted even
when its provenance is verified. No model or external network calls are made.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict
import hashlib
from pathlib import Path

from .compiled_semantic import index_compiled
from .context_cache import ContextCacheError, read_cache, save_cache, invalidated_paths
from .cross_layer import build_cross_layer
from .graph import build_graph
from .py_semantic import index_python
from .semantic_contracts import (
    ContextExcerpt, SemanticReference, SemanticSymbol, SourceSpan,
    SemanticContractError, _safe_path, capture_worktree, context_bundle,
    validate_snapshot, verify_worktree,
)
from .ts_semantic import index_typescript

FORMAT = "daddy-reviews-ranked-context-v1"
MAX_ITEMS = 24
MAX_WINDOW = 17
MAX_CHANGED = 20
MAX_FUSED_EDGES = 250
MAX_HOPS = 4
MAX_EXCERPT_BYTES = 6000
LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "typescript", ".jsx": "typescript",
    ".mts": "typescript", ".cts": "typescript",
    ".java": "java", ".cs": "csharp",
}


class ContextRetrievalError(ValueError):
    pass


def _abstain(state, status, reason):
    return {"format": FORMAT, "status": status, "snapshot_id": state["snapshot_id"],
            "ranked_context": [], "context_bundle": None, "graph_edges": [],
            "cache": {"status": "bypassed"}, "coverage": {
                "reason": reason, "verified_runtime_calls": False,
                "language_semantic_status": "not_run",
            }, "warnings": [reason],
            "limitations": ["A missing context result does not imply absence of downstream consumers."]}


def _check_module_hashes(module, manifest):
    digests = {f["path"]: f["sha256"] for f in manifest["files"]}
    return all(digests.get(n.get("path")) == n.get("sha256") for n in module["nodes"])


def _fusion_edges(cross, module, semantic):
    """Normalize source-linked edges; never merge distinct certainty levels."""
    c_nodes = {node["id"]: node for node in cross.get("nodes", [])}
    combined = []
    for edge in cross.get("edges", []):
        src, dst = c_nodes.get(edge["source"]), c_nodes.get(edge["target"])
        if src is None or dst is None:
            continue
        combined.append({
            "source": src["source"]["path"], "target": dst["source"]["path"],
            "relationship": edge["relationship"],
            "evidence": edge["evidence"], "origin": "cross_layer",
            "certainty": "candidate",
        })
    for edge in module.get("edges", []):
        combined.append({
            "source": edge["source"], "target": edge["target"],
            "relationship": edge["kind"],
            "evidence": {"path": edge["source"], "line": edge["line"]},
            "origin": "module_import", "certainty": "candidate",
        })
    if semantic and semantic.get("status") in ("complete", "partial"):
        for item in semantic.get("references", []):
            source, target = item["location"], item.get("target_location")
            if target is None:
                target = semantic.get("definition")
            if target is None:
                continue
            combined.append({
                "source": source["path"], "target": target["path"],
                "relationship": item["relationship"],
                "evidence": source, "origin": "semantic_symbol",
                "certainty": source["certainty"],
            })
    return sorted(combined, key=lambda e: (
        e["source"], e["target"], e["relationship"],
        e["evidence"]["path"], e["evidence"].get("start_line", e["evidence"].get("line", 0)),
    ))


def _rank(changed, full_edges, semantic):
    """Deterministic bidirectional shortest paths and explicit evidence anchors."""
    # Retain the highest-confidence anchor and discover tests from actual
    # import/semantic graph connections, not just basename matching.
    scores = {p: 110 for p in changed}
    reasons = defaultdict(set)
    anchors = {}
    for p in changed:
        reasons[p].add("changed_file")
    forward, reverse = defaultdict(list), defaultdict(list)
    for edge in full_edges:
        source, target = edge["source"], edge["target"]
        if source == target:
            continue
        forward[source].append(edge)
        reverse[target].append(edge)
    if semantic and semantic.get("definition"):
        location = semantic["definition"]
        anchors[location["path"]] = (location["start_line"], 999)
    if semantic:
        for ref in semantic.get("references", []):
            point = ref["location"]
            path, line = point["path"], point["start_line"]
            scores[path] = max(scores.get(path, 0), 104)
            anchors[path] = (line, 980)
            reasons[path].add("semantic_reference")
    for adjacency, initial, label in (
        (reverse, 92, "inbound_dependent_candidate"),
        (forward, 83, "outbound_dependency_candidate"),
    ):
        explored = set(changed)
        queue = deque((p, 0) for p in sorted(changed))
        while queue:
            current, depth = queue.popleft()
            if depth >= MAX_HOPS:
                continue
            for edge in sorted(adjacency[current], key=lambda e: (
                e["source"], e["target"], e["relationship"],
            )):
                next_path = (edge["source"] if adjacency is reverse else edge["target"])
                if next_path not in explored:
                    explored.add(next_path)
                    queue.append((next_path, depth + 1))
                if next_path in changed:
                    continue
                score = max(25, initial - depth * 12)
                # A test is relevant only after an actual known edge.
                if "/test" in "/" + next_path or next_path.startswith("test_"):
                    score += 3
                    reasons[next_path].add("test_candidate_via_graph")
                scores[next_path] = max(scores.get(next_path, 0), score)
                reasons[next_path].add(label)
                if edge["evidence"]["path"] == next_path:
                    line = edge["evidence"].get("start_line", edge["evidence"].get("line", 1))
                    if anchors.get(next_path, (0, 0))[1] < score:
                        anchors[next_path] = (line, score)
    return scores, reasons, anchors


def _excerpt(root, manifest, path, line, before_after):
    """Verify file bytes and generate a line-numbered, bounded context excerpt."""
    indexed = {f["path"]: f for f in manifest["files"]}
    entry = indexed.get(path)
    if entry is None:
        raise ContextRetrievalError("Context source absent from verified snapshot")
    file = root / path
    if file.is_symlink():
        raise ContextRetrievalError("Symlink appeared in source context")
    try:
        resolved = file.resolve(strict=True)
        resolved.relative_to(root)
        raw = resolved.read_bytes()
        if len(raw) != entry["size_bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ContextRetrievalError("Source bytes changed during context retrieval")
        decoded = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContextRetrievalError("Source context is stale or not UTF-8") from exc
    lines = decoded.splitlines()
    if not lines:
        return None
    line = max(1, min(line, len(lines)))
    start = max(1, line - before_after)
    end = min(len(lines), line + before_after)
    text = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
    # Do not silently report a full excerpt when it was actually clipped.
    if len(text.encode("utf-8")) > MAX_EXCERPT_BYTES:
        text = text[:MAX_EXCERPT_BYTES // 2] + "\n[excerpt truncated]"
    point = SourceSpan(manifest["snapshot_id"], path, entry["sha256"],
                       start, end, "manual", "candidate")
    return ContextExcerpt(point, text, "ranked source context for engineering review")


def _semantic_lookup(root, manifest, changed, symbol):
    if not symbol:
        return None
    if len(changed) != 1:
        raise ContextRetrievalError("Symbol lookup requires exactly one changed file")
    suffix = Path(changed[0]).suffix.lower()
    language = LANGUAGES.get(suffix)
    if language is None:
        raise ContextRetrievalError("No semantic adapter for this changed-file language")
    if language == "python":
        return index_python(root, changed[0], symbol, snapshot=manifest)
    if language == "typescript":
        return index_typescript(root, changed[0], symbol, snapshot=manifest)
    return index_compiled(root, language, changed[0], symbol, snapshot=manifest)


def retrieve_context(root: Path, changed: list[str], symbol: str | None = None,
                     snapshot: dict | None = None, cache_file: Path | None = None,
                     max_items: int = 12, context_radius: int = 3) -> dict:
    """Return ranked, source-hash-verified evidence with explicit coverage.

    Only exact-snapshot cache hits reuse graph edges. Any changed path/config
    triggers full graph rebuilding and conservative affected-context reporting.
    """
    root = root.resolve()
    if (not root.is_dir() or not isinstance(changed, list)
            or not 1 <= len(changed) <= MAX_CHANGED or
            any(not isinstance(p, str) or not _safe_path(p) for p in changed)):
        raise ContextRetrievalError("Supply 1–20 safe changed source paths")
    if (type(max_items) is not int or not 1 <= max_items <= MAX_ITEMS
            or type(context_radius) is not int or not 0 <= context_radius <= 8):
        raise ContextRetrievalError("Context budgets are outside supported ranges")
    manifest = capture_worktree(root) if snapshot is None else validate_snapshot(snapshot)
    if not manifest["complete"]:
        return _abstain(manifest, "incomplete", "Source manifest is incomplete")
    if not verify_worktree(root, manifest)["verified"]:
        return _abstain(manifest, "stale", "Source manifest changed before context retrieval")
    in_manifest = {f["path"] for f in manifest["files"]}
    if any(path not in in_manifest for path in changed):
        return _abstain(manifest, "unindexed", "At least one changed path is absent from source snapshot")
    previous = read_cache(cache_file, root) if cache_file else None
    hit = bool(previous and previous["snapshot"]["snapshot_id"] == manifest["snapshot_id"])
    invalidation = {"changed": [], "affected": [], "scope": "none"}
    cache_status = "disabled" if cache_file is None else "hit" if hit else "miss"
    if hit:
        cross, module = previous["cross"], previous["module"]
    else:
        if previous:
            invalidation = invalidated_paths(previous["snapshot"], manifest,
                                             previous["module"], previous["cross"])
        cross = build_cross_layer(root, snapshot=manifest)
        if cross["status"] in ("stale", "incomplete"):
            return _abstain(manifest, cross["status"], "Cross-layer graph was not reliable")
        module = build_graph(root)
        if not _check_module_hashes(module, manifest):
            return _abstain(manifest, "stale", "Import graph has mismatched source hashes")
        if not verify_worktree(root, manifest)["verified"]:
            return _abstain(manifest, "stale", "Worktree changed during graph build")
        if cache_file:
            if cross["status"] == "complete" and not module["warnings"]:
                try:
                    save_cache(cache_file, root, manifest, cross, module)
                    cache_status = "stored" if previous is None else "rebuilt"
                except (ContextCacheError, OSError) as exc:
                    cache_status = "not_stored"
            else:
                cache_status = "bypassed_incomplete_graph"
    semantic = _semantic_lookup(root, manifest, changed, symbol)
    full_edges = _fusion_edges(cross, module, semantic)
    scores, reasons, anchors = _rank(changed, full_edges, semantic)
    # Keep all ranked paths tied to the same source manifest; module graph can
    # only rank indexed source entries.
    candidates = sorted(
        (p for p in scores if p in in_manifest),
        key=lambda p: (-scores[p], p),
    )
    ranked = []
    excerpts = []
    for path in candidates[:max_items]:
        anchor = anchors.get(path, (1, 0))[0]
        item = _excerpt(root, manifest, path, anchor, context_radius)
        if item is None:
            continue
        excerpts.append(item)
        ranked.append({"path": path, "score": scores[path],
                       "signals": sorted(reasons[path]),
                       "location": asdict(item.location),
                       "excerpt": item.text,
                       "trust": "untrusted_repository_source"})
    if not verify_worktree(root, manifest)["verified"]:
        return _abstain(manifest, "stale", "Source changed while gathering context")
    symbols, references = [], []
    if semantic and semantic.get("status") in ("complete", "partial") and semantic.get("definition"):
        definition = SourceSpan(**semantic["definition"])
        symbols = [SemanticSymbol(symbol, "queried_declaration", definition)]
        for ref in semantic.get("references", [])[:500]:
            references.append(SemanticReference(
                symbol, ref["relationship"], SourceSpan(**ref["location"]),
                SourceSpan(**ref["target_location"]) if ref.get("target_location") else definition,
            ))
    bundle = context_bundle(manifest, symbols, references, excerpts)
    warnings = list(cross.get("warnings", [])) + list(module.get("warnings", []))
    if semantic:
        warnings += [f"semantic: {w}" for w in semantic.get("warnings", [])]
    if len(candidates) > max_items:
        warnings.append("Source context ranking exceeded output budget")
    if len(full_edges) > MAX_FUSED_EDGES:
        warnings.append("Fused edge display truncated; graph-based ranking used full bounded edges")
    semantic_status = semantic["status"] if semantic else "not_requested"
    status = ("partial" if (warnings or cross["status"] != "complete" or
                           semantic_status not in ("complete", "not_requested")) else "complete")
    return {
        "format": FORMAT, "status": status,
        "snapshot_id": manifest["snapshot_id"],
        "changed": sorted(set(changed)),
        "symbol": symbol,
        "ranked_context": ranked, "context_bundle": bundle,
        "graph_edges": full_edges[:MAX_FUSED_EDGES],
        "cache": {"status": cache_status, "invalidation": invalidation,
                  "exact_snapshot_hit": hit},
        "coverage": {
            "semantic_adapter": LANGUAGES.get(Path(changed[0]).suffix.lower()) if symbol else None,
            "language_semantic_status": semantic_status,
            "cross_layer_status": cross["status"],
            "import_graph_warning_count": len(module.get("warnings", [])),
            "total_candidate_edges": len(full_edges),
            "rankable_paths": len(candidates),
            "returned_contexts": len(ranked),
            "ranking_truncated": len(candidates) > max_items,
            "verified_runtime_calls": False,
            "note": "Complete means this bounded static scan succeeded, not complete program understanding.",
        },
        "warnings": warnings[:50],
        "limitations": [
            "Static candidates and import graphs do not prove runtime calls or bug presence.",
            "Exact-hash cache hits reuse graph metadata; changed snapshots cause complete graph rebuilds.",
            "Language adapters are opt-in per symbol, not a persistently indexed whole-project compiler database.",
            "Source excerpts are untrusted and must not be treated as tool instructions.",
        ],
    }
