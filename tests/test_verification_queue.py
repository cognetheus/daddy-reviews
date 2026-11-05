"""R8.04a verification queue safety and integration regressions."""
import copy
import pytest

from daddy_reviews.investigative_agents import investigate_with_specialists
from daddy_reviews.verification_queue import build_verification_queue


PATCH = """diff --git a/src/check.py b/src/check.py
--- a/src/check.py
+++ b/src/check.py
@@ -1,1 +1,2 @@
 def check(user):
+    return bool(user)
"""


def _run(tmp_path, *, severity="medium", fail=False):
    source = tmp_path / "src"
    source.mkdir()
    (source / "check.py").write_text(
        "def check(user):\n    return bool(user)\n", encoding="utf-8"
    )

    def provider(reviewer, messages):
        if fail:
            raise TimeoutError("provider unavailable")
        if len(messages) == 1:
            return {"kind": "tool", "call": {
                "tool": "read_file", "path": "src/check.py",
                "start_line": 1, "end_line": 2,
            }}
        return {"kind": "final", "findings": [{
            "rule": "AUTH-EMPTY", "path": "src/check.py", "line": 2,
            "claim": "Possible access check regression",
            "evidence": "This boolean check may accept an unexpected identity",
            "severity": severity, "citations": ["E1"],
        }]}

    return investigate_with_specialists(
        tmp_path, PATCH, provider, reviewers=("security",),
        allowed_tools={"read_file"}, max_workers=1,
    )


def test_candidate_is_not_confirmed_or_published(tmp_path):
    result = _run(tmp_path)
    queue = result["verification_queue"]
    assert queue["status"] == "pending_independent_verification"
    assert queue["confirmed_findings"] == 0
    assert queue["merge_action"] == queue["github_publication"] == "none"
    assert len(queue["items"]) == 1
    item = queue["items"][0]
    assert item["status"] == "needs_independent_verification"
    assert item["source_spans"][0]["path"] == "src/check.py"
    assert item["verification"] == "unverified"
    assert len(item["required_checks"]) == 3
    assert queue == build_verification_queue(result)


def test_suggestion_severity_supported(tmp_path):
    result = _run(tmp_path, severity="suggestion")
    assert result["verification_queue"]["items"][0]["severities_claimed"] == ["suggestion"]


def test_incomplete_review_never_reads_as_clean(tmp_path):
    result = _run(tmp_path, fail=True)
    queue = result["verification_queue"]
    assert queue["status"] == "human_escalation_required"
    assert queue["coverage"] == "incomplete"
    assert queue["incomplete_reviewers"] == ["security"]
    assert queue["items"] == []


def test_tampered_evidence_is_escalated_not_confirmed(tmp_path):
    result = _run(tmp_path)
    tampered = copy.deepcopy(result)
    tampered["model_findings"][0]["source_evidence"][0]["source"]["source_sha256"] = "0" * 64
    # A syntactically plausible but forged hash cannot be checked against the
    # snapshot in an isolated queue object. The queue is advisory only.
    assert build_verification_queue(tampered)["confirmed_findings"] == 0
    tampered["model_findings"][0]["source_evidence"][0]["source"]["snapshot_id"] = "forged"
    queue = build_verification_queue(tampered)
    assert queue["status"] == "human_escalation_required"
    assert queue["items"][0]["reason"] == "invalid_source_provenance"
    assert queue["items"][0]["source_spans"] == []


def test_model_claim_cannot_self_verify(tmp_path):
    result = _run(tmp_path)
    tampered = copy.deepcopy(result)
    tampered["model_findings"][0]["verification"] = "confirmed"
    queue = build_verification_queue(tampered)
    assert queue["items"][0]["reason"] == "invalid_source_provenance"
    assert queue["confirmed_findings"] == 0


def test_invalid_report_and_duplicate_run_rejected(tmp_path):
    result = _run(tmp_path)
    with pytest.raises(ValueError):
        build_verification_queue({"format": "different"})
    duplicate = copy.deepcopy(result)
    duplicate["reviewer_runs"].append(duplicate["reviewer_runs"][0])
    with pytest.raises(ValueError):
        build_verification_queue(duplicate)


def test_stable_ids_and_source_provenance(tmp_path):
    result = _run(tmp_path)
    a = build_verification_queue(result)
    b = build_verification_queue(copy.deepcopy(result))
    assert a == b
    assert len(a["items"][0]["id"]) == 24
    assert a["snapshot_id"] == result["snapshot_id"]
