"""R5: dry-run, human authorization, PR line validation and idempotent GitHub writes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from daddy_reviews.github_publish import PublicationError, curate_findings, publish, _added_lines
from daddy_reviews.rerun import RerunError, plan_rerun, read_state, save_state

HEAD = "a" * 40
DIFF = ("diff --git a/app.py b/app.py\nindex a..b 100644\n"
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n")
FINDING = {
    "rule": "BUG_001", "path": "app.py", "line": 1,
    "claim": "Potentially unsafe operation", "evidence": "Regression test 17 failed",
    "severity": "high", "verification": "confirmed", "changed": True,
    "verification_artifact": "tests/test_app.py::test_regression_17",
    "human_approved": True,
}

class FakeClient:
    def __init__(self, sha=HEAD):
        self.sha = sha
        self.posts = []
        self.comments = []
    def request(self, method, path, data=None):
        if method == "GET" and path.endswith("/pulls/7"):
            return {"state": "open", "head": {"sha": self.sha}}
        if method == "GET" and "/files?" in path:
            return [{"filename": "app.py", "patch": "@@ -1 +1 @@\n-old\n+new\n"}]
        if method == "GET" and "/comments?" in path:
            return list(self.comments)
        if method == "POST" and path.endswith("/comments"):
            self.posts.append(data)
            self.comments.append({"body": data["body"]})
            return {"id": len(self.posts)}
        raise AssertionError((method, path))

def test_dry_run_has_no_network_and_filters_unapproved():
    data = publish("example/repo", 7, {"findings": [
        dict(FINDING), {**FINDING, "human_approved": False},
        {**FINDING, "rule": "UNVERIFIED", "verification": "unverified"},
    ]})
    assert data["mode"] == "dry_run"
    assert data["eligible_count"] == 1
    assert data["omitted_count"] == 2
    assert data["posted"] == []

def test_apply_requires_explicit_pinned_commit_and_human_approved_evidence():
    with pytest.raises(PublicationError, match="expected-head"):
        publish("example/repo", 7, {"findings": [FINDING]}, apply=True, client=FakeClient())
    with pytest.raises(PublicationError, match="No independently"):
        publish("example/repo", 7, {"findings": [
            {**FINDING, "verification": "unverified"}]},
            HEAD, apply=True, client=FakeClient())

def test_stale_pr_head_and_non_added_line_are_rejected_prewrite():
    with pytest.raises(PublicationError, match="HEAD changed"):
        publish("example/repo", 7, {"findings": [FINDING]},
                HEAD, apply=True, client=FakeClient("b" * 40))
    with pytest.raises(PublicationError, match="added PR line"):
        publish("example/repo", 7, {"findings": [
            {**FINDING, "line": 999}]}, HEAD, apply=True, client=FakeClient())

def test_exactly_once_comment_across_reruns_and_human_gate():
    client = FakeClient()
    first = publish("example/repo", 7, {"findings": [FINDING]}, HEAD, apply=True, client=client)
    second = publish("example/repo", 7, {"findings": [FINDING]}, HEAD, apply=True, client=client)
    assert first["posted"][0]["id"] == 1
    assert not second["posted"] and len(second["skipped_existing"]) == 1
    assert len(client.posts) == 1
    assert client.posts[0]["side"] == "RIGHT"
    assert client.posts[0]["commit_id"] == HEAD
    assert "daddy-reviews:" in client.posts[0]["body"]
    assert first["merge_action"] == "none"

def test_rejects_untrustworthy_paths_and_invalid_json_schema():
    assert not curate_findings({"findings": [
        {**FINDING, "path": "../../etc/passwd"}]})["eligible"]
    with pytest.raises(PublicationError):
        publish("example/repo", 7, {"findings": [123]})
    with pytest.raises(PublicationError):
        publish("https://example.com/repo", 7, {"findings": []})

def test_added_line_parser_handles_multiple_hunks():
    assert _added_lines("@@ -1 +1 @@\n-old\n+new\n@@ -10 +10,2 @@\n a\n+more\n") == {1, 11}

def test_first_review_incremental_change_and_noop_state():
    with TemporaryDirectory() as td:
        root = Path(td)
        state_file = root / "state.json"
        first = plan_rerun(root, DIFF, HEAD)
        assert first["action"] == "initial_review"
        assert first["changed_files"] == ["app.py"]
        assert not state_file.exists()
        save_state(state_file, first["state"])
        before = read_state(state_file)
        unchanged = plan_rerun(root, DIFF, HEAD, before)
        assert unchanged["action"] == "no_change"
        assert unchanged["selected_reviewers"] == []
        moved = plan_rerun(root, DIFF.replace("+new", "+better"), "b" * 40, before)
        assert moved["action"] == "review_changed"
        assert moved["changed_files"] == ["app.py"]
        assert moved["head_changed"]

def test_corrupt_or_symlink_state_fails_closed():
    with TemporaryDirectory() as td:
        root = Path(td)
        state = root / "state.json"
        state.write_text("{broken")
        with pytest.raises(RerunError):
            read_state(state)
        state.unlink()
        state.symlink_to(root / "other")
        with pytest.raises(RerunError):
            save_state(state, plan_rerun(root, DIFF, HEAD)["state"])
