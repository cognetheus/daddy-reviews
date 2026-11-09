"""R8.04g.02 independent blinded human label provenance and CLI regressions."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews import cli
from daddy_reviews.ground_truth_labels import (
    FORMAT, audit_independently_signed_labels, label_signing_bytes,
)
from daddy_reviews.human_attestation import HumanVerificationError
from daddy_reviews.human_quality import read_resolution_dataset

CORPUS = Path(__file__).resolve().parents[1] / "evals/human_resolution_synthetic.json"


def inputs():
    dataset = copy.deepcopy(read_resolution_dataset(CORPUS))
    dataset["dataset_kind"] = "human_labeled"
    for case in dataset["cases"]:
        case["label_metadata"]["label_kind"] = "human_labeled"
    private = {}
    keys = {}
    for name in ("alice", "bob"):
        secret = Ed25519PrivateKey.generate()
        public = secret.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        private[name] = secret
        keys[name + "-key"] = {
            "reviewer_id": name, "role": "ground_truth_adjudicator",
            "enabled": True, "public_key_b64": base64.b64encode(public).decode(),
        }
    records = []
    evidence = {}
    for case in dataset["cases"]:
        for person in private:
            blob = (f"Independent test evidence {case['id']} by {person}; "
                    "no model responses seen; synthetic fixture only.").encode()
            digest = hashlib.sha256(blob).hexdigest()
            evidence[digest] = blob
            rec = {
                "format": FORMAT, "case_id": case["id"],
                "candidate_id": case["candidate_id"],
                "snapshot_id": case["snapshot_id"],
                "patch_sha256": case["patch_sha256"],
                "tier": case["tier"], "label": case["label"],
                "reviewer_id": person, "key_id": person + "-key",
                "signed_at": "2026-11-09T16:00:00Z",
                "blind_protocol": "separate_from_model_and_resolution_v1",
                "evidence_sha256": digest,
                "rationale": "Synthetic independent reproduction audit for a bounded case.",
                "signature_b64": "",
            }
            rec["signature_b64"] = base64.b64encode(
                private[person].sign(label_signing_bytes(rec))).decode()
            records.append(rec)
    return dataset, records, keys, evidence


def test_signed_two_independent_humans_per_case_advisory_metrics_only():
    dataset, records, keys, evidence = inputs()
    scored = audit_independently_signed_labels(dataset, records, keys, evidence)
    assert scored["status"] == "authenticated_label_provenance_not_truth"
    assert scored["signed_label_count"] == 20
    assert scored["case_count"] == 10
    assert scored["metrics"]["tp"] == 3
    assert scored["metrics"]["fp"] == 1
    assert scored["metrics"]["fn"] == 1
    assert scored["identity_and_evidence_bytes_authenticated"]
    assert not scored["blind_review_confirmed_by_platform"]
    assert not scored["defect_truth_independently_proven"]
    assert not scored["model_quality_approved"]
    assert not scored["promotion_eligible"]
    assert scored["github_publication"] == scored["merge_action"] == "none"
    assert len(scored["audit_receipts"]) == 20
    assert scored == audit_independently_signed_labels(dataset, records, keys, evidence)


@pytest.mark.parametrize("change", [
    ("label", "clean"), ("snapshot_id", "fake-source"),
    ("patch_sha256", "f" * 64), ("tier", "trivial"),
    ("candidate_id", "fake-candidate"),
    ("evidence_sha256", "a" * 64),
    ("rationale", "A different rationale after signing"),
    ("blind_protocol", "model-reviewed"),
    ("signature_b64", "invalid"),
])
def test_tampered_signature_or_label_binding_fails(change):
    dataset, labels, trusted, blobs = inputs()
    labels[0][change[0]] = change[1]
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, labels, trusted, blobs)


def test_distinct_signers_and_required_evidence_must_be_present():
    dataset, labels, trusted, blobs = inputs()
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, labels[:1], trusted, blobs)
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, [labels[0], labels[0], *labels[2:]],
                                          trusted, blobs)
    lost = dict(blobs)
    lost.pop(labels[0]["evidence_sha256"])
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, labels, trusted, lost)
    bad = dict(blobs)
    bad[labels[0]["evidence_sha256"]] = b"tampered"
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, labels, trusted, bad)


def test_revoked_identity_and_wrong_role_fail_closed():
    dataset, labels, trusted, blobs = inputs()
    for modify in (
        lambda t: t["alice-key"].update(enabled=False),
        lambda t: t["alice-key"].update(role="human_verifier"),
        lambda t: t["alice-key"].update(reviewer_id="mallory"),
        lambda t: t.pop("alice-key"),
    ):
        changed = copy.deepcopy(trusted)
        modify(changed)
        with pytest.raises(HumanVerificationError):
            audit_independently_signed_labels(dataset, labels, changed, blobs)


def test_synthetic_dataset_cannot_masquerade_as_real_human_labeled():
    dataset, labels, trusted, blobs = inputs()
    dataset["dataset_kind"] = "synthetic"
    for case in dataset["cases"]:
        case["label_metadata"]["label_kind"] = "synthetic"
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(dataset, labels, trusted, blobs)


def test_operator_cli_verifies_signed_case_evidence_offline(tmp_path, capsys):
    dataset, labels, trusted, blobs = inputs()
    corpus = tmp_path / "human-cases.json"
    records = tmp_path / "signed-labels.json"
    keys = tmp_path / "trusted-label-keys.json"
    folder = tmp_path / "ground-truth-evidence"
    folder.mkdir()
    corpus.write_text(json.dumps(dataset))
    records.write_text(json.dumps(labels))
    keys.write_text(json.dumps(trusted))
    keys.chmod(0o600)
    for digest, blob in blobs.items():
        (folder / digest).write_bytes(blob)
    cli.main([
        "human-label-audit", "--root", str(tmp_path),
        "--resolution-dataset", str(corpus),
        "--label-attestations-file", str(records),
        "--label-trust-keys-file", str(keys),
        "--label-evidence-dir", str(folder),
    ])
    report = json.loads(capsys.readouterr().out)
    assert report["signed_label_count"] == 20
    assert report["identity_and_evidence_bytes_authenticated"] is True
    assert report["promotion_eligible"] is False
    assert "Independent test evidence" not in json.dumps(report)


def test_unsigned_invented_human_label_rejected():
    dataset, labels, trusted, blobs = inputs()
    record = copy.deepcopy(labels[0])
    record["signature_b64"] = ""
    with pytest.raises(HumanVerificationError):
        audit_independently_signed_labels(
            dataset, [record, *labels[1:]], trusted, blobs)
