"""R8.04g independent GitHub API job-status and source policy regressions."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

from daddy_reviews import github_job_status as check
from daddy_reviews import cli
from daddy_reviews.human_attestation import HumanVerificationError

REPO = "cognetheus/daddy-reviews"
REPO_ID = 1431087545
SHA = "a" * 40
RUN_ID = 926115
ATTEMPT = 2


def run_record():
    return {
        "id": RUN_ID, "run_attempt": ATTEMPT, "head_sha": SHA,
        "status": "completed", "conclusion": "success", "event": "push",
        "path": check.WORKFLOW, "workflow_id": 51516,
        "repository": {"id": REPO_ID, "full_name": REPO},
        "head_repository": {"id": REPO_ID, "full_name": REPO},
    }


def jobs_record():
    rows = []
    for idx, name in enumerate(check.JOB_NAMES):
        stepnames = ["Set up job", *check.REQUIRED_STEPS[name], "Complete job"]
        rows.append({
            "id": 50000 + idx, "run_id": RUN_ID, "run_attempt": ATTEMPT,
            "name": name, "status": "completed", "conclusion": "success",
            "labels": ["ubuntu-latest"], "runner_environment": "github-hosted",
            "steps": [{"name": item, "status": "completed", "conclusion": "success"}
                      for item in stepnames],
        })
    return {"total_count": 3, "jobs": rows}


def expectations():
    return {"expected_repo": REPO, "expected_repo_id": REPO_ID,
            "expected_commit": SHA, "expected_run_id": RUN_ID,
            "expected_attempt": ATTEMPT}


def test_live_response_policy_accepts_only_exact_completed_three_job_run():
    result = check.verify_github_job_responses(run_record(), jobs_record(), **expectations())
    assert result["status"] == "github_api_run_and_jobs_verified"
    assert result["repository_numeric_id"] == REPO_ID
    assert result["workflow_path"] == check.WORKFLOW
    assert list(result["jobs"]) == list(check.JOB_NAMES)
    assert result["github_reported_run_conclusion"] == "success"
    assert result["test_outcome_proven"] is False
    assert result["cryptographic_job_status_signature"] is False
    assert result["github_publication"] == result["merge_action"] == "none"


@pytest.mark.parametrize("path,value", [
    ("id", RUN_ID + 1),
    ("run_attempt", ATTEMPT + 1),
    ("head_sha", "b" * 40),
    ("status", "in_progress"),
    ("conclusion", "failure"),
    ("event", "pull_request"),
    ("path", ".github/workflows/other.yml"),
    ("repository", {"id": REPO_ID + 1, "full_name": REPO}),
    ("head_repository", {"id": REPO_ID + 1}),
    ("workflow_id", 0),
])
def test_mismatched_github_run_metadata_fails_closed(path, value):
    changed = run_record()
    changed[path] = value
    with pytest.raises(HumanVerificationError):
        check.verify_github_job_responses(changed, jobs_record(), **expectations())


@pytest.mark.parametrize("patch", [
    lambda j: j["jobs"][0].update(conclusion="failure"),
    lambda j: j["jobs"][0].update(status="in_progress"),
    lambda j: j["jobs"][0].update(run_attempt=1),
    lambda j: j["jobs"][0].update(runner_environment="self-hosted"),
    lambda j: j["jobs"][0].update(labels=["self-hosted"]),
    lambda j: j["jobs"][0]["steps"][1].update(conclusion="failure"),
    lambda j: j["jobs"][1]["steps"].pop(1),
    lambda j: j["jobs"][2].update(name="unknown-job"),
    lambda j: j["jobs"][2].update(id=j["jobs"][0]["id"]),
    lambda j: j.update(total_count=5),
    lambda j: j["jobs"].pop(),
])
def test_failed_or_incomplete_jobs_never_count_as_proven(patch):
    jobs = jobs_record()
    patch(jobs)
    with pytest.raises(HumanVerificationError):
        check.verify_github_job_responses(run_record(), jobs, **expectations())


def test_duplicate_json_and_invalid_content_fails_closed():
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{}' * 40_000):
        with pytest.raises(HumanVerificationError):
            check._json_object(raw)


def test_live_authenticated_gh_api_calls_are_exact_attempt_scoped(monkeypatch):
    calls = []
    monkeypatch.setattr(check, "_verified_executable", lambda path, digest: Path(path))
    def run(args, **kwargs):
        calls.append((args, kwargs))
        obj = run_record() if len(calls) == 1 else jobs_record()
        return subprocess.CompletedProcess(args, 0, json.dumps(obj).encode(), b"")
    monkeypatch.setattr(check.subprocess, "run", run)
    token = "operator-read-only-1234567890"
    result = check.verify_live_github_jobs(
        gh_binary=Path("/usr/bin/gh"),
        gh_binary_sha256="a" * 64,
        **expectations(), api_token=token)
    assert result["status"] == "github_api_run_and_jobs_verified"
    assert result["api_authentication"] == "live_GitHub_REST_via_token_and_TLS"
    assert len(calls) == 2
    assert calls[0][0][-1] == (
        f"/repos/{REPO}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}")
    assert calls[1][0][-1] == (
        f"/repos/{REPO}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs?per_page=100&page=1")
    for args, opts in calls:
        assert args[1:4] == ["api", "--method", "GET"]
        assert token not in str(args)
        assert opts["env"]["GH_TOKEN"] == token
        assert opts["env"]["GH_HOST"] == "github.com"
        assert opts["env"]["GH_CONFIG_DIR"] == opts["env"]["HOME"]
        assert opts["check"] is False


def test_unauthenticated_transport_and_error_status_fail(monkeypatch):
    monkeypatch.setattr(check, "_verified_executable", lambda path, digest: Path(path))
    called = []
    monkeypatch.setattr(check.subprocess, "run",
                        lambda args, **kw: called.append(args) or
                        subprocess.CompletedProcess(args, 1, b'{}', b"unauthorized"))
    args = {"gh_binary": Path("/usr/bin/gh"), "gh_binary_sha256": "a" * 64,
            **expectations()}
    with pytest.raises(HumanVerificationError):
        check.verify_live_github_jobs(**args, api_token=None)
    assert not called
    with pytest.raises(HumanVerificationError):
        check.verify_live_github_jobs(**args, api_token="operator-token-12345")


def test_cli_uses_explicit_token_and_source_policy(monkeypatch, tmp_path, capsys):
    invoked = []
    monkeypatch.setenv("GH_TOKEN", "test-token-123456789")
    def verify(**kw):
        invoked.append(kw)
        return {"status": "github_api_run_and_jobs_verified",
                "merge_action": "none", "github_publication": "none"}
    monkeypatch.setattr(cli, "verify_live_github_jobs", verify)
    cli.main([
        "github-jobs-verify", "--root", str(tmp_path),
        "--gh-binary", "/usr/bin/gh", "--gh-binary-sha256", "a" * 64,
        "--attestation-repo", REPO, "--attestation-repo-id", str(REPO_ID),
        "--attestation-commit", SHA,
        "--test-run-id", str(RUN_ID), "--test-run-attempt", str(ATTEMPT),
    ])
    assert json.loads(capsys.readouterr().out)["status"] == "github_api_run_and_jobs_verified"
    assert invoked[0]["expected_run_id"] == RUN_ID
    assert invoked[0]["expected_repo_id"] == REPO_ID
    assert invoked[0]["api_token"] == "test-token-123456789"
