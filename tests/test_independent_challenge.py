"""R8.04b: independent challenge is source-bound, budgeted and advisory."""
import copy

import pytest

from daddy_reviews.agents import AgentRuntimeError
from daddy_reviews.independent_challenge import challenge_findings
from daddy_reviews.investigative_agents import investigate_with_specialists

PATCH = (
    "diff --git a/src/auth.py b/src/auth.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n+++ b/src/auth.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def authorize(user):\n"
    "+    return bool(user)\n"
)


def seed(root):
    source = root / "src/auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def authorize(user):\n    return bool(user)\n", encoding="utf-8")


def report(root):
    seed(root)
    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {
                "tool": "read_file", "path": "src/auth.py",
                "start_line": 1, "end_line": 2}}
        return {"kind": "final", "findings": [{
            "rule": "AUTH-BOOL", "path": "src/auth.py", "line": 2,
            "claim": "Truthy strings might bypass authorization",
            "evidence": "Authorization checks only truthiness",
            "severity": "medium", "citations": ["E1"],
        }]}
    result = investigate_with_specialists(
        root, PATCH, provider, reviewers=("security",),
        allowed_tools={"read_file"}, max_workers=1,
    )
    assert result["status"] == "complete"
    return result


def _challenger(verdict="refuted"):
    def provider(reviewer, messages):
        assert reviewer == "code-quality"
        if len(messages) == 1:
            payload = __import__("json").loads(messages[0]["content"])
            assert "candidate" in payload
            assert "source_evidence" not in payload
            return {"kind": "tool", "call": {
                "tool": "read_file", "path": "src/auth.py",
                "start_line": 1, "end_line": 2}}
        response = __import__("json").loads(messages[-1]["content"])
        assert response["host_evidence_ids"]["E1"]["path"] == "src/auth.py"
        return {"kind": "final", "verdict": verdict,
                "reason": "The source check has no explicit role comparison",
                "citations": ["E1"]}
    return provider


def test_independent_refutation_cannot_silently_clear_finding(tmp_path):
    original = report(tmp_path)
    challenged = challenge_findings(
        tmp_path, PATCH, original, _challenger(),
        reviewer="code-quality", allowed_tools={"read_file"},
    )
    assert challenged["status"] == "completed_advisory"
    assert challenged["confirmed_findings"] == 0
    assert challenged["merge_action"] == challenged["github_publication"] == "none"
    assert challenged["outcomes"][0]["challenge_verdict"] == "refuted"
    assert challenged["outcomes"][0]["verification"] == "unverified"
    assert len(challenged["outcomes"][0]["citations"]) == 1
    assert original["model_findings"][0]["verification"] == "unverified"


def test_same_reviewer_not_independent(tmp_path):
    original = report(tmp_path)
    calls = []
    result = challenge_findings(
        tmp_path, PATCH, original, lambda r, m: calls.append(m),
        reviewer="security", allowed_tools={"read_file"},
    )
    assert calls == []
    assert result["status"] == "incomplete"
    assert result["outcomes"][0]["reason"] == "not_independent"


def test_forged_citations_fail_closed(tmp_path):
    original = report(tmp_path)
    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {
                "tool": "read_file", "path": "src/auth.py", "start_line": 1,
                "end_line": 2}}
        return {"kind": "final", "verdict": "supported",
                "reason": "I made up evidence", "citations": ["E999"]}
    result = challenge_findings(
        tmp_path, PATCH, original, provider,
        reviewer="code-quality", allowed_tools={"read_file"},
    )
    assert result["status"] == "incomplete"
    assert result["outcomes"][0]["status"] == "escalate_human"


def test_no_citation_no_self_confirmation(tmp_path):
    original = report(tmp_path)
    result = challenge_findings(
        tmp_path, PATCH, original,
        lambda r, m: {"kind": "final", "verdict": "supported",
                      "reason": "Model certainty", "citations": []},
        reviewer="code-quality",
    )
    assert result["status"] == "incomplete"
    assert result["confirmed_findings"] == 0


def test_denied_tools_do_not_count_as_clean(tmp_path):
    original = report(tmp_path)
    result = challenge_findings(
        tmp_path, PATCH, original, _challenger(),
        reviewer="code-quality", allowed_tools=(),
    )
    assert result["status"] == "incomplete"
    assert result["outcomes"][0]["reason"] == "tool_denied"


def test_changed_source_or_patch_abstains_before_model(tmp_path):
    original = report(tmp_path)
    called = []
    with pytest.raises(AgentRuntimeError):
        challenge_findings(tmp_path, PATCH + "extra", original,
                           lambda r, m: called.append(m))
    (tmp_path / "src/auth.py").write_text("def authorize(user):\n    return True\n")
    with pytest.raises(AgentRuntimeError):
        challenge_findings(tmp_path, PATCH, original,
                           lambda r, m: called.append(m))
    assert called == []


def test_incomplete_original_review_abstains(tmp_path):
    original = report(tmp_path)
    modified = copy.deepcopy(original)
    modified["status"] = "incomplete"
    with pytest.raises(AgentRuntimeError):
        challenge_findings(tmp_path, PATCH, modified, _challenger())


def test_model_cannot_request_write_or_publish(tmp_path):
    original = report(tmp_path)
    for action in (
        {"kind": "tool", "call": {"tool": "write_file", "path": "src/auth.py"}},
        {"kind": "final", "verdict": "refuted", "reason": "Not a bug",
         "citations": ["E1"], "merge_action": "approve"},
    ):
        outcome = challenge_findings(
            tmp_path, PATCH, original, lambda r, m: action,
            reviewer="code-quality", allowed_tools={"read_file"},
        )
        assert outcome["status"] == "incomplete"
        assert outcome["outcomes"][0]["status"] == "escalate_human"
