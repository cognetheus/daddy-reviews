"""R8.04g.01: independent, authenticated GitHub Actions run/job status checks.

This module reads LIVE GitHub REST responses via a SHA-256-pinned gh CLI
binary with an explicitly provided read token. It NEVER trusts model-produced
run JSON or executes reviewed repository code. GitHub API data is secured by
TLS and the operator's token, NOT a cryptographically signed job-status claim.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .github_attestation import _verified_executable
from .human_attestation import HumanVerificationError

FORMAT = "daddy-reviews-github-job-status-v1"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
WORKFLOW = ".github/workflows/attested-test-execution.yml"
JOB_NAMES = ("run-fixed-suite", "sign-only", "verify-attested")
REQUIRED_STEPS = {
    "run-fixed-suite": (
        "Capture ONE fixed bounded pytest suite in non-OIDC job",
        "Transfer exact execution artifact to isolated attestation job",
    ),
    "sign-only": (
        "Authenticate the artifact with GitHub Actions OIDC",
    ),
    "verify-attested": (
        "Validate executor schema before reading external signatures",
        "Verify signed GitHub origin and exact supervisor output",
        "Modified execution record must fail closed",
    ),
}
MAX_RESPONSE_BYTES = 160_000
MAX_JOBS = 20
MAX_STEPS = 50


def _json_object(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise HumanVerificationError("Invalid bounded GitHub API response")
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise HumanVerificationError("Duplicate GitHub API JSON key")
            value[k] = v
        return value
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              HumanVerificationError("Nonfinite GitHub API data")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HumanVerificationError("GitHub API returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise HumanVerificationError("GitHub API response must be JSON object")
    return data


def _identity(repo, repo_id, sha, run_id, attempt):
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or type(repo_id) is not int or repo_id <= 0
            or not isinstance(sha, str) or not SHA1.fullmatch(sha)
            or type(run_id) is not int or run_id < 1
            or type(attempt) is not int or attempt < 1):
        raise HumanVerificationError("Explicit numeric repository, source and run identity required")


def _check_run(run, *, repo, repo_id, sha, run_id, attempt):
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    if (run.get("id") != run_id or run.get("run_attempt") != attempt
            or run.get("head_sha") != sha
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("event") not in ("push", "workflow_dispatch")
            or not isinstance(repository, dict)
            or repository.get("id") != repo_id
            or repository.get("full_name") != repo
            or not isinstance(head_repository, dict)
            or head_repository.get("id") != repo_id
            or not isinstance(run.get("path"), str)
            or run["path"].split("@", 1)[0] != WORKFLOW
            or type(run.get("workflow_id")) is not int
            or run["workflow_id"] <= 0):
        raise HumanVerificationError("GitHub run status, workflow, repository or source does not match")
    return run["workflow_id"]


def _check_jobs(jobs, *, run_id, attempt):
    if (not isinstance(jobs, dict) or type(jobs.get("total_count")) is not int
            or jobs["total_count"] != len(JOB_NAMES)
            or not isinstance(jobs.get("jobs"), list)
            or len(jobs["jobs"]) != len(JOB_NAMES)
            or len(jobs["jobs"]) > MAX_JOBS):
        raise HumanVerificationError("Incomplete, paginated, or unexpected GitHub workflow jobs")
    found = {}
    ids = set()
    for job in jobs["jobs"]:
        if not isinstance(job, dict):
            raise HumanVerificationError("Invalid GitHub job record")
        name, jid = job.get("name"), job.get("id")
        if (name not in JOB_NAMES or name in found
                or type(jid) is not int or jid <= 0 or jid in ids
                or job.get("run_id") != run_id
                or job.get("run_attempt") != attempt
                or job.get("status") != "completed"
                or job.get("conclusion") != "success"
                or not isinstance(job.get("labels"), list)
                or "ubuntu-latest" not in job["labels"]
                or job.get("runner_environment") not in (None, "github-hosted")):
            raise HumanVerificationError("GitHub job is unexpected, incomplete, failed or self-hosted")
        steps = job.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise HumanVerificationError("GitHub job is missing step evidence")
        names = set()
        for step in steps:
            if (not isinstance(step, dict)
                    or not isinstance(step.get("name"), str)
                    or step["name"] in names
                    or step.get("status") != "completed"
                    or step.get("conclusion") != "success"):
                raise HumanVerificationError("GitHub job has missing, duplicate or unsuccessful steps")
            names.add(step["name"])
        if not set(REQUIRED_STEPS[name]) <= names:
            raise HumanVerificationError("Required supervised test/signing/verification step absent")
        found[name] = {"job_id": jid, "required_steps": list(REQUIRED_STEPS[name]),
                       "github_reported_status": "success"}
        ids.add(jid)
    if set(found) != set(JOB_NAMES):
        raise HumanVerificationError("GitHub workflow lacks required independent jobs")
    return {key: found[key] for key in JOB_NAMES}


def verify_github_job_responses(run: dict, jobs: dict, *,
                                expected_repo: str, expected_repo_id: int,
                                expected_commit: str, expected_run_id: int,
                                expected_attempt: int) -> dict:
    """Pure policy checker; inputs must come from the authenticated host fetch.

    This function by itself does NOT authenticate passed JSON dictionaries.
    Production callers MUST use verify_live_github_jobs().
    """
    _identity(expected_repo, expected_repo_id, expected_commit,
              expected_run_id, expected_attempt)
    workflow_id = _check_run(
        run, repo=expected_repo, repo_id=expected_repo_id,
        sha=expected_commit, run_id=expected_run_id,
        attempt=expected_attempt)
    validated = _check_jobs(jobs, run_id=expected_run_id,
                            attempt=expected_attempt)
    return {
        "format": FORMAT, "status": "github_api_run_and_jobs_verified",
        "repository": expected_repo, "repository_numeric_id": expected_repo_id,
        "source_commit": expected_commit, "workflow_path": WORKFLOW,
        "workflow_id": workflow_id, "run_id": expected_run_id,
        "run_attempt": expected_attempt, "jobs": validated,
        "github_reported_run_conclusion": "success",
        "api_authentication": "requires_live_gh_cli_fetch_in_production",
        "cryptographic_job_status_signature": False,
        "test_outcome_proven": False, "merge_action": "none",
        "github_publication": "none",
    }


def verify_live_github_jobs(*, gh_binary: Path, gh_binary_sha256: str,
                            expected_repo: str, expected_repo_id: int,
                            expected_commit: str, expected_run_id: int,
                            expected_attempt: int, api_token: str,
                            timeout: int = 20) -> dict:
    """Query GitHub twice over authenticated TLS, checking exact attempt and jobs.

    No network sandbox is provided; trusted CLI installation and host TLS store
    remain part of the operator's trust boundary. Access token is never logged.
    """
    _identity(expected_repo, expected_repo_id, expected_commit,
              expected_run_id, expected_attempt)
    if (not isinstance(api_token, str) or not 12 <= len(api_token) <= 2048
            or "\n" in api_token or "\r" in api_token
            or type(timeout) is not int or not 1 <= timeout <= 60):
        raise HumanVerificationError("A bounded explicit GitHub read token is required")
    binary = _verified_executable(gh_binary, gh_binary_sha256)
    base = f"/repos/{expected_repo}/actions/runs/{expected_run_id}/attempts/{expected_attempt}"
    paths = (base, base + "/jobs?per_page=100&page=1")
    with tempfile.TemporaryDirectory(prefix="daddy-gh-jobs-") as scratch:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": scratch, "GH_CONFIG_DIR": scratch,
            "GH_HOST": "github.com", "GH_TOKEN": api_token,
            "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
        }
        # No custom API hosts, proxy environment, shell, repos or model data.
        responses = []
        for path in paths:
            argv = [str(binary), "api", "--method", "GET",
                    "-H", "Accept: application/vnd.github+json", path]
            try:
                process = subprocess.run(
                    argv, capture_output=True, check=False,
                    timeout=timeout, env=env)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise HumanVerificationError("Live GitHub job status request failed") from exc
            if process.returncode != 0:
                raise HumanVerificationError("GitHub API did not authenticate or return a successful response")
            responses.append(_json_object(process.stdout))
    _verified_executable(gh_binary, gh_binary_sha256)
    checked = verify_github_job_responses(
        responses[0], responses[1], expected_repo=expected_repo,
        expected_repo_id=expected_repo_id, expected_commit=expected_commit,
        expected_run_id=expected_run_id, expected_attempt=expected_attempt)
    checked["api_authentication"] = "live_GitHub_REST_via_token_and_TLS"
    return checked
