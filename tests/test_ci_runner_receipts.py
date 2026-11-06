"""R8.04d.02: signed runner receipt integrity (not GitHub OIDC identity)."""
import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews.ci_runner_receipts import (
    FORMAT, runner_signing_bytes, verify_runner_receipts,
)
from daddy_reviews.cli import main
from daddy_reviews.human_attestation import HumanVerificationError
from daddy_reviews.human_resolution import adjudicate_human_verification
from daddy_reviews.operator_artifacts import load_operator_inputs
from test_operator_artifacts import build_inputs


COMMIT = "a" * 40
REPO = "cognetheus/daddy-reviews"


def prepare(root):
    paths = build_inputs(root)
    inputs = load_operator_inputs(**paths)
    resolution = adjudicate_human_verification(root, **inputs)
    assert resolution["status"] == "human_attested_resolution"
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trust = {"runner-001": {
        "runner_id": "ci-runner-001", "role": "ci_runner_attestor",
        "enabled": True, "public_key_b64": base64.b64encode(public).decode(),
    }}
    test = inputs["attestations"][0]["test"]
    receipt = {
        "format": FORMAT, "key_id": "runner-001", "runner_id": "ci-runner-001",
        "provider": "github_actions", "repository": REPO,
        "commit_sha": COMMIT, "workflow_ref": ".github/workflows/ci.yml",
        "run_id": 42, "run_attempt": 1, "job_id": 7,
        "observed_at": "2026-11-06T13:00:00Z",
        "snapshot_id": resolution["snapshot_id"],
        "patch_sha256": resolution["patch_sha256"],
        "test_id": test["test_id"],
        "test_outcome": test["outcome"],
        "log_sha256": test["log_sha256"],
        "signature_b64": "",
    }
    receipt["signature_b64"] = base64.b64encode(
        private.sign(runner_signing_bytes(receipt))).decode()
    return paths, inputs, resolution, trust, receipt, private


def assess(parts, receipts=None, trust=None, repo=REPO, commit=COMMIT):
    paths, inputs, resolution, trusted, record, _ = parts
    return verify_runner_receipts(
        receipts if receipts is not None else [record],
        trust if trust is not None else trusted,
        resolution, inputs["attestations"], inputs["evidence_blobs"],
        expected_commit=commit, expected_repository=repo,
    )


def test_signed_runner_receipt_links_human_log_and_pinned_source(tmp_path):
    parts = prepare(tmp_path)
    result = assess(parts)
    assert result["status"] == "runner_key_verified"
    assert result["unmatched_human_test_count"] == 0
    assert result["verified_receipts"][0]["signature_verified"] is True
    assert result["platform_oidc_verified"] is False
    assert result["github_actions_execution_proven"] is False
    assert result["github_publication"] == result["merge_action"] == "none"


def test_altered_runner_metadata_is_rejected(tmp_path):
    parts = prepare(tmp_path)
    base = parts[4]
    for field, value in (
        ("commit_sha", "b" * 40), ("repository", "other/repo"),
        ("workflow_ref", ".github/workflows/other.yml"),
        ("test_outcome", "not_reproduced"), ("log_sha256", "0" * 64),
        ("snapshot_id", "forged"), ("run_id", 999),
        ("signature_b64", "invalid signature"),
    ):
        record = copy.deepcopy(base)
        record[field] = value
        with pytest.raises(HumanVerificationError):
            assess(parts, [record])


def test_external_trust_cannot_be_replaced_by_artifact(tmp_path):
    parts = prepare(tmp_path)
    for edit in (
        lambda t: t["runner-001"].update(enabled=False),
        lambda t: t["runner-001"].update(role="human_verifier"),
        lambda t: t["runner-001"].update(runner_id="unknown-runner"),
        lambda t: t.pop("runner-001"),
    ):
        trusted = copy.deepcopy(parts[3])
        edit(trusted)
        with pytest.raises(HumanVerificationError):
            assess(parts, trust=trusted)


def test_pinned_repository_commit_and_duplicate_runner_receipts(tmp_path):
    parts = prepare(tmp_path)
    with pytest.raises(HumanVerificationError):
        assess(parts, repo="forged/repo")
    with pytest.raises(HumanVerificationError):
        assess(parts, commit="f" * 40)
    with pytest.raises(HumanVerificationError):
        assess(parts, [parts[4], parts[4]])


def test_runner_receipt_with_unlinked_test_claim_is_rejected(tmp_path):
    parts = prepare(tmp_path)
    record = copy.deepcopy(parts[4])
    record["test_id"] = "different/test"
    record["signature_b64"] = base64.b64encode(
        parts[5].sign(runner_signing_bytes(record))).decode()
    with pytest.raises(HumanVerificationError):
        assess(parts, [record])


def test_runner_receipts_do_not_cover_unmatched_independent_human_tests(tmp_path):
    parts = prepare(tmp_path)
    _, inputs, resolution, trust, record, _ = parts
    extra = {"test": {"test_id": "another/test", "log_sha256": "0" * 64,
                      "outcome": "inconclusive"}}
    result = verify_runner_receipts(
        [record], trust, resolution, inputs["attestations"] + [extra],
        inputs["evidence_blobs"], expected_commit=COMMIT, expected_repository=REPO)
    assert result["status"] == "incomplete_runner_evidence"
    assert result["unmatched_human_test_count"] == 1


def test_operator_cli_checks_runner_evidence_without_proving_platform_execution(tmp_path, capsys):
    parts = prepare(tmp_path)
    paths, _, _, trust, receipt, _ = parts
    receipt_file = tmp_path / "runner-receipts.json"
    runner_trust_file = tmp_path / "runner-trust.json"
    receipt_file.write_text(json.dumps([receipt]))
    runner_trust_file.write_text(json.dumps(trust))
    args = [
        "human-verify", "--root", str(tmp_path),
        "--diff-file", str(paths["patch_file"]),
        "--report-file", str(paths["report_file"]),
        "--attestations-file", str(paths["attestations_file"]),
        "--trusted-keys-file", str(paths["trust_keys_file"]),
        "--evidence-dir", str(paths["evidence_dir"]),
        "--ci-receipts-file", str(receipt_file),
        "--ci-runner-keys-file", str(runner_trust_file),
        "--ci-expected-repo", REPO,
        "--ci-expected-commit", COMMIT,
    ]
    main(args)
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "human_attested_resolution"
    assert report["ci_runner_provenance"]["status"] == "runner_key_verified"
    assert not report["ci_runner_provenance"]["github_actions_execution_proven"]
    assert report["merge_action"] == report["github_publication"] == "none"
