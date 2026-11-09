"""R8.04f.01 — bounded supervised pytest evidence for a trusted CI workflow.

The capture command runs ONE built-in, repository-pinned pytest suite. It is
intended only for an isolated, protected GitHub-hosted runner. A captured exit
code is runner-reported evidence; an external signed artifact attests its
origin, not the honesty or immutability of workflow code.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .human_attestation import HumanVerificationError
from .operator_artifacts import _safe_regular_read

FORMAT = "daddy-reviews-supervised-test-execution-v1"
SUITE = "tests/test_human_quality.py"
SUITE_FILE_MAX = 64_000
MAX_OUTPUT = 15_000
MAX_ARTIFACT = 65_536
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
WORKFLOW = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml\Z")


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_identity(repository, commit, workflow, run_id, attempt):
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or not isinstance(commit, str) or not SHA1.fullmatch(commit)
            or not isinstance(workflow, str) or not WORKFLOW.fullmatch(workflow)
            or not workflow.startswith(repository + "/")
            or type(run_id) is not int or run_id < 1
            or type(attempt) is not int or attempt < 1):
        raise HumanVerificationError("Test executor needs pinned GitHub source and run identity")


def capture_fixed_ci_test(root: Path, *, repository: str, commit: str,
                          workflow: str, run_id: int, attempt: int,
                          timeout: int = 90) -> dict:
    """Invoke the fixed pytest suite; do not expose this as an operator review tool.

    Executes repository test code. Use only in an unprivileged isolated runner,
    not against untrusted pull-request source in a privileged attestation job.
    """
    _check_identity(repository, commit, workflow, run_id, attempt)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise HumanVerificationError("Test timeout out of bounds")
    root = Path(root).resolve(strict=True)
    suite = root / SUITE
    if suite.is_symlink() or not suite.is_file():
        raise HumanVerificationError("Required fixed test suite is missing")
    source = _safe_regular_read(suite, SUITE_FILE_MAX)
    if not source:
        raise HumanVerificationError("Empty fixed test suite")
    from time import monotonic
    start = _iso_now()
    clock = monotonic()
    command = [sys.executable, "-m", "pytest", "-q", SUITE]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GH_", "GITHUB_TOKEN", "GIT_"))
           and k not in ("AWS_SECRET_ACCESS_KEY", "AZURE_CLIENT_SECRET", "GOOGLE_APPLICATION_CREDENTIALS",
                         "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
                         "https_proxy", "all_proxy")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    try:
        proc = subprocess.run(command, cwd=root, capture_output=True, check=False,
                              timeout=timeout, env=env)
        exit_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    except OSError as exc:
        raise HumanVerificationError("Fixed test runner unavailable") from exc
    # Truncated output cannot attest an observed successful result.
    output_complete = len(stdout) <= MAX_OUTPUT and len(stderr) <= MAX_OUTPUT
    if not output_complete:
        stdout = stdout[:MAX_OUTPUT]
        stderr = stderr[:MAX_OUTPUT]
    end = _iso_now()
    record = {
        "format": FORMAT, "repository": repository, "source_commit": commit,
        "workflow": workflow, "run_id": run_id, "run_attempt": attempt,
        "suite": SUITE, "suite_sha256": _sha(source),
        "launcher": "python_module_pytest", "arguments": ["-q", SUITE],
        "timeout_seconds": timeout, "started_at": start, "finished_at": end,
        "elapsed_ms": round((monotonic() - clock) * 1000),
        "exit_code": exit_code,
        "output_complete": output_complete,
        "outcome": "passed" if exit_code == 0 and output_complete else "failed",
        "stdout_b64": base64.b64encode(stdout).decode("ascii"),
        "stderr_b64": base64.b64encode(stderr).decode("ascii"),
        "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(stderr),
        "claim": "supervisor_observed_local_process_exit_not_external_test_truth",
    }
    return record


def _decoded(value, digest):
    if not isinstance(value, str) or len(value) > 4 * MAX_OUTPUT // 3 + 8:
        raise HumanVerificationError("Unbounded test log encoding")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HumanVerificationError("Invalid test output base64") from exc
    if len(raw) > MAX_OUTPUT or _sha(raw) != digest:
        raise HumanVerificationError("Test output bytes do not match supervised digest")
    return raw


def inspect_test_execution_artifact(artifact: bytes, *,
                                   expected_repository: str, expected_commit: str,
                                   expected_workflow: str, expected_run_id: int,
                                   expected_attempt: int,
                                   expected_suite_sha256: str) -> dict:
    """Strictly parse a previously platform-authenticated execution artifact.

    This does not cryptographically verify it. Pair with verified GitHub/Sigstore
    artifact identity in verify_attested_test_execution().
    """
    if not isinstance(artifact, bytes) or not 1 <= len(artifact) <= MAX_ARTIFACT:
        raise HumanVerificationError("Missing or oversized execution artifact")
    _check_identity(expected_repository, expected_commit, expected_workflow,
                    expected_run_id, expected_attempt)
    if not isinstance(expected_suite_sha256, str) or not SHA256.fullmatch(expected_suite_sha256):
        raise HumanVerificationError("Expected suite hash must be pinned")
    def unique_keys(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise HumanVerificationError("Duplicate execution artifact fields")
            obj[k] = v
        return obj
    try:
        record = json.loads(artifact.decode("utf-8"), object_pairs_hook=unique_keys,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                HumanVerificationError("Nonfinite execution artifact value")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HumanVerificationError("Malformed execution artifact") from exc
    fields = {
        "format", "repository", "source_commit", "workflow", "run_id", "run_attempt",
        "suite", "suite_sha256", "launcher", "arguments", "timeout_seconds",
        "started_at", "finished_at", "elapsed_ms", "exit_code", "output_complete",
        "outcome", "stdout_b64", "stderr_b64", "stdout_sha256", "stderr_sha256",
        "claim",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise HumanVerificationError("Unknown or missing execution artifact fields")
    if (record["format"] != FORMAT
            or record["repository"] != expected_repository
            or record["source_commit"] != expected_commit
            or record["workflow"] != expected_workflow
            or record["run_id"] != expected_run_id
            or record["run_attempt"] != expected_attempt
            or record["suite"] != SUITE
            or record["suite_sha256"] != expected_suite_sha256
            or record["launcher"] != "python_module_pytest"
            or record["arguments"] != ["-q", SUITE]
            or type(record["timeout_seconds"]) is not int
            or not 1 <= record["timeout_seconds"] <= 120
            or type(record["elapsed_ms"]) is not int
            or not 0 <= record["elapsed_ms"] <= 500_000
            or type(record["exit_code"]) is not int
            or not -255 <= record["exit_code"] <= 255
            or type(record["output_complete"]) is not bool
            or record["outcome"] not in ("passed", "failed")
            or record["claim"] != "supervisor_observed_local_process_exit_not_external_test_truth"
            or not isinstance(record["started_at"], str)
            or not isinstance(record["finished_at"], str)
            or len(record["started_at"]) > 40 or len(record["finished_at"]) > 40
            or not all(isinstance(record[key], str) and SHA256.fullmatch(record[key])
                       for key in ("stdout_sha256", "stderr_sha256"))):
        raise HumanVerificationError("Execution artifact violates pinned source and launcher policy")
    try:
        start = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
        finish = datetime.fromisoformat(record["finished_at"].replace("Z", "+00:00"))
        if not record["started_at"].endswith("Z") or not record["finished_at"].endswith("Z") or (
                start.tzinfo is None or finish.tzinfo is None or finish < start):
            raise ValueError("Invalid UTC execution interval")
    except (ValueError, TypeError) as exc:
        raise HumanVerificationError("Malformed execution timestamps") from exc
    stdout = _decoded(record["stdout_b64"], record["stdout_sha256"])
    _decoded(record["stderr_b64"], record["stderr_sha256"])
    predicted = "passed" if record["exit_code"] == 0 and record["output_complete"] else "failed"
    if record["outcome"] != predicted:
        raise HumanVerificationError("Result contradicts recorded process exit code")
    return {
        "format": FORMAT, "artifact_sha256": _sha(artifact),
        "repository": record["repository"], "source_commit": record["source_commit"],
        "workflow": record["workflow"], "run_id": record["run_id"],
        "run_attempt": record["run_attempt"], "suite_sha256": record["suite_sha256"],
        "status": "supervisor_recorded_" + record["outcome"],
        "stdout_sha256": record["stdout_sha256"],
        "stderr_sha256": record["stderr_sha256"],
        "output_complete": record["output_complete"],
        "exit_code": record["exit_code"],
        "process_output_available": bool(stdout),
        "test_execution_platform_proven": False,
        "github_publication": "none", "merge_action": "none",
    }


def verify_attested_test_execution(artifact: bytes, verified_origin: dict, **expected) -> dict:
    """Join a verified GitHub artifact identity and a strict supervisor record.

    The origin object MUST be an authenticated result from
    verify_github_attestation_offline(), never a model or parsed bundle field.
    This function alone cannot establish that callers didn't forge the origin
    object. Keep the verifier invocation and this function in the same host.
    """
    observed = inspect_test_execution_artifact(artifact, **expected)
    if (not isinstance(verified_origin, dict)
            or verified_origin.get("format") != "daddy-reviews-github-attestation-verification-v1"
            or verified_origin.get("status") != "artifact_signature_and_identity_verified"
            or verified_origin.get("platform_oidc_verified") is not True
            or verified_origin.get("artifact_digest_verified") is not True
            or verified_origin.get("artifact_sha256") != observed["artifact_sha256"]
            or verified_origin.get("repository") != observed["repository"]
            or verified_origin.get("source_commit") != observed["source_commit"]
            or verified_origin.get("signer_workflow") != observed["workflow"]):
        raise HumanVerificationError("Execution artifact is not linked to verified GitHub origin")
    return {
        **observed,
        "status": observed["status"] + "_origin_authenticated",
        "artifact_origin_verified": True,
        "test_execution_platform_proven": False,
        "test_outcome_proven": False,
        "policy": "A valid GitHub signature authenticates the runner-produced record, "
                  "not independently the test execution or factual outcome. "
                  "Protected workflow provenance and independent reviewer checks are required.",
    }


def verify_execution_with_github_attestation(*, artifact_file: Path,
                                              bundle_file: Path,
                                              trusted_root_file: Path,
                                              gh_binary: Path,
                                              gh_binary_sha256: str,
                                              expected_repo: str,
                                              expected_repo_id: int,
                                              expected_commit: str,
                                              signer_workflow: str,
                                              expected_artifact_sha256: str,
                                              expected_run_id: int,
                                              expected_attempt: int,
                                              expected_suite_sha256: str) -> dict:
    """Re-use the authenticated artifact SHA as a single host-side trust step.

    Does not accept model-supplied verified-origin JSON as a source of truth.
    """
    from .github_attestation import verify_github_attestation_offline
    origin = verify_github_attestation_offline(
        artifact_file=artifact_file, bundle_file=bundle_file,
        trusted_root_file=trusted_root_file, gh_binary=gh_binary,
        gh_binary_sha256=gh_binary_sha256, expected_repo=expected_repo,
        expected_repo_id=expected_repo_id, expected_commit=expected_commit,
        signer_workflow=signer_workflow,
        expected_artifact_sha256=expected_artifact_sha256,
    )
    artifact = _safe_regular_read(artifact_file, MAX_ARTIFACT)
    if _sha(artifact) != expected_artifact_sha256:
        raise HumanVerificationError("Attested execution artifact changed during verification")
    return verify_attested_test_execution(
        artifact, origin,
        expected_repository=expected_repo, expected_commit=expected_commit,
        expected_workflow=signer_workflow, expected_run_id=expected_run_id,
        expected_attempt=expected_attempt,
        expected_suite_sha256=expected_suite_sha256,
    )
