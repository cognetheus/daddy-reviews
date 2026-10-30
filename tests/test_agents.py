"""R4 tests: opt-in bounded specialist sessions with fake local provider."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from daddy_reviews.agents import (AgentRuntimeError, _endpoint, local_ollama_provider,
                                  review_with_specialists)

PATCH = (
    "diff --git a/src/auth/login.py b/src/auth/login.py\n"
    "new file mode 100644\n--- /dev/null\n+++ b/src/auth/login.py\n"
    "@@ -0,0 +1 @@\n+def check(user): return user != None\n"
)

def test_local_only_transport_and_no_network_on_construction():
    assert _endpoint("http://127.0.0.1:11434") == "http://127.0.0.1:11434/api/chat"
    assert _endpoint("http://[::1]:11434") == "http://[::1]:11434/api/chat"
    assert callable(local_ollama_provider("some-local-model"))
    for url in ("https://localhost:11434", "http://example.com:11434",
                "http://127.0.0.1:11434/other", "http://127.0.0.1:11434?secret=1",
                "http://user:pass@localhost:11434"):
        with pytest.raises(AgentRuntimeError):
            local_ollama_provider("model", url)

def test_parallel_specialists_cannot_auto_confirm_or_block():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "src/auth").mkdir(parents=True)
        (root / "src/auth/login.py").write_text("def check(user): return user != None\n")
        def provider(reviewer, shared):
            body = json.loads(shared)
            assert "untrusted_patch" in body
            if reviewer == "documentation":
                return {"findings": []}
            return {"findings": [{
                "rule": "AUTH-LEAK", "path": "src/auth/login.py", "line": 1,
                "claim": "Unverified concern", "evidence": "reviewer hypothesis",
                "severity": "critical", "verification": "confirmed",
            }]}
        result = review_with_specialists(root, PATCH, provider)
    assert result["status"] == "complete"
    assert len(result["reviewer_runs"]) == 6
    assert all(x["status"] == "completed" for x in result["reviewer_runs"])
    assert result["model_findings"]
    assert all(x["verification"] == "unverified" for x in result["model_findings"])
    assert result["adjudication"]["merge_action"] == "none"
    assert result["merge_action"] == "none"

def test_invalid_location_marks_run_incomplete():
    with TemporaryDirectory() as d:
        def provider(reviewer, shared):
            return {"findings": [{"rule": "R", "path": "unmodified.py", "line": 9,
                                  "claim": "fake", "evidence": "none",
                                  "severity": "critical"}]}
        result = review_with_specialists(Path(d), PATCH, provider)
    assert result["status"] == "incomplete"
    assert not result["model_findings"]
    assert any(x["status"] == "failed" for x in result["reviewer_runs"])

def test_empty_findings_are_valid_and_a_failed_model_is_not_a_clean_review():
    small = (
        "diff --git a/x.py b/x.py\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
    )
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "x.py").write_text("x = 1\n")
        clean = review_with_specialists(root, small, lambda name, ctx: {"findings": []})
        broken = review_with_specialists(root, small, lambda name, ctx: 123)
    assert clean["status"] == "complete"
    assert clean["model_findings"] == []
    assert broken["status"] == "incomplete"
    assert broken["adjudication"]["merge_action"] == "none"

def test_guard_model_input_budget_and_parallelism():
    with TemporaryDirectory() as d:
        with pytest.raises(AgentRuntimeError):
            review_with_specialists(Path(d), "x" * 48_001, lambda a, b: {})
        with pytest.raises(AgentRuntimeError):
            review_with_specialists(Path(d), "", lambda a, b: {}, max_workers=99)
