"""R8.06a — read-only, exact-source GitHub PR intake with bounded API responses.

A pull request is *untrusted input*. We independently obtain its data over
authenticated read-only GitHub REST GET requests; a pinned locally checked
out PR HEAD is required. Never use this module for approval, merge or posting.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from time import perf_counter_ns

from .bounded_exec import run_bounded
from .diff import DiffError, parse_diff
from .github_attestation import _verified_executable
from .human_attestation import HumanVerificationError
from .ops_readiness import pinned_local_head
from .ops_telemetry import OperationalError
from .review import review_patch
from .real_repository_intake import _output_path

FORMAT = "daddy-reviews-pr-pilot-summary-v1"
PRIVATE_FORMAT = "daddy-reviews-pr-pilot-private-report-v1"
REPO = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
PATH_LIMIT = 400
MAX_PR_FILES = 40
MAX_PATCH_BYTES = 262144
PAGE_LIMIT = 4
PER_PAGE = 10


class PilotError(ValueError):
    """Live PR intake rejected or source could not be independently pinned."""


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise PilotError("Duplicate GitHub PR JSON field")
        obj[k] = v
    return obj


def _decode(raw: bytes, expected):
    if not isinstance(raw, bytes) or not raw or len(raw) > 65536:
        raise PilotError("Oversized or empty GitHub PR API data")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               PilotError("Nonfinite GitHub API data")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PilotError("Malformed authenticated GitHub API data") from exc
    if not isinstance(value, expected):
        raise PilotError("GitHub API response had unexpected type")
    return value


def _safe_name(name):
    return (isinstance(name, str) and 1 <= len(name) <= PATH_LIMIT
            and not name.startswith("/") and "\\" not in name
            and all(part not in ("", ".", "..") for part in name.split("/"))
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in name))


def _identity(repo, repo_id, number, head):
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or ".." in repo
            or type(repo_id) is not int or repo_id <= 0
            or type(number) is not int or not 1 <= number <= 1_000_000_000
            or not isinstance(head, str) or not SHA.fullmatch(head)):
        raise PilotError("Invalid explicit PR target, source revision or repository ID")


def _pr_identity(pr, *, repo, repo_id, number, head):
    if not isinstance(pr, dict):
        raise PilotError("Incomplete PR metadata")
    base = pr.get("base")
    source = pr.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (type(pr.get("number")) is not int or pr["number"] != number
            or pr.get("state") != "open"
            or not isinstance(base, dict) or not isinstance(source, dict)
            or not isinstance(base_repo, dict)
            or type(base_repo.get("id")) is not int
            or base_repo["id"] != repo_id or base_repo.get("full_name") != repo
            or source.get("sha") != head
            or not isinstance(base.get("sha"), str)
            or not SHA.fullmatch(base["sha"])
            or type(pr.get("changed_files")) is not int
            or not 1 <= pr["changed_files"] <= MAX_PR_FILES):
        raise PilotError("PR open state, base identity, head SHA or file budget mismatched")
    return base["sha"], pr["changed_files"]


def _quote(p):
    return shlex.quote(p)


def _patch_from_files(files):
    if (not isinstance(files, list)
            or not 1 <= len(files) <= MAX_PR_FILES):
        raise PilotError("PR file list incomplete or too large")
    seen = set()
    chunks = []
    added = removed = 0
    for item in files:
        if not isinstance(item, dict):
            raise PilotError("Malformed PR file entry")
        path = item.get("filename")
        previous = item.get("previous_filename")
        status = item.get("status")
        patch = item.get("patch")
        if not _safe_name(path) or path in seen:
            raise PilotError("Unsafe, missing or duplicated PR path")
        seen.add(path)
        if status not in ("added", "removed", "modified", "renamed"):
            raise PilotError("Unsupported PR file operation")
        if status == "renamed" and not _safe_name(previous):
            raise PilotError("Renamed file source path missing")
        if not isinstance(patch, str) or not patch.startswith("@@"):
            # Binary files, very large/truncated patches and zero-line renames
            # are all abstentions, never counted as successfully reviewed.
            raise PilotError("PR file has missing, binary or truncated patch; abstain")
        if type(item.get("additions")) is not int or type(item.get("deletions")) is not int:
            raise PilotError("Missing GitHub per-file change counts")
        if item["additions"] < 0 or item["deletions"] < 0:
            raise PilotError("Negative GitHub per-file line counts")
        prior = previous if status == "renamed" else path
        new_path = path
        pre = "/dev/null" if status == "added" else "a/" + prior
        post = "/dev/null" if status == "removed" else "b/" + new_path
        flags = ("new file mode 100644\n" if status == "added"
                 else "deleted file mode 100644\n" if status == "removed"
                 else ("rename from " + _quote(prior) + "\n"
                       + "rename to " + _quote(new_path) + "\n") if status == "renamed"
                 else "")
        chunk = (
            "diff --git " + _quote("a/" + prior) + " "
            + _quote("b/" + new_path) + "\n" + flags
            + "--- " + _quote(pre) + "\n"
            + "+++ " + _quote(post) + "\n"
            + patch.rstrip("\n") + "\n"
        )
        try:
            parsed = parse_diff(chunk)
        except DiffError as exc:
            raise PilotError("PR file patch failed deterministic parsing") from exc
        if (len(parsed) != 1
                or len(parsed[0].added_lines) != item["additions"]
                or len(parsed[0].deleted_lines) != item["deletions"]):
            raise PilotError("PR API patch truncated or inconsistent with line counts")
        added += item["additions"]
        removed += item["deletions"]
        chunks.append(chunk)
    assembled = "".join(chunks)
    if len(assembled.encode("utf-8")) > MAX_PATCH_BYTES:
        raise PilotError("Combined PR patch exceeds safe processing budget")
    return assembled, added, removed


def _live_api(binary, token, repo, number, *, timeout, gh_env):
    """Generate bounded authenticated GETs only; no model-suggested URLs."""
    root = f"/repos/{repo}/pulls/{number}"
    def query(path, expected):
        result = run_bounded(
            [str(binary), "api", "--method", "GET",
             "-H", "Accept: application/vnd.github+json", path],
            cwd=Path(gh_env["HOME"]), env=gh_env,
            timeout=timeout, max_output=65536)
        if result.returncode != 0 or not result.output_complete or result.timeout_expired:
            raise PilotError("Authenticated read-only GitHub API request failed or exceeded budget")
        return _decode(result.stdout, expected)

    first = query(root, dict)
    files = []
    for page in range(1, PAGE_LIMIT + 1):
        batch = query(root + f"/files?per_page={PER_PAGE}&page={page}", list)
        if len(batch) > PER_PAGE:
            raise PilotError("GitHub PR pagination exceeded requested page size")
        files.extend(batch)
        if len(files) > MAX_PR_FILES:
            raise PilotError("PR file budget exceeded")
        if len(batch) < PER_PAGE:
            break
    else:
        raise PilotError("PR pagination has no independently checked final page")
    last = query(root, dict)  # TOCTOU check after reading all files
    return first, files, last


def capture_live_pr(*, root: Path, repository: str, repository_id: int,
                    number: int, expected_head: str, token: str,
                    gh_binary: Path, gh_binary_sha256: str,
                    timeout: int = 20):
    """Returns safe public summary plus private evidence packet (never posted)."""
    _identity(repository, repository_id, number, expected_head)
    if (not isinstance(token, str) or not 12 <= len(token) <= 2048
            or "\n" in token or "\r" in token
            or type(timeout) is not int or not 1 <= timeout <= 40):
        raise PilotError("Explicit read-only GitHub token and bounded timeout required")
    if pinned_local_head(root) != expected_head:
        raise PilotError("Local reviewed checkout HEAD does not match pinned PR commit")
    try:
        binary = _verified_executable(gh_binary, gh_binary_sha256)
    except HumanVerificationError as exc:
        raise PilotError("SHA-256-pinned GitHub CLI not verified") from exc
    with tempfile.TemporaryDirectory(prefix="daddy-pr-pilot-") as home:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home, "GH_CONFIG_DIR": home, "GH_HOST": "github.com",
            "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
        }
        first, files, last = _live_api(
            binary, token, repository, number, timeout=timeout, gh_env=env)
    before_base, expected_files = _pr_identity(
        first, repo=repository, repo_id=repository_id,
        number=number, head=expected_head)
    after_base, after_files = _pr_identity(
        last, repo=repository, repo_id=repository_id,
        number=number, head=expected_head)
    if before_base != after_base or expected_files != after_files or len(files) != expected_files:
        raise PilotError("PR source, changed-file count or base changed during capture")
    if pinned_local_head(root) != expected_head:
        raise PilotError("Local source HEAD moved during PR intake")
    patch, added, removed = _patch_from_files(files)
    started = perf_counter_ns()
    report = review_patch(root, patch)
    review_elapsed_ms = max(0, round((perf_counter_ns() - started) / 1_000_000))
    if review_elapsed_ms > 120000:
        raise PilotError("PR review exceeded advisory two-minute processing budget")
    patch_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    # No free-form finding, source, filepath or comment is shared publicly.
    summary = {
        "format": FORMAT, "status": "advisory_source_read_verified",
        "repository": repository,
        "repository_numeric_id": repository_id,
        "pr_number": number, "head_commit": expected_head,
        "base_commit": before_base, "patch_sha256": patch_sha,
        "changed_file_count": len(files),
        "added_lines": added, "deleted_lines": removed,
        "candidate_findings": len(report.get("findings", [])),
        "review_elapsed_ms": review_elapsed_ms,
        "verified_defects": 0,  # no independently adjudicated labels were read
        "coverage": "bounded_complete_textual_patch",
        "github_read_only": True, "model_used": False,
        "human_findings_verified": False, "human_review_required": True,
        "pr_comments_posted": 0, "merge_action": "none",
        "production_approval_granted": False,
        "source_text_in_summary": False,
        "retrieval_method": "authenticated_github_get_and_exact_local_commit",
    }
    private = {
        "format": PRIVATE_FORMAT, "summary": summary,
        "review_packet": report,
        "source_text_trust": "untrusted_pull_request",
        "github_writes": [],
        "merge_action": "none",
    }
    return {"summary": summary, "private": private}


def write_private_pilot_report(path: Path, report: dict) -> dict:
    """Save full PR evidence locally for a human, NEVER as a CI artifact."""
    if (not isinstance(report, dict)
            or report.get("format") != PRIVATE_FORMAT
            or not isinstance(report.get("review_packet"), dict)
            or not isinstance(report.get("summary"), dict)):
        raise PilotError("Invalid private PR review payload")
    destination = _output_path(path)
    blob = (json.dumps(report, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if len(blob) > 2_000_000:
        raise PilotError("Private PR report exceeds local storage budget")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        fd = os.open(destination, flags, 0o600)
        created = True
        with os.fdopen(fd, "wb") as out:
            out.write(blob)
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        if created:
            destination.unlink(missing_ok=True)
        raise PilotError("Failed to exclusively save private PR review") from exc
    return {
        "private_evidence_saved": True,
        "private_evidence_sha256": hashlib.sha256(blob).hexdigest(),
        "private_evidence_not_published": True,
    }
