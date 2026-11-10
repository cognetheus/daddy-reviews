"""R8.04h source-anchored, independently signed real-sample evaluation tests.

Test labels are generated synthetic adjudications over REAL local Git objects.
They cannot be used as evidence that external human research was performed.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews import cli
from daddy_reviews.ground_truth_labels import FORMAT, label_signing_bytes
from daddy_reviews.human_attestation import HumanVerificationError
from daddy_reviews.real_repository_intake import build_real_repository_intake
from daddy_reviews.real_repository_quality import (
    audit_real_repository_labels, read_label_evidence,
)
from test_real_repository_intake import git_source, model_report, build


def signed_case_records(tmp_path, *, with_model=True):
    root, base, head = git_source(tmp_path)
    report = model_report(root, base, head) if with_model else None
    intake = build(root, base, head, report=report)
    predicted = {c["case_id"]: c for c in intake["private_ledger"]["cases"]}
    positive = next((c["case_id"] for c in predicted.values() if c["model_flagged"]), None)
    missed = next(c["case_id"] for c in predicted.values() if not c["model_flagged"])
    keys = {}
    secrets = {}
    for person in ("labeler-one", "labeler-two"):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        secrets[person] = key
        keys[person] = {
            "reviewer_id": person, "role": "ground_truth_adjudicator",
            "enabled": True, "public_key_b64": base64.b64encode(public).decode(),
        }
    labels, blobs = [], {}
    for case in intake["blind_packet"]["cases"]:
        for person in secrets:
            evidence = (
                f"Independent reviewer test-only evidence for {case['case_id']}"
                f" against immutable Git object {head}, labeler {person}"
            ).encode("utf-8")
            digest = hashlib.sha256(evidence).hexdigest()
            blobs[digest] = evidence
            decision = "defect" if case["case_id"] in {positive, missed} else "clean"
            record = {
                "format": FORMAT, "case_id": case["case_id"],
                "candidate_id": case["case_id"],
                "snapshot_id": head,
                "patch_sha256": intake["blind_packet"]["patch_sha256"],
                "tier": case["tier"], "label": decision,
                "reviewer_id": person, "key_id": person,
                "signed_at": "2026-11-10T12:00:00Z",
                "blind_protocol": "separate_from_model_and_resolution_v1",
                "evidence_sha256": digest,
                "rationale": "Test-only example of a separately reproduced decision.",
                "signature_b64": "",
            }
            record["signature_b64"] = base64.b64encode(
                secrets[person].sign(label_signing_bytes(record))).decode()
            labels.append(record)
    kwargs = {
        "repository": "example/real-repo", "repository_id": 912345,
        "base_commit": base, "head_commit": head,
        "seed": "independent-lab-seed-2026", "max_cases": 5,
        "report": report,
    }
    return root, intake, labels, keys, blobs, secrets, kwargs


def evaluate(root, intake, labels, keys, blobs, kwargs):
    return audit_real_repository_labels(
        root, intake["blind_packet"], intake["private_ledger"],
        labels, keys, blobs, **kwargs)


def test_model_flagged_and_unflagged_human_adjudications_counted_separately(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    result = evaluate(root, intake, records, keys, blobs, kwargs)
    assert result["status"] == "sample_audited_not_population_accuracy"
    assert result["case_count"] == 5
    assert result["counts"]["true_positive"] == 1
    assert result["counts"]["sampled_unflagged_defect"] == 1
    assert result["observed_sample_metrics"]["recall_among_sampled_changed_line_anchors"] == 0.5
    assert result["observed_sample_metrics"]["precision_among_sampled_flagged"] == 1.0
    assert result["signed_label_count"] == 10
    assert not result["population_accuracy_claim"]
    assert not result["promotion_eligible"]
    assert not result["blinding_cryptographically_proven"]
    assert result["github_publication"] == result["merge_action"] == "none"
    assert "labeler-one" in json.dumps(result)


def test_missing_model_report_still_authenticates_labels_but_does_not_score(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path, with_model=False)
    result = evaluate(root, intake, records, keys, blobs, kwargs)
    assert result["status"] == "labels_authenticated_model_predictions_missing"
    assert result["observed_sample_metrics"] is None
    assert result["counts"] is None
    assert not result["population_accuracy_claim"]


def test_private_ledger_and_blind_packet_forgery_cannot_redefine_git_population(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    for alter in (
        lambda x: x["private_ledger"]["cases"][0].update(\n            model_flagged=not x["private_ledger"]["cases"][0]["model_flagged"]),
        lambda x: x["blind_packet"]["cases"][0].update(line=999),
        lambda x: x["private_ledger"]["population"].update(eligible_added_lines=0),
        lambda x: x["blind_packet"]["cases"][0].update(label="defect"),
    ):
        forged = copy.deepcopy(intake)
        alter(forged)
        with pytest.raises(HumanVerificationError):
            evaluate(root, forged, records, keys, blobs, kwargs)


def test_signatures_protect_source_claims_and_separate_reviewer_identity(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    for mutate in (
        lambda rs: rs[0].update(snapshot_id="b" * 40),
        lambda rs: rs[0].update(evidence_sha256="0" * 64),
        lambda rs: rs[0].update(label="clean" if rs[0]["label"] == "defect" else "defect"),
        lambda rs: rs[0].update(key_id="labeler-two"),
        lambda rs: rs[0].update(signature_b64="not-ed25519"),
    ):
        changed = copy.deepcopy(records)
        mutate(changed)
        with pytest.raises(HumanVerificationError):
            evaluate(root, intake, changed, keys, blobs, kwargs)


def test_missing_duplicate_and_revoked_human_signers_block_metrics(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    with pytest.raises(HumanVerificationError):
        evaluate(root, intake, records[1:], keys, blobs, kwargs)
    with pytest.raises(HumanVerificationError):
        evaluate(root, intake, [records[0], records[0], *records[2:]],
                 keys, blobs, kwargs)
    bad = copy.deepcopy(keys)
    bad["labeler-one"]["enabled"] = False
    with pytest.raises(HumanVerificationError):
        evaluate(root, intake, records, bad, blobs, kwargs)


def test_disagreement_is_human_escalation_not_majority_truth(tmp_path):
    root, intake, records, keys, blobs, secrets, kwargs = signed_case_records(tmp_path)
    changed = copy.deepcopy(records)
    changed[1]["label"] = ("defect" if changed[1]["label"] == "clean" else "clean")
    changed[1]["signature_b64"] = base64.b64encode(
        secrets["labeler-two"].sign(label_signing_bytes(changed[1]))).decode()
    result = evaluate(root, intake, changed, keys, blobs, kwargs)
    assert result["status"] == "conflicting_human_labels_escalate"
    assert result["counts"] is None
    assert result["observed_sample_metrics"] is None
    assert result["conflicting_case_ids"] == [changed[1]["case_id"]]
    assert result["promotion_eligible"] is False


def test_operator_rechecks_git_commit_and_refuses_stale_source_metadata(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    changed = {**kwargs, "head_commit": "b" * 40}
    with pytest.raises((HumanVerificationError, ValueError)):
        evaluate(root, intake, records, keys, blobs, changed)


def test_operator_cli_real_label_audit_reads_sha256_named_human_evidence(tmp_path, capsys):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    folder = tmp_path / "private-research"
    folder.mkdir(mode=0o700)
    blind = folder / "blind.json"
    ledger = folder / "ledger.json"
    labels = folder / "labels.json"
    trust = folder / "trusted-public-keys.json"
    evidence = folder / "evidence"
    evidence.mkdir(mode=0o700)
    blind.write_text(json.dumps(intake["blind_packet"]))
    ledger.write_text(json.dumps(intake["private_ledger"]))
    labels.write_text(json.dumps(records))
    trust.write_text(json.dumps(keys))
    trust.chmod(0o600)
    for digest, data in blobs.items():
        (evidence / digest).write_bytes(data)
    report = folder / "model-report.json"
    report.write_text(json.dumps(kwargs["report"]))
    cli.main([
        "real-label-audit", "--root", str(root),
        "--base", kwargs["base_commit"], "--head", kwargs["head_commit"],
        "--attestation-repo", kwargs["repository"],
        "--attestation-repo-id", str(kwargs["repository_id"]),
        "--real-sample-seed", kwargs["seed"],
        "--real-sample-max-cases", str(kwargs["max_cases"]),
        "--real-blind-file", str(blind),
        "--real-private-file", str(ledger),
        "--real-model-report", str(report),
        "--label-attestations-file", str(labels),
        "--label-trust-keys-file", str(trust),
        "--label-evidence-dir", str(evidence),
    ])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "sample_audited_not_population_accuracy"
    assert output["counts"]["sampled_unflagged_defect"] == 1
    assert output["model_quality_approved"] is False
    assert "Independent reviewer test-only evidence" not in json.dumps(output)


def test_symlinked_real_label_evidence_not_loaded(tmp_path):
    root, intake, records, keys, blobs, _, kwargs = signed_case_records(tmp_path)
    folder = tmp_path / "evidence"
    folder.mkdir()
    digest, raw = next(iter(blobs.items()))
    actual = tmp_path / "outside"
    actual.write_bytes(raw)
    (folder / digest).symlink_to(actual)
    for other_digest, data in blobs.items():
        if other_digest != digest:
            (folder / other_digest).write_bytes(data)
    with pytest.raises(HumanVerificationError):
        read_label_evidence(folder, records)
