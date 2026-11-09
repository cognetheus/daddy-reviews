"""R8.04e.01: operator policy for genuine GitHub CLI attestations.

Unit tests MOCK the external cryptographic CLI, and therefore do not claim
real Sigstore validation. Full integration requires a real signed bundle.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from daddy_reviews import github_attestation as subject
from daddy_reviews.cli import main
from daddy_reviews.human_attestation import HumanVerificationError

REPO = "cognetheus/daddy-reviews"
REPO_ID = 123456
COMMIT = "a" * 40
ARTIFACT = b"test log, externally signed artifact bytes\n"
SHA = hashlib.sha256(ARTIFACT).hexdigest()
SIGNER = "cognetheus/daddy-reviews/.github/workflows/ci.yml"


def files(root):
    paths = {
        "artifact_file": root / "test-log",
        "bundle_file": root / "github-bundle.jsonl",
        "trusted_root_file": root / "sigstore-root.jsonl",
        "gh_binary": root / "gh-binary",
    }
    for label, value in (
        ("artifact_file", ARTIFACT),
        ("bundle_file", b'{"untrusted":"bundle"}\n'),
        ("trusted_root_file", b'{"operator":"trusted-root-fixture"}\n'),
        ("gh_binary", b"fake-command-binary"),
    ):
        paths[label].write_bytes(value)
    paths["gh_binary"].chmod(0o755)
    return paths


def verified_output(*, repository_id=REPO_ID, digest=SHA, timestamps=None,
                    predicate=subject.PREDICATE):
    if timestamps is None:
        timestamps = [{"timestamp": "2026-11-09T10:00:00Z"}]
    return json.dumps([{
        "attestation": {"untrusted": "copied"},
        "verificationResult": {
            "signature": {"certificate": {
                "sourceRepositoryIdentifier": str(repository_id),
            }},
            "verifiedTimestamps": timestamps,
            "statement": {
                "predicateType": predicate,
                "subject": [{"name": "test-log", "digest": {"sha256": digest}}],
                "predicate": {"untrusted": "The tests passed!"}
            },
        },
    }]).encode()


def verify(root, monkeypatch, *, output=None, exitcode=0, **kwargs):
    paths = files(root)
    argv = {
        **paths, "gh_binary_sha256": hashlib.sha256(b"fake-command-binary").hexdigest(),
        "expected_repo": REPO, "expected_repo_id": REPO_ID,
        "expected_commit": COMMIT, "signer_workflow": SIGNER,
        "expected_artifact_sha256": SHA,
    }
    argv.update(kwargs)
    # Only stub binary trust validation here; isolated tests separately test
    # actual binary digest verification. Never pretend this stubs signature verification.
    monkeypatch.setattr(subject, "_verified_executable", lambda path, hash: Path(path))
    observed = []
    def run(command, **options):
        observed.append((command, options))
        return subprocess.CompletedProcess(command, exitcode,
                                          output if output is not None else verified_output(),
                                          b"could contain secrets")
    monkeypatch.setattr(subject.subprocess, "run", run)
    return argv, observed


def test_cli_invokes_pinned_gh_policy_and_attested_digest(monkeypatch, tmp_path):
    inputs, calls = verify(tmp_path, monkeypatch)
    result = subject.verify_github_attestation_offline(**inputs)
    assert result["status"] == "artifact_signature_and_identity_verified"
    assert result["platform_oidc_verified"] is True
    assert result["github_actions_test_execution_proven"] is False
    assert result["test_outcome_proven"] is False
    assert result["github_publication"] == result["merge_action"] == "none"
    assert "untrusted" not in json.dumps(result)
    assert len(calls) == 1
    command, opts = calls[0]
    assert command[1:3] == ["attestation", "verify"]
    for flag, value in (
        ("--repo", REPO),
        ("--signer-workflow", SIGNER),
        ("--source-digest", COMMIT),
        ("--cert-oidc-issuer", subject.ISSUER),
        ("--predicate-type", subject.PREDICATE),
    ):
        assert command[command.index(flag) + 1] == value
    assert "--bundle" in command and "--custom-trusted-root" in command
    assert "--deny-self-hosted-runners" in command
    assert "shell" not in opts and opts["check"] is False
    assert opts["env"]["GH_PROMPT_DISABLED"] == "1"
    assert "GH_TOKEN" not in opts["env"]
    assert not Path(command[3]).exists()  # private temporary copy cleaned up


@pytest.mark.parametrize("change", [
    {"repository_id": REPO_ID + 1},
    {"digest": "0" * 64},
    {"timestamps": []},
    {"predicate": "https://spdx.dev/Document/v2.3"},
])
def test_untrusted_metadata_or_missing_verified_timestamp_fails(
        tmp_path, monkeypatch, change):
    inputs, _ = verify(tmp_path, monkeypatch, output=verified_output(**change))
    with pytest.raises(HumanVerificationError):
        subject.verify_github_attestation_offline(**inputs)


def test_verifier_exit_failure_is_never_overridden_by_plausible_json(tmp_path, monkeypatch):
    inputs, _ = verify(tmp_path, monkeypatch, exitcode=1)
    with pytest.raises(HumanVerificationError):
        subject.verify_github_attestation_offline(**inputs)


def test_malformed_or_empty_verification_json_cannot_be_promotion(tmp_path, monkeypatch):
    for stdout in (b"", b"{}", b"[]", b"null", b"invalid", b"{}\n{}"):
        inputs, _ = verify(tmp_path, monkeypatch, output=stdout)
        with pytest.raises(HumanVerificationError):
            subject.verify_github_attestation_offline(**inputs)


def test_invalid_repo_identity_signer_commit_and_digest_fail_before_cli(tmp_path, monkeypatch):
    changes = (
        {"expected_repo_id": 0},
        {"expected_repo": "evil/repo"},
        {"signer_workflow": "evil/repo/.github/workflows/ci.yml"},
        {"signer_workflow": "cognetheus/daddy-reviews/../../unsafe"},
        {"expected_commit": "bogus"},
        {"expected_artifact_sha256": "0" * 64},
    )
    for change in changes:
        inputs, calls = verify(tmp_path, monkeypatch, **change)
        with pytest.raises(HumanVerificationError):
            subject.verify_github_attestation_offline(**inputs)
        assert calls == []


def test_modified_artifact_and_symlinked_root_fail_before_gh(tmp_path, monkeypatch):
    inputs, calls = verify(tmp_path, monkeypatch)
    inputs["artifact_file"].write_bytes(b"tampered evidence")
    with pytest.raises(HumanVerificationError):
        subject.verify_github_attestation_offline(**inputs)
    assert not calls
    inputs, calls = verify(tmp_path, monkeypatch)
    root = tmp_path / "link-root.jsonl"
    root.symlink_to(inputs["trusted_root_file"])
    inputs["trusted_root_file"] = root
    with pytest.raises(HumanVerificationError):
        subject.verify_github_attestation_offline(**inputs)
    assert not calls


def test_actual_binary_digest_gate_rejects_wrong_hash_and_symlink():
    actual = Path(sys.executable).resolve()
    if any(part.is_symlink() for part in [actual, *actual.parents]):
        pytest.skip("Interpreter path has symlinked parent")
    binary = actual.read_bytes()
    digest = hashlib.sha256(binary).hexdigest()
    if actual.stat().st_mode & 0o022 or any(p.stat().st_mode & 0o022 for p in actual.parents):
        pytest.skip("Interpreter installation directory is not suitable for trusted binary gate")
    assert subject._verified_executable(actual, digest) == actual
    with pytest.raises(HumanVerificationError):
        subject._verified_executable(actual, "0" * 64)


def test_cli_explicit_operator_args_and_result(monkeypatch, tmp_path, capsys):
    inputs, _ = verify(tmp_path, monkeypatch)
    flags = [
        "github-attestation-verify", "--root", str(tmp_path),
        "--attested-artifact-file", str(inputs["artifact_file"]),
        "--attestation-bundle-file", str(inputs["bundle_file"]),
        "--sigstore-trusted-root-file", str(inputs["trusted_root_file"]),
        "--gh-binary", str(inputs["gh_binary"]),
        "--gh-binary-sha256", inputs["gh_binary_sha256"],
        "--attestation-repo", REPO,
        "--attestation-repo-id", str(REPO_ID),
        "--attestation-commit", COMMIT,
        "--attestation-signer-workflow", SIGNER,
        "--attestation-artifact-sha256", SHA,
    ]
    main(flags)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "artifact_signature_and_identity_verified"
    assert not result["test_outcome_proven"]
