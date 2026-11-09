"""R8.04f: operator CLI can validate a real signed supervised-test artifact.

Cryptographic verification is mocked in the unit test; the separate Github
Actions workflow tests authentic GitHub OIDC/Sigstore integration.
"""
import hashlib
import json
from pathlib import Path

import pytest

from daddy_reviews import cli
from daddy_reviews.human_attestation import HumanVerificationError
from test_test_execution import COMMIT, REPO, WF, encode, payload


def build_args(tmp_path):
    evidence = encode(payload())
    artifact = tmp_path / "supervised.json"
    artifact.write_bytes(evidence)
    return [
        "attested-test-verify", "--root", str(tmp_path),
        "--attested-artifact-file", str(artifact),
        "--attestation-bundle-file", str(tmp_path / "bundle.jsonl"),
        "--sigstore-trusted-root-file", str(tmp_path / "trusted-root.jsonl"),
        "--gh-binary", "/usr/bin/gh",
        "--gh-binary-sha256", "b" * 64,
        "--attestation-repo", REPO,
        "--attestation-repo-id", "123456",
        "--attestation-commit", COMMIT,
        "--attestation-signer-workflow", WF,
        "--attestation-artifact-sha256", hashlib.sha256(evidence).hexdigest(),
        "--test-suite-sha256", payload()["suite_sha256"],
        "--test-run-id", "919",
        "--test-run-attempt", "1",
    ]


def test_operator_cli_pins_commit_run_suite_artifact_and_restricts_actions(
        tmp_path, monkeypatch, capsys):
    args = build_args(tmp_path)
    observed = []
    def verify(**kwargs):
        observed.append(kwargs)
        return {
            "status": "supervisor_recorded_passed_origin_authenticated",
            "artifact_origin_verified": True,
            "test_outcome_proven": False,
            "test_execution_platform_proven": False,
            "github_publication": "none", "merge_action": "none",
        }
    monkeypatch.setattr(cli, "verify_execution_with_github_attestation", verify)
    cli.main(args)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "supervisor_recorded_passed_origin_authenticated"
    assert not result["test_outcome_proven"]
    assert result["merge_action"] == result["github_publication"] == "none"
    assert len(observed) == 1
    assert observed[0]["expected_commit"] == COMMIT
    assert observed[0]["expected_run_id"] == 919
    assert observed[0]["expected_suite_sha256"] == payload()["suite_sha256"]


def test_failed_signed_test_process_preserves_json_but_nonzero_exit(
        tmp_path, monkeypatch, capsys):
    args = build_args(tmp_path)
    monkeypatch.setattr(cli, "verify_execution_with_github_attestation",
                        lambda **kwargs: {
                            "status": "supervisor_recorded_failed_origin_authenticated",
                            "test_outcome_proven": False})
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "supervisor_recorded_failed_origin_authenticated"


def test_cli_requires_all_pinned_source_and_run_arguments(
        tmp_path, monkeypatch, capsys):
    args = build_args(tmp_path)
    index = args.index("--test-suite-sha256")
    del args[index:index+2]
    called = []
    monkeypatch.setattr(cli, "verify_execution_with_github_attestation",
                        lambda **kwargs: called.append(kwargs))
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2 and not called


def test_cli_invalid_authenticator_fails_before_json_result(
        tmp_path, monkeypatch, capsys):
    args = build_args(tmp_path)
    def reject(**kwargs):
        raise HumanVerificationError("Unverified GitHub provenance")
    monkeypatch.setattr(cli, "verify_execution_with_github_attestation", reject)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert "Unverified GitHub provenance" in capsys.readouterr().err
