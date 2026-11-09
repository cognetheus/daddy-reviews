"""R8.04f: actual fixed-suite pytest capture, bound artifact parsing and trust join.

The only cryptographic verification integration is in the separate GitHub
Actions attested-test-execution workflow. Mocking origins here is NOT proof.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from daddy_reviews import test_execution as subject
from daddy_reviews.human_attestation import HumanVerificationError


REPO = "cognetheus/daddy-reviews"
COMMIT = "a" * 40
WF = REPO + "/.github/workflows/attested-test-execution.yml"
ROOT = Path(__file__).resolve().parents[1]


def payload():
    suite = ROOT / subject.SUITE
    contents = suite.read_bytes()
    stdout = b"5 passed in 0.40s\n"
    stderr = b""
    return {
        "format": subject.FORMAT,
        "repository": REPO, "source_commit": COMMIT,
        "workflow": WF, "run_id": 919, "run_attempt": 1,
        "suite": subject.SUITE,
        "suite_sha256": hashlib.sha256(contents).hexdigest(),
        "launcher": "python_module_pytest",
        "arguments": ["-q", subject.SUITE],
        "timeout_seconds": 60, "started_at": "2026-11-09T15:00:00Z",
        "finished_at": "2026-11-09T15:00:01Z", "elapsed_ms": 150,
        "exit_code": 0, "output_complete": True, "outcome": "passed",
        "stdout_b64": base64.b64encode(stdout).decode(),
        "stderr_b64": base64.b64encode(stderr).decode(),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "claim": "supervisor_observed_local_process_exit_not_external_test_truth",
    }


def encode(record):
    return (json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def expect(record):
    return {
        "expected_repository": REPO,
        "expected_commit": COMMIT,
        "expected_workflow": WF,
        "expected_run_id": 919,
        "expected_attempt": 1,
        "expected_suite_sha256": record["suite_sha256"],
    }


def origin(artifact):
    return {
        "format": "daddy-reviews-github-attestation-verification-v1",
        "status": "artifact_signature_and_identity_verified",
        "platform_oidc_verified": True, "artifact_digest_verified": True,
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "repository": REPO, "source_commit": COMMIT,
        "signer_workflow": WF,
    }


def test_actual_pytest_suite_is_captured_without_claiming_external_truth():
    evidence = subject.capture_fixed_ci_test(
        ROOT, repository=REPO, commit=COMMIT, workflow=WF,
        run_id=919, attempt=1)
    assert evidence["outcome"] == "passed", (
        base64.b64decode(evidence["stdout_b64"]).decode(errors="replace")
    )
    assert evidence["exit_code"] == 0
    assert evidence["suite"] == subject.SUITE
    assert evidence["suite_sha256"] == hashlib.sha256(
        (ROOT / subject.SUITE).read_bytes()).hexdigest()
    artifact = encode(evidence)
    assessed = subject.inspect_test_execution_artifact(artifact, **expect(evidence))
    assert assessed["status"] == "supervisor_recorded_passed"
    assert not assessed["test_execution_platform_proven"]
    assert assessed["merge_action"] == assessed["github_publication"] == "none"


def test_authenticated_artifact_origin_is_explicitly_separate_from_test_truth():
    report = payload()
    artifact = encode(report)
    result = subject.verify_attested_test_execution(
        artifact, origin(artifact), **expect(report))
    assert result["status"] == "supervisor_recorded_passed_origin_authenticated"
    assert result["artifact_origin_verified"]
    assert result["test_outcome_proven"] is False
    assert result["test_execution_platform_proven"] is False


def test_forged_origin_and_wrong_identity_rejected():
    report = payload()
    artifact = encode(report)
    for edit in (
        {"artifact_sha256": "0" * 64},
        {"source_commit": "b" * 40},
        {"repository": "forged/repo"},
        {"status": "unverified"},
        {"platform_oidc_verified": False},
        {"artifact_digest_verified": False},
        {"signer_workflow": "malicious/repo/.github/workflows/test.yml"},
    ):
        fake = {**origin(artifact), **edit}
        with pytest.raises(HumanVerificationError):
            subject.verify_attested_test_execution(artifact, fake, **expect(report))


@pytest.mark.parametrize("key,bad", [
    ("source_commit", "b" * 40),
    ("repository", "other/repo"),
    ("workflow", "other/repo/.github/workflows/ci.yml"),
    ("run_id", 920),
    ("run_attempt", 2),
    ("suite", "tests/test_other.py"),
    ("suite_sha256", "0" * 64),
    ("launcher", "shell"),
    ("arguments", ["-q", "--ignore"]),
    ("exit_code", 1),
    ("output_complete", False),
    ("stdout_sha256", "0" * 64),
    ("stdout_b64", "invalid-base64%"),
    ("started_at", "2026-12-01T12:00:00Z"),
    ("timeout_seconds", 0),
])
def test_tampered_report_field_cannot_inherit_passing_status(key, bad):
    record = payload()
    record[key] = bad
    with pytest.raises(HumanVerificationError):
        subject.inspect_test_execution_artifact(encode(record), **expect(payload()))


def test_duplicate_json_nonfinite_and_extra_fields_fail_closed():
    normal = payload()
    for artifact in (
        encode(normal).replace(b'"run_attempt":1', b'"run_attempt":1,"run_attempt":1'),
        encode(normal).replace(b'"elapsed_ms":150', b'"elapsed_ms":NaN'),
        encode({**normal, "approve_merge": True}),
        b"{}",
    ):
        with pytest.raises(HumanVerificationError):
            subject.inspect_test_execution_artifact(artifact, **expect(normal))


def test_real_failed_and_truncated_supervisor_reports_remain_failures(monkeypatch):
    actual = payload()
    def fake_fail(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, b"failure", b"failed")
    monkeypatch.setattr(subject.subprocess, "run", fake_fail)
    report = subject.capture_fixed_ci_test(
        ROOT, repository=REPO, commit=COMMIT, workflow=WF,
        run_id=919, attempt=1)
    assert report["outcome"] == "failed" and report["exit_code"] == 1
    assert subject.inspect_test_execution_artifact(
        encode(report), **expect(actual))["status"] == "supervisor_recorded_failed"
    def fake_overlong(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b"x" * (subject.MAX_OUTPUT + 1), b"")
    monkeypatch.setattr(subject.subprocess, "run", fake_overlong)
    report = subject.capture_fixed_ci_test(
        ROOT, repository=REPO, commit=COMMIT, workflow=WF,
        run_id=919, attempt=1)
    assert report["outcome"] == "failed" and not report["output_complete"]


def test_run_identity_and_missing_test_suite_rejected_before_execution(monkeypatch, tmp_path):
    invoked = []
    monkeypatch.setattr(subject.subprocess, "run",
                        lambda *a, **kw: invoked.append((a, kw)))
    with pytest.raises(HumanVerificationError):
        subject.capture_fixed_ci_test(
            ROOT, repository=REPO, commit="bad", workflow=WF,
            run_id=919, attempt=1)
    with pytest.raises(HumanVerificationError):
        subject.capture_fixed_ci_test(
            tmp_path, repository=REPO, commit=COMMIT,
            workflow=WF, run_id=919, attempt=1)
    assert not invoked


def test_test_supervisor_refuses_process_with_oidc_or_github_credentials(monkeypatch):
    for credential in (
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GH_TOKEN", "GITHUB_TOKEN",
    ):
        invoked = []
        with monkeypatch.context() as scope:
            scope.setenv(credential, "do-not-expose")
            scope.setattr(subject.subprocess, "run",
                          lambda *args, **kwargs: invoked.append((args, kwargs)))
            with pytest.raises(HumanVerificationError):
                subject.capture_fixed_ci_test(
                    ROOT, repository=REPO, commit=COMMIT,
                    workflow=WF, run_id=919, attempt=1)
        assert not invoked


def test_single_host_verification_links_to_exact_same_artifact(monkeypatch, tmp_path):
    record = payload()
    artifact = encode(record)
    path = tmp_path / "supervised.json"
    path.write_bytes(artifact)
    observed = []
    def fake_external_verify(**kwargs):
        observed.append(kwargs)
        return origin(artifact)
    from daddy_reviews import github_attestation
    monkeypatch.setattr(github_attestation, "verify_github_attestation_offline",
                        fake_external_verify)
    verified = subject.verify_execution_with_github_attestation(
        artifact_file=path, bundle_file=tmp_path / "bundle",
        trusted_root_file=tmp_path / "root", gh_binary=Path("/usr/bin/gh"),
        gh_binary_sha256="b" * 64,
        expected_repo=REPO, expected_repo_id=123,
        expected_commit=COMMIT, signer_workflow=WF,
        expected_artifact_sha256=hashlib.sha256(artifact).hexdigest(),
        expected_run_id=919, expected_attempt=1,
        expected_suite_sha256=record["suite_sha256"])
    assert observed and verified["artifact_origin_verified"] is True
    assert verified["test_outcome_proven"] is False
    assert not verified["test_execution_platform_proven"]
