"""R8.05b: independent, fail-closed GitHub production branch governance.

A release must not be promoted merely because unit tests passed or a caller
provided JSON claiming branch protection. Only a live authenticated GitHub
API response through an operator SHA-256-pinned gh executable counts as
externally observed configuration. This module NEVER changes repository
settings, merges PRs or publishes reviews.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile

from .github_attestation import _verified_executable
from .github_job_status import _json_object
from .human_attestation import HumanVerificationError

FORMAT = "daddy-reviews-branch-governance-v1"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
BRANCH = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
REQUIRED_CHECKS = ("test (3.10)", "test (3.12)", "test (3.13)")
MAX_TOKEN_BYTES = 2048


def _identity(repo, repo_id, branch, commit):
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or type(repo_id) is not int or repo_id <= 0
            or not isinstance(branch, str) or not BRANCH.fullmatch(branch)
            or not isinstance(commit, str) or not SHA.fullmatch(commit)):
        raise HumanVerificationError(
            "Explicit immutable GitHub repo ID, source commit and safe protected branch required")


def _enabled(value):
    return isinstance(value, dict) and value.get("enabled") is True


def _disabled(value):
    return isinstance(value, dict) and value.get("enabled") is False


def assess_branch_governance(repo_data: dict | None, branch_data: dict | None,
                             protection: dict | None, *,
                             expected_repo: str, expected_repo_id: int,
                             expected_branch: str, expected_commit: str,
                             protection_fetch_error: str | None = None) -> dict:
    """Pure policy checker. Caller-supplied objects are NOT authenticated.

    The live wrapper must fetch GitHub data using a token/TLS before setting
    github_api_authenticated=True. Missing/403 protection is always blocked.
    """
    _identity(expected_repo, expected_repo_id, expected_branch, expected_commit)
    failures = []
    if (not isinstance(repo_data, dict)
            or type(repo_data.get("id")) is not int
            or repo_data.get("id") != expected_repo_id
            or repo_data.get("full_name") != expected_repo
            or repo_data.get("default_branch") != expected_branch
            or repo_data.get("archived") is not False
            or repo_data.get("disabled") is not False):
        failures.append("repository_identity_or_state_unverified")
    if (not isinstance(branch_data, dict)
            or branch_data.get("name") != expected_branch
            or not isinstance(branch_data.get("commit"), dict)
            or branch_data["commit"].get("sha") != expected_commit
            or branch_data.get("protected") is not True):
        failures.append("branch_commit_or_protected_flag_unverified")
    if not isinstance(protection, dict):
        failures.append("branch_protection_not_accessible_or_not_configured")
    else:
        reviews = protection.get("required_pull_request_reviews")
        statuses = protection.get("required_status_checks")
        contexts = set()
        if isinstance(statuses, dict):
            for context in statuses.get("contexts", []):
                if isinstance(context, str):
                    contexts.add(context)
            for check in statuses.get("checks", []):
                if isinstance(check, dict) and isinstance(check.get("context"), str):
                    contexts.add(check["context"])
        if not (isinstance(statuses, dict) and statuses.get("strict") is True
                and set(REQUIRED_CHECKS) <= contexts):
            failures.append("required_up_to_date_ci_matrix_missing")
        if not (isinstance(reviews, dict)
                and type(reviews.get("required_approving_review_count")) is int
                and reviews["required_approving_review_count"] >= 2
                and reviews.get("dismiss_stale_reviews") is True
                and reviews.get("require_code_owner_reviews") is True):
            failures.append("two_reviewers_stale_dismissal_or_code_owners_missing")
        if not _enabled(protection.get("enforce_admins")):
            failures.append("administrator_bypass_not_prevented")
        if not _enabled(protection.get("required_conversation_resolution")):
            failures.append("unresolved_conversations_not_blocked")
        if not _disabled(protection.get("allow_force_pushes")):
            failures.append("force_pushes_not_explicitly_disabled")
        if not _disabled(protection.get("allow_deletions")):
            failures.append("branch_deletion_not_explicitly_disabled")
        if _enabled(protection.get("lock_branch")):
            failures.append("branch_locked_from_normal_release_flow")
    return {
        "format": FORMAT,
        "status": ("branch_policy_valid_in_untrusted_input"
                   if not failures else "blocked_branch_security_gate"),
        "repository": expected_repo, "repository_numeric_id": expected_repo_id,
        "branch": expected_branch, "source_commit": expected_commit,
        "required_ci_checks": list(REQUIRED_CHECKS),
        "security_gaps": sorted(set(failures)),
        "protection_fetch_error": protection_fetch_error,
        "github_api_authenticated": False,
        "branch_policy_verified": False,
        "release_authorized": False, "model_quality_approved": False,
        "human_signoff_required": True, "merge_action": "none",
        "github_publication": "none",
    }


def verify_live_branch_governance(*, gh_binary: Path, gh_binary_sha256: str,
                                  api_token: str, expected_repo: str,
                                  expected_repo_id: int, expected_branch: str,
                                  expected_commit: str, timeout: int = 20) -> dict:
    """TLS authenticated read-only queries with explicit token and pinned CLI.

    A 403/404 protection response is reported as a **release blocker**, not
    hidden, inferred from repository rulesets, or treated as a success.
    """
    _identity(expected_repo, expected_repo_id, expected_branch, expected_commit)
    if (not isinstance(api_token, str)
            or not 12 <= len(api_token) <= MAX_TOKEN_BYTES
            or "\n" in api_token or "\r" in api_token
            or type(timeout) is not int or not 1 <= timeout <= 45):
        raise HumanVerificationError("Operator-controlled read-only GitHub token is required")
    binary = _verified_executable(gh_binary, gh_binary_sha256)
    paths = (
        f"/repos/{expected_repo}",
        f"/repos/{expected_repo}/branches/{expected_branch}",
        f"/repos/{expected_repo}/branches/{expected_branch}/protection",
    )
    values = []
    fetch_failure = None
    with tempfile.TemporaryDirectory(prefix="daddy-branch-governance-") as home:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home, "GH_CONFIG_DIR": home, "GH_HOST": "github.com",
            "GH_TOKEN": api_token, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
        }
        for index, api_path in enumerate(paths):
            try:
                process = subprocess.run(
                    [str(binary), "api", "--method", "GET",
                     "-H", "Accept: application/vnd.github+json", api_path],
                    capture_output=True, check=False, env=env, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise HumanVerificationError("GitHub branch policy API request unavailable") from exc
            if process.returncode != 0:
                values.append(None)
                if index != 2:
                    raise HumanVerificationError("Could not authenticate repository and branch metadata")
                fetch_failure = "GitHub branch protection denied/unavailable (403, 404 or API error)"
            else:
                values.append(_json_object(process.stdout))
    _verified_executable(gh_binary, gh_binary_sha256)
    result = assess_branch_governance(
        values[0], values[1], values[2],
        expected_repo=expected_repo, expected_repo_id=expected_repo_id,
        expected_branch=expected_branch, expected_commit=expected_commit,
        protection_fetch_error=fetch_failure)
    result["github_api_authenticated"] = True
    if not result["security_gaps"]:
        result["status"] = "authenticated_branch_policy_verified"
        result["branch_policy_verified"] = True
    return result
