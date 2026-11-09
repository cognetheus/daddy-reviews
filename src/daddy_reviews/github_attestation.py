"""R8.04e.01: offline GitHub/Sigstore artifact provenance verification.

Only GitHub CLI's independently verified result is considered. We invoke a
host-selected, SHA-256-pinned GH executable on operator-provided bundle and
trusted-root bytes in a private temporary directory; no repository code runs.
The attested *artifact* may be test-output data, but an artifact attestation
does not independently prove the assertion that a test actually ran.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .human_attestation import HumanVerificationError
from .operator_artifacts import _safe_regular_read

FORMAT = "daddy-reviews-github-attestation-verification-v1"
PREDICATE = "https://slsa.dev/provenance/v1"
ISSUER = "https://token.actions.githubusercontent.com"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
WORKFLOW = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml\Z")
MAX_BUNDLE = 1_000_000
MAX_ROOT = 512_000
MAX_RESULT = 512_000
MAX_GH_EXE = 160_000_000


def _verified_executable(path: Path, expected_sha256: str) -> Path:
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise HumanVerificationError("Exact GitHub CLI executable hash required")
    executable = Path(os.path.abspath(os.fspath(path)))
    if not executable.is_absolute() or executable.is_symlink():
        raise HumanVerificationError("GitHub CLI path must be absolute and not a symlink")
    for parent in executable.parents:
        if parent.is_symlink() or parent.stat().st_mode & 0o022:
            raise HumanVerificationError("Untrusted GitHub CLI executable parent")
    if not hasattr(os, "O_NOFOLLOW"):
        raise HumanVerificationError("No-follow binary verification is required")
    fd = None
    try:
        fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111
                or st.st_mode & 0o022 or not 1 <= st.st_size <= MAX_GH_EXE):
            raise HumanVerificationError("Invalid GitHub CLI binary permissions or size")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb") as binary:
            fd = None
            while True:
                block = binary.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise HumanVerificationError("GitHub CLI executable SHA-256 mismatch")
    except OSError as exc:
        raise HumanVerificationError("Cannot securely read GitHub CLI executable") from exc
    finally:
        if fd is not None:
            os.close(fd)
    return executable


def _validate_identity(repo, repo_id, commit, signer, digest):
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or type(repo_id) is not int or repo_id <= 0
            or not isinstance(commit, str) or not SHA1.fullmatch(commit)
            or not isinstance(signer, str) or not WORKFLOW.fullmatch(signer)
            or not signer.startswith(repo + "/")
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)):
        raise HumanVerificationError("Repository, numeric ID, commit, workflow and artifact digest must be pinned")


def _policy_checked_result(stdout: bytes, expected_repo_id: int, expected_digest: str):
    try:
        parsed = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HumanVerificationError("GitHub CLI output was not bounded JSON") from exc
    if not isinstance(parsed, list) or not 1 <= len(parsed) <= 30:
        raise HumanVerificationError("No verified attestation returned by GitHub CLI")
    matched = []
    for entry in parsed:
        if not isinstance(entry, dict) or not isinstance(entry.get("verificationResult"), dict):
            raise HumanVerificationError("GitHub CLI attestation output lacks verification result")
        result = entry["verificationResult"]
        signature = result.get("signature")
        certificate = signature.get("certificate") if isinstance(signature, dict) else None
        if not isinstance(certificate, dict):
            raise HumanVerificationError("GitHub CLI signature certificate absent")
        actual_repo_id = certificate.get("sourceRepositoryIdentifier")
        if str(actual_repo_id) != str(expected_repo_id):
            continue
        stamps = result.get("verifiedTimestamps")
        statement = result.get("statement")
        if (not isinstance(stamps, list) or not stamps
                or not isinstance(statement, dict)
                or statement.get("predicateType") != PREDICATE):
            continue
        subjects = statement.get("subject")
        if (not isinstance(subjects, list) or not 1 <= len(subjects) <= 100):
            continue
        if not any(
            isinstance(subject, dict) and isinstance(subject.get("digest"), dict)
            and subject["digest"].get("sha256") == expected_digest
            for subject in subjects
        ):
            continue
        matched.append({
            "repository_numeric_id": expected_repo_id,
            "subject_sha256": expected_digest,
            "verified_timestamp_count": len(stamps),
        })
    if not matched:
        raise HumanVerificationError("No verified attestation matches repository numeric identity and artifact")
    return matched


def verify_github_attestation_offline(*, artifact_file: Path, bundle_file: Path,
                                      trusted_root_file: Path, gh_binary: Path,
                                      gh_binary_sha256: str, expected_repo: str,
                                      expected_repo_id: int, expected_commit: str,
                                      signer_workflow: str,
                                      expected_artifact_sha256: str,
                                      timeout: int = 25) -> dict:
    """Run pinned GH verifier offline and enforce verified certificate policy.

    A passing result means a signed artifact matched Github-issued identity and
    a trusted Sigstore verification root; it is NOT evidence a test *passed*.
    """
    _validate_identity(expected_repo, expected_repo_id, expected_commit,
                       signer_workflow, expected_artifact_sha256)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise HumanVerificationError("Verifier timeout must be 1–120 seconds")
    binary = _verified_executable(gh_binary, gh_binary_sha256)
    artifact = _safe_regular_read(artifact_file, 65_536)
    bundle = _safe_regular_read(bundle_file, MAX_BUNDLE)
    root = _safe_regular_read(trusted_root_file, MAX_ROOT, protected=True)
    if (not artifact or hashlib.sha256(artifact).hexdigest() != expected_artifact_sha256
            or not bundle or not root):
        raise HumanVerificationError("Attested artifact digest or offline trust material mismatch")
    # Never pass operator-supplied mutable paths to external verification.
    # Create isolated copies, no shell, and prohibit network-origin fallback.
    with tempfile.TemporaryDirectory(prefix="daddy-gh-attestation-") as scratch:
        temp = Path(scratch)
        artifact_path, bundle_path, root_path = (
            temp / "artifact", temp / "bundle.jsonl", temp / "trusted_root.jsonl")
        for target, value in ((artifact_path, artifact), (bundle_path, bundle),
                              (root_path, root)):
            target.write_bytes(value)
            target.chmod(0o600)
        command = [
            str(binary), "attestation", "verify", str(artifact_path),
            "--repo", expected_repo,
            "--bundle", str(bundle_path),
            "--custom-trusted-root", str(root_path),
            "--signer-workflow", signer_workflow,
            "--source-digest", expected_commit,
            "--cert-oidc-issuer", ISSUER,
            "--predicate-type", PREDICATE,
            "--deny-self-hosted-runners",
            "--format", "json",
        ]
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("GH_", "GITHUB_", "GIT_", "SIGSTORE_"))
               and key not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                               "http_proxy", "https_proxy", "all_proxy")}
        env["GH_PROMPT_DISABLED"] = "1"
        env["NO_COLOR"] = "1"
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout,
                                  check=False, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HumanVerificationError("Pinned GitHub attestation verifier unavailable or timed out") from exc
        if proc.returncode != 0:
            raise HumanVerificationError("GitHub CLI refused cryptographic attestation verification")
        if not proc.stdout or len(proc.stdout) > MAX_RESULT:
            raise HumanVerificationError("GitHub CLI produced no valid bounded verification result")
        accepted = _policy_checked_result(
            proc.stdout, expected_repo_id, expected_artifact_sha256)
    # Re-check pinned executable after the external call to narrow replacement.
    _verified_executable(gh_binary, gh_binary_sha256)
    return {
        "format": FORMAT, "status": "artifact_signature_and_identity_verified",
        "repository": expected_repo, "repository_numeric_id": expected_repo_id,
        "source_commit": expected_commit, "signer_workflow": signer_workflow,
        "artifact_sha256": expected_artifact_sha256,
        "verified_attestation_count": len(accepted),
        "platform_oidc_verified": True,
        "artifact_digest_verified": True,
        "verified_by": "sha256_pinned_gh_attestation_verify_offline",
        "github_actions_test_execution_proven": False,
        "test_outcome_proven": False,
        "merge_action": "none", "github_publication": "none",
        "limits": "GitHub/Sigstore verified artifact origin, not that the artifact's test claims are true. "
                  "Offline trusted roots need independent freshness and repository-ID pinning.",
    }
