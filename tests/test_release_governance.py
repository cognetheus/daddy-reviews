"""R8.05b: fail-closed branch governance without elevating write permissions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest

from daddy_reviews import cli
from daddy_reviews.human_attestation import HumanVerificationError
from daddy_reviews import release_governance as check

REPO = "cognetheus/daddy-reviews"
REPO_ID = 1234567
BRANCH = "main"
COMMIT = "a" * 40


def records():
    repo = {
        "id": REPO_ID, "full_name": REPO, "default_branch": BRANCH,
        "archived": False, "disabled": False,
    }
    branch = {"name": BRANCH, "commit": {"sha": COMMIT}, "protected": True}
    protection = {
        "required_status_checks": {
            "strict": True,
            "contexts": list(check.REQUIRED_CHECKS),
            "checks": [{"context": "test (3.12)", "app_id": 15368}],
        },
        "required_pull_request_reviews": {
            "required_approving_review_count": 2,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": True,
        },
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "lock_branch": {"enabled": False},
    }
    return repo, branch, protection


def run_policy(repo, branch, protection, **params):
    expected = {
        "expected_repo": REPO, "expected_repo_id": REPO_ID,
        "expected_branch": BRANCH, "expected_commit": COMMIT,
    }
    return check.assess_branch_governance(repo, branch, protection,
                                          **{**expected, **params})


def test_strong_branch_protection_is_only_a_candidate_until_live_api_checks():
    result = run_policy(*records())
    assert result["status"] == "branch_policy_valid_in_untrusted_input"
    assert result["security_gaps"] == []
    assert result["branch_policy_verified"] is False
    assert result["github_api_authenticated"] is False
    assert result["release_authorized"] is False
    assert result["human_signoff_required"] is True
    assert result["github_publication"] == result["merge_action"] == "none"


@pytest.mark.parametrize("break_policy", [
    lambda r,b,p: r.update(id=True),
    lambda r,b,p: r.update(default_branch="develop"),
    lambda r,b,p: r.update(archived=True),
    lambda r,b,p: b.update(commit={"sha": "0" * 40}),
    lambda r,b,p: b.update(protected=False),
    lambda r,b,p: p.update(required_status_checks=None),
    lambda r,b,p: p["required_status_checks"].update(strict=False),
    lambda r,b,p: p["required_status_checks"].update(contexts=["test (3.10)"]),
    lambda r,b,p: p["required_status_checks"].update(contexts=None, checks=None),
    lambda r,b,p: p.update(required_pull_request_reviews=None),
    lambda r,b,p: p["required_pull_request_reviews"].update(required_approving_review_count=1),
    lambda r,b,p: p["required_pull_request_reviews"].update(required_approving_review_count=True),
    lambda r,b,p: p["required_pull_request_reviews"].update(dismiss_stale_reviews=False),
    lambda r,b,p: p["required_pull_request_reviews"].update(require_code_owner_reviews=False),
    lambda r,b,p: p.update(enforce_admins={"enabled": False}),
    lambda r,b,p: p.update(required_conversation_resolution={"enabled": False}),
    lambda r,b,p: p.update(allow_force_pushes={"enabled": True}),
    lambda r,b,p: p.update(allow_deletions={"enabled": True}),
    lambda r,b,p: p.update(lock_branch={"enabled": True}),
])
def test_missing_policy_requirement_fails_closed(break_policy):
    repo, branch, protection = copy.deepcopy(records())
    break_policy(repo, branch, protection)
    result = run_policy(repo, branch, protection)
    assert result["status"] == "blocked_branch_security_gate"
    assert result["security_gaps"]
    assert not result["branch_policy_verified"]


def test_app_protection_permission_403_is_a_blocker_not_a_proof():
    repo, branch, _ = records()
    result = run_policy(
        repo, branch, None,
        protection_fetch_error="403 Resource not accessible by integration")
    assert result["status"] == "blocked_branch_security_gate"
    assert result["protection_fetch_error"].startswith("403")
    assert "branch_protection_not_accessible_or_not_configured" in result["security_gaps"]
    assert result["release_authorized"] is False


def test_live_fetch_uses_exact_three_gets_and_isolation_without_token_in_argv(
        tmp_path, monkeypatch):
    repo, branch, protection = records()
    response = [repo, branch, protection]
    calls = []
    monkeypatch.setattr(check, "_verified_executable", lambda path, sha: Path(path))
    def fake_run(argv, **options):
        calls.append((argv, options))
        return subprocess.CompletedProcess(argv, 0,
                                           json.dumps(response[len(calls) - 1]).encode(), b"")
    monkeypatch.setattr(check.subprocess, "run", fake_run)
    token = "read-only-test-github-credential"
    result = check.verify_live_branch_governance(
        gh_binary=tmp_path / "gh", gh_binary_sha256="f" * 64,
        api_token=token, expected_repo=REPO, expected_repo_id=REPO_ID,
        expected_branch=BRANCH, expected_commit=COMMIT)
    assert result["status"] == "authenticated_branch_policy_verified"
    assert result["github_api_authenticated"] is True
    assert result["branch_policy_verified"] is True
    assert result["release_authorized"] is False
    assert len(calls) == 3
    assert [call[0][-1] for call in calls] == [
        f"/repos/{REPO}", f"/repos/{REPO}/branches/main",
        f"/repos/{REPO}/branches/main/protection",
    ]
    for argv,opts in calls:
        assert argv[1:4] == ["api", "--method", "GET"]
        assert token not in str(argv)
        assert opts["env"]["GH_TOKEN"] == token
        assert opts["env"]["GH_HOST"] == "github.com"
        assert opts["env"]["HOME"] == opts["env"]["GH_CONFIG_DIR"]
        assert opts["check"] is False


def test_live_403_blocks_release_but_returns_actionable_safe_summary(
        tmp_path, monkeypatch):
    repo, branch, _ = records()
    responses = [repo, branch]
    calls = []
    monkeypatch.setattr(check, "_verified_executable", lambda path, sha: Path(path))
    def fake_run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 3:
            return subprocess.CompletedProcess(argv, 1, b"", b"permission denied")
        return subprocess.CompletedProcess(argv, 0,
                                           json.dumps(responses[len(calls)-1]).encode(), b"")
    monkeypatch.setattr(check.subprocess, "run", fake_run)
    result = check.verify_live_branch_governance(
        gh_binary=tmp_path/"gh", gh_binary_sha256="f"*64,
        api_token="read-only-test-token-1234",
        expected_repo=REPO, expected_repo_id=REPO_ID,
        expected_branch=BRANCH, expected_commit=COMMIT)
    assert result["status"] == "blocked_branch_security_gate"
    assert result["github_api_authenticated"] is True
    assert result["branch_policy_verified"] is False
    assert "branch_protection_not_accessible_or_not_configured" in result["security_gaps"]
    assert "permission denied" not in json.dumps(result)


def test_missing_token_or_unsafe_api_identifier_cannot_make_requests(
        tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(check, "_verified_executable", lambda path, sha: Path(path))
    monkeypatch.setattr(check.subprocess, "run",
                        lambda *a, **kw: calls.append(a))
    common = dict(gh_binary=tmp_path/"gh", gh_binary_sha256="f"*64,
                  expected_repo=REPO, expected_repo_id=REPO_ID,
                  expected_branch=BRANCH, expected_commit=COMMIT)
    with pytest.raises(HumanVerificationError):
        check.verify_live_branch_governance(**common, api_token=None)
    with pytest.raises(HumanVerificationError):
        check.verify_live_branch_governance(**{**common, "expected_branch": "../main"},
                                            api_token="valid-token-123456")
    assert not calls


def test_governance_cli_prints_blocked_summary_then_exits_nonzero(
        monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GH_TOKEN", "operator-read-token-123456")
    monkeypatch.setattr(cli, "verify_live_branch_governance",
                        lambda **kw: run_policy(*records()[:2], None))
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "branch-governance-audit", "--root", str(tmp_path),
            "--attestation-repo", REPO,
            "--attestation-repo-id", str(REPO_ID),
            "--attestation-commit", COMMIT,
            "--gh-binary", "/usr/bin/gh", "--gh-binary-sha256", "f"*64,
        ])
    assert exc.value.code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "blocked_branch_security_gate"
    assert summary["release_authorized"] is False
