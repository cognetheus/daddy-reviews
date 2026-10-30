"""R7.01 contract and manifest acceptance/negative-path tests."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from daddy_reviews.semantic_contracts import (
    SemanticContractError, SourceSpan, SemanticSymbol, SemanticReference,
    ContextExcerpt, bound_span, capture_worktree, context_bundle, read_snapshot,
    validate_snapshot, verify_worktree,
)


def _repo(root: Path):
    (root / "src").mkdir()
    (root / "src" / "auth.py").write_text(
        "def require_tenant(user, tenant):\n"
        "    return user.tenant_id == tenant\n", encoding="utf-8")
    (root / "consumer.py").write_text(
        "from src.auth import require_tenant\n"
        "def load(user, tenant):\n"
        "    return require_tenant(user, tenant)\n", encoding="utf-8")


def test_worktree_snapshot_is_deterministic_and_read_only(tmp_path):
    _repo(tmp_path)
    snap = capture_worktree(tmp_path)
    assert snap["complete"] is True
    assert snap["source_kind"] == "working_tree_manifest"
    assert "not_authenticated_git_tree" in snap["provenance"]
    assert [x["path"] for x in snap["files"]] == ["consumer.py", "src/auth.py"]
    assert snap["snapshot_id"] == capture_worktree(tmp_path)["snapshot_id"]
    assert snap["files"][1]["line_count"] == 2
    assert not (tmp_path / ".daddy").exists()
    assert verify_worktree(tmp_path, snap)["status"] == "fresh"
    output = tmp_path / "manifest.json"
    output.write_text(json.dumps(snap), encoding="utf-8")
    assert read_snapshot(output)["snapshot_id"] == snap["snapshot_id"]


def test_added_modified_and_deleted_files_are_detected(tmp_path):
    _repo(tmp_path)
    original = capture_worktree(tmp_path)
    (tmp_path / "src" / "auth.py").write_text("def require_tenant(): return True\n")
    (tmp_path / "consumer.py").unlink()
    (tmp_path / "new.py").write_text("flag = True\n")
    result = verify_worktree(tmp_path, original)
    assert result["status"] == "stale_or_incomplete"
    assert result["verified"] is False
    assert result["added"] == ["new.py"]
    assert result["removed"] == ["consumer.py"]
    assert result["modified"] == ["src/auth.py"]


def test_incomplete_scan_abstains_and_does_not_claim_freshness(tmp_path):
    _repo(tmp_path)
    (tmp_path / "giant.py").write_bytes(b"x" * 350_001)
    snap = capture_worktree(tmp_path)
    assert not snap["complete"] and snap["warnings"]
    assert verify_worktree(tmp_path, snap)["status"] == "stale_or_incomplete"
    with pytest.raises(SemanticContractError, match="Incomplete"):
        bound_span(snap, "src/auth.py", 1, 1, "ast", "candidate")
    with pytest.raises(SemanticContractError, match="incomplete"):
        context_bundle(snap)


def test_symlink_source_not_followed_and_no_outside_bytes_exposed(tmp_path):
    _repo(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-secret.py")
    outside.write_text("secret = 'PRIVATE'\n")
    try:
        (tmp_path / "leak.py").symlink_to(outside)
        snap = capture_worktree(tmp_path)
        assert snap["complete"] is False
        assert all(f["path"] != "leak.py" for f in snap["files"])
        assert all("PRIVATE" not in json.dumps(snap) for _ in [0])
    finally:
        outside.unlink()


def test_manifest_rejects_path_injection_forged_sha_bool_and_duplicate(tmp_path):
    _repo(tmp_path)
    snap = capture_worktree(tmp_path)
    forged = json.loads(json.dumps(snap))
    forged["files"][0]["path"] = "../../etc/passwd"
    with pytest.raises(SemanticContractError):
        validate_snapshot(forged)
    forged = json.loads(json.dumps(snap))
    forged["files"][0]["sha256"] = "f" * 64
    with pytest.raises(SemanticContractError, match="fingerprint"):
        validate_snapshot(forged)
    forged = json.loads(json.dumps(snap))
    forged["complete"] = 1
    with pytest.raises(SemanticContractError):
        validate_snapshot(forged)
    forged = json.loads(json.dumps(snap))
    forged["files"].append(dict(forged["files"][0]))
    with pytest.raises(SemanticContractError):
        validate_snapshot(forged)


def test_context_bundle_binds_symbol_refs_to_exact_file_hash_and_snapshot(tmp_path):
    _repo(tmp_path)
    snap = capture_worktree(tmp_path)
    definition = bound_span(snap, "src/auth.py", 1, 2, "ast", "candidate")
    call = bound_span(snap, "consumer.py", 3, 3, "lexical", "candidate")
    symbol = SemanticSymbol("require_tenant", "function", definition)
    reference = SemanticReference("require_tenant", "possible_call", call, definition)
    excerpt = ContextExcerpt(definition, "def require_tenant(user, tenant):\n...", "investigate changed trust boundary")
    bundle = context_bundle(snap, [symbol], [reference], [excerpt])
    assert bundle["snapshot_id"] == snap["snapshot_id"]
    assert bundle["references"][0]["location"]["path"] == "consumer.py"
    assert bundle["verified_runtime_calls"] is False
    another = replace(call, source_sha256="a" * 64)
    with pytest.raises(SemanticContractError, match="Stale"):
        context_bundle(snap, references=[replace(reference, location=another)])
    with pytest.raises(SemanticContractError):
        bound_span(snap, "src/auth.py", 3, 3, "ast", "candidate")
    with pytest.raises(SemanticContractError):
        bound_span(snap, "../outside.py", 1, 1, "ast", "candidate")


def test_source_span_rejects_false_certainty_and_invalid_lines(tmp_path):
    _repo(tmp_path)
    snap = capture_worktree(tmp_path)
    entry = snap["files"][0]
    with pytest.raises(SemanticContractError):
        SourceSpan(snap["snapshot_id"], entry["path"], entry["sha256"],
                   True, 3, "ast", "resolved")
    with pytest.raises(SemanticContractError):
        SourceSpan(snap["snapshot_id"], entry["path"], entry["sha256"],
                   1, 2, "model_guess", "confirmed")


def test_read_snapshot_rejects_symlink_and_malformed_json(tmp_path):
    path = tmp_path / "input.json"
    path.write_text("{malformed", encoding="utf-8")
    with pytest.raises(SemanticContractError):
        read_snapshot(path)
    other = tmp_path / "outside.json"
    other.write_text("{}", encoding="utf-8")
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(SemanticContractError, match="symlinked"):
        read_snapshot(path)
