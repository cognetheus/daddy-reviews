"""R8.04k.01 — independent GitHub Actions run timestamps for a registered study.

GitHub server timestamps and the exact workflow run display title are checked
via a SHA-256-pinned gh CLI using read-only authenticated REST. No model code,
reviewed tests, GitHub writes, or shell commands are executed by this module.
A GitHub actor ID is an account, NOT proof of an independent human.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .github_job_status import _json_object, _verified_executable
from .human_attestation import HumanVerificationError, sha256_json
from .study_protocol import PLAN_FORMAT, RECORD_FORMAT, REGISTRATION_FORMAT, _utc

FORMAT = "daddy-reviews-github-study-chronology-v1"
MANIFEST = "daddy-reviews-github-study-anchor-manifest-v1"
RECEIPT = "daddy-reviews-study-reviewer-receipt-v1"
ENROLLMENT = "daddy-reviews-study-github-enrollment-v1"
WORKFLOW_PATH = ".github/workflows/study-evidence-anchor.yml"
RUN_NAME = "Daddy Study Anchor"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
BRANCH = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
TOKEN_MAX = 2048


def reviewer_receipt_sha256(plan: dict, labels: list, reviewer_id: str) -> str:
    """Commit to all of ONE enrolled researcher's signed label records.

    These SHA-256 receipts are safe to display in GitHub Actions titles,
    unlike case text, model findings, signing keys or evidence bytes.
    """
    if (not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT
            or not isinstance(labels, list) or len(labels) > 320
            or not isinstance(reviewer_id, str)
            or reviewer_id not in plan.get("frozen_reviewer_ids", [])):
        raise HumanVerificationError("Invalid signed-label bundle for enrolled researcher")
    case_ids = {item["case_id"] for item in plan["cases"]}
    mine = [rec for rec in labels if isinstance(rec, dict)
            and rec.get("reviewer_id") == reviewer_id]
    if (len(mine) != len(case_ids)
            or {rec.get("case_id") for rec in mine} != case_ids
            or any(rec.get("format") != RECORD_FORMAT
                   or rec.get("study_plan_sha256") != sha256_json(plan)
                   or rec.get("head_commit") != plan["head_commit"]
                   or not isinstance(rec.get("signature_b64"), str)
                   or len(rec["signature_b64"]) < 64
                   for rec in mine)):
        raise HumanVerificationError("Incomplete, duplicate or source-mismatched reviewer bundle")
    return sha256_json({
        "format": RECEIPT, "study_plan_sha256": sha256_json(plan),
        "reviewer_id": reviewer_id,
        "observations": sorted(mine, key=lambda item: item["case_id"]),
    })


def _run_identity(value, *, role: str):
    if (not isinstance(value, dict)
            or set(value) != ({"run_id", "actor_id", "head_sha"}
                              if role == "registration" else
                              {"reviewer_id", "run_id", "actor_id", "head_sha"})
            or type(value.get("run_id")) is not int or value["run_id"] <= 0
            or type(value.get("actor_id")) is not int or value["actor_id"] <= 0
            or not isinstance(value.get("head_sha"), str)
            or not SHA1.fullmatch(value["head_sha"])):
        raise HumanVerificationError("Invalid pinned Actions run, actor or workflow commit")
    return value


def _manifest(manifest: dict, plan: dict, *, expected_registration_sha256: str, require_reviewers: bool):
    if (not isinstance(manifest, dict)
            or set(manifest) != {
                "format", "anchor_repository", "anchor_repository_id",
                "workflow_id", "head_branch", "enrollment", "registration", "reviewers"}
            or manifest.get("format") != MANIFEST
            or not isinstance(manifest.get("anchor_repository"), str)
            or not REPO.fullmatch(manifest["anchor_repository"])
            or type(manifest.get("anchor_repository_id")) is not int
            or manifest["anchor_repository_id"] <= 0
            or type(manifest.get("workflow_id")) is not int
            or manifest["workflow_id"] <= 0
            or not isinstance(manifest.get("head_branch"), str)
            or not BRANCH.fullmatch(manifest["head_branch"])
            or not isinstance(manifest.get("reviewers"), list)
            or len(manifest["reviewers"]) not in (0, 2)):
        raise HumanVerificationError("Invalid GitHub study anchor manifest")
    registration = _run_identity(manifest["registration"], role="registration")
    enrollment = manifest.get("enrollment")
    if (not isinstance(enrollment, dict)
            or set(enrollment) != {
                "format", "study_registration_sha256", "registrar_actor_id",
                "reviewer_actors"}
            or enrollment["format"] != ENROLLMENT
            or enrollment["study_registration_sha256"] != expected_registration_sha256
            or type(enrollment["registrar_actor_id"]) is not int
            or enrollment["registrar_actor_id"] <= 0
            or enrollment["registrar_actor_id"] != registration["actor_id"]
            or not isinstance(enrollment["reviewer_actors"], list)
            or len(enrollment["reviewer_actors"]) != 2):
        raise HumanVerificationError("No precommitted registrar and two reviewer GitHub accounts")
    expected_actors = {}
    for item in enrollment["reviewer_actors"]:
        if (not isinstance(item, dict)
                or set(item) != {"reviewer_id", "actor_id"}
                or not isinstance(item["reviewer_id"], str)
                or type(item["actor_id"]) is not int
                or item["actor_id"] <= 0
                or item["reviewer_id"] in expected_actors):
            raise HumanVerificationError("Malformed precommitted reviewer GitHub identities")
        expected_actors[item["reviewer_id"]] = item["actor_id"]
    if (sorted(expected_actors) != plan.get("frozen_reviewer_ids")
            or len(set(expected_actors.values())) != 2
            or enrollment["registrar_actor_id"] in expected_actors.values()):
        raise HumanVerificationError("Enrollment does not bind the frozen independent reviewer roster")
    reviewers = manifest["reviewers"]
    if not isinstance(plan.get("frozen_reviewer_ids"), list) or len(plan["frozen_reviewer_ids"]) != 2:
        raise HumanVerificationError("No frozen two-reviewer study roster")
    if require_reviewers and len(reviewers) != 2:
        raise HumanVerificationError("Chronology requires two separately pinned reviewer runs")
    if reviewers:
        for item in reviewers:
            _run_identity(item, role="reviewer")
        if (sorted(item["reviewer_id"] for item in reviewers)
                != plan["frozen_reviewer_ids"]
                or len({item["actor_id"] for item in reviewers}) != 2
                or any(item["actor_id"] != expected_actors[item["reviewer_id"]]
                       for item in reviewers)
                or any(item["actor_id"] == registration["actor_id"] for item in reviewers)):
            raise HumanVerificationError("GitHub identities violate frozen independent enrollment")
    anchors = [registration, *reviewers]
    if len({item["run_id"] for item in anchors}) != len(anchors):
        raise HumanVerificationError("Reused GitHub workflow run as different study receipts")
    return reviewers


def _verify_run(run: dict, *, manifest: dict, entry: dict,
                expected_kind: str, registration_hash: str,
                payload_sha: str) -> datetime:
    repo = manifest["anchor_repository"]
    repo_id = manifest["anchor_repository_id"]
    title = f"{RUN_NAME} | {expected_kind} | {registration_hash} | {payload_sha}"
    if not isinstance(run, dict):
        raise HumanVerificationError("GitHub study anchor must be a JSON object")
    parent = run.get("repository")
    head = run.get("head_repository")
    actor = run.get("actor")
    triggering = run.get("triggering_actor")
    if (not isinstance(run, dict)
            or type(run.get("id")) is not int or run["id"] != entry["run_id"]
            or type(run.get("run_attempt")) is not int
            or run["run_attempt"] != 1
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("event") != "workflow_dispatch"
            or type(run.get("workflow_id")) is not int
            or run["workflow_id"] != manifest["workflow_id"]
            or run.get("head_sha") != entry["head_sha"]
            or run.get("head_branch") != manifest["head_branch"]
            or not isinstance(run.get("path"), str)
            or run["path"].split("@", 1)[0] != WORKFLOW_PATH
            or run.get("display_title") != title
            or not isinstance(parent, dict)
            or type(parent.get("id")) is not int
            or parent["id"] != repo_id or parent.get("full_name") != repo
            or not isinstance(head, dict)
            or type(head.get("id")) is not int
            or head["id"] != repo_id
            or not isinstance(actor, dict)
            or type(actor.get("id")) is not int
            or actor["id"] != entry["actor_id"]
            or actor.get("type") != "User"
            or not isinstance(triggering, dict)
            or type(triggering.get("id")) is not int
            or triggering["id"] != entry["actor_id"]):
        raise HumanVerificationError("GitHub server run identity, signer or exact study commitment mismatched")
    timestamp = _utc(run.get("created_at"))
    if timestamp > datetime.now(timezone.utc).replace(microsecond=0):
        raise HumanVerificationError("GitHub server timestamp is in the future")
    return timestamp


def verify_study_anchor_responses(*, registration: dict, labels: list,
                                  anchor_manifest: dict, runs: list,
                                  expected_registration_sha256: str,
                                  require_reviewers: bool = False) -> dict:
    """Pure policy checker; NEVER treat caller-supplied run JSON as authenticated.

    For production, use verify_live_study_anchors(), which obtains all runs
    directly from the GitHub REST API over TLS.
    """
    if (not isinstance(registration, dict)
            or registration.get("format") != REGISTRATION_FORMAT
            or not isinstance(registration.get("plan"), dict)
            or not isinstance(expected_registration_sha256, str)
            or not SHA256.fullmatch(expected_registration_sha256)
            or sha256_json(registration) != expected_registration_sha256):
        raise HumanVerificationError("Registration does not match independently pinned digest")
    plan = registration["plan"]
    if plan.get("format") != PLAN_FORMAT:
        raise HumanVerificationError("Invalid signed study plan in registry")
    reviewers = _manifest(anchor_manifest, plan,
                          expected_registration_sha256=expected_registration_sha256,
                          require_reviewers=require_reviewers)
    expected_runs = [anchor_manifest["registration"], *reviewers]
    if not isinstance(runs, list) or len(runs) != len(expected_runs):
        raise HumanVerificationError("Incomplete GitHub Actions chronology response set")
    if not isinstance(labels, list) or len(labels) > 320 or any(
            not isinstance(item, dict) for item in labels):
        raise HumanVerificationError("Study observations are invalid")
    if not require_reviewers and reviewers:
        raise HumanVerificationError(
            "Registration-only validation must not silently accept unverified reviewer runs")
    when = []
    committed = []
    for index, (entry, run) in enumerate(zip(expected_runs, runs)):
        kind = "registration" if index == 0 else "reviewer"
        payload = (
            sha256_json(anchor_manifest["enrollment"])
            if index == 0 else reviewer_receipt_sha256(
                plan, labels, entry["reviewer_id"]))
        timestamp = _verify_run(
            run, manifest=anchor_manifest, entry=entry,
            expected_kind=kind, registration_hash=expected_registration_sha256,
            payload_sha=payload)
        when.append(timestamp)
        committed.append({
            "run_id": entry["run_id"],
            "actor_numeric_id": entry["actor_id"],
            "kind": kind,
            "reviewer_id": entry.get("reviewer_id"),
            "payload_sha256": payload,
            "github_created_at": timestamp.isoformat().replace("+00:00", "Z"),
            "github_run_conclusion": "success",
        })
    if require_reviewers and any(
            item.get("reviewer_id") not in plan["frozen_reviewer_ids"]
            for item in labels):
        raise HumanVerificationError("Unexpected or additional reviewer observations")
    for index, entry in enumerate(reviewers, start=1):
        if when[index] <= when[0]:
            raise HumanVerificationError("Researcher receipt is not strictly later than registration")
        for record in labels:
            if record.get("reviewer_id") == entry["reviewer_id"]:
                observed = _utc(record.get("signed_at"))
                if observed < when[0] or observed > when[index]:
                    raise HumanVerificationError(
                        "Claimed observation timestamp is inconsistent with GitHub registration and receipt")
    return {
        "format": FORMAT,
        "status": ("github_registration_and_two_receipts_matched"
                   if require_reviewers else "github_registration_anchor_matched"),
        "repository": anchor_manifest["anchor_repository"],
        "repository_numeric_id": anchor_manifest["anchor_repository_id"],
        "workflow_id": anchor_manifest["workflow_id"],
        "registration_sha256": expected_registration_sha256,
        "server_observed_commitments": committed,
        "github_hosted_chronological_order_verified": bool(require_reviewers),
        "externally_authenticated_GitHub_run_metadata": False,
        "human_identity_independently_proven": False,
        "actual_blinding_proven": False,
        "defect_truth_proven": False, "quality_promotion_authorized": False,
        "github_publication": "none", "merge_action": "none",
    }


def verify_live_study_anchors(*, gh_binary: Path, gh_binary_sha256: str,
                              api_token: str, registration: dict, labels: list,
                              anchor_manifest: dict,
                              expected_registration_sha256: str,
                              require_reviewers: bool = False,
                              timeout: int = 20) -> dict:
    """Authenticated GET only. No model, code execution, shell or GH writes."""
    if (not isinstance(api_token, str) or not 12 <= len(api_token) <= TOKEN_MAX
            or "\r" in api_token or "\n" in api_token
            or type(timeout) is not int or not 1 <= timeout <= 45):
        raise HumanVerificationError("Explicit bounded read-only GitHub token required")
    if (not isinstance(registration, dict)
            or not isinstance(registration.get("plan"), dict)
            or not isinstance(expected_registration_sha256, str)
            or not SHA256.fullmatch(expected_registration_sha256)
            or sha256_json(registration) != expected_registration_sha256):
        raise HumanVerificationError("Signed registration hash not independently pinned")
    reviewers = _manifest(anchor_manifest, registration["plan"],
                          expected_registration_sha256=expected_registration_sha256,
                          require_reviewers=require_reviewers)
    binary = _verified_executable(gh_binary, gh_binary_sha256)
    repo = anchor_manifest["anchor_repository"]
    entries = [anchor_manifest["registration"], *reviewers]
    responses = []
    with tempfile.TemporaryDirectory(prefix="daddy-study-anchor-") as scratch:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": scratch, "GH_CONFIG_DIR": scratch, "GH_HOST": "github.com",
            "GH_TOKEN": api_token, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1",
        }
        for entry in entries:
            path = f"/repos/{repo}/actions/runs/{entry['run_id']}"
            try:
                proc = subprocess.run(
                    [str(binary), "api", "--method", "GET",
                     "-H", "Accept: application/vnd.github+json", path],
                    capture_output=True, check=False, env=env, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise HumanVerificationError("GitHub study anchor lookup failed") from exc
            if proc.returncode != 0:
                raise HumanVerificationError("GitHub study anchor unavailable or unauthenticated")
            responses.append(_json_object(proc.stdout))
    _verified_executable(gh_binary, gh_binary_sha256)
    result = verify_study_anchor_responses(
        registration=registration, labels=labels, anchor_manifest=anchor_manifest,
        runs=responses, expected_registration_sha256=expected_registration_sha256,
        require_reviewers=require_reviewers)
    result["externally_authenticated_GitHub_run_metadata"] = True
    return result
