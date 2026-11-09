"""R8.04g.02: signed, blinded, source-bound labels for reviewer evaluation.

This authenticates enrolled human adjudicators' statements and evidence bytes,
NOT correctness of their defect labels or reviewer/model performance. No
automatic review promotion, PR publication or merge decision is possible.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
import json
import re

from .human_attestation import HumanVerificationError, sha256_json
from .human_quality import evaluate_human_resolutions, validate_resolution_dataset

FORMAT = "daddy-reviews-ground-truth-label-v1"
RESULT_FORMAT = "daddy-reviews-authenticated-label-evaluation-v1"
DOMAIN = b"daddy-reviews-ground-truth-label-v1\n"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PERSON = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
FIELDS = frozenset({
    "format", "case_id", "candidate_id", "snapshot_id", "patch_sha256",
    "tier", "label", "reviewer_id", "key_id", "signed_at",
    "blind_protocol", "evidence_sha256", "rationale", "signature_b64",
})
MAX_LABELS = 500
MAX_EVIDENCE_BYTES = 65_536
MAX_HUMANS_PER_CASE = 4


def label_signing_bytes(record: dict) -> bytes:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise HumanVerificationError("Independent label record has missing or extra fields")
    try:
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "signature_b64"},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HumanVerificationError("Independent label cannot be canonicalized") from exc
    if len(canonical) > 6_000:
        raise HumanVerificationError("Independent label exceeds size limit")
    return DOMAIN + canonical


def _schema(record):
    label_signing_bytes(record)
    if (record["format"] != FORMAT
            or any(not isinstance(record.get(k), str)
                   or not PERSON.fullmatch(record[k]) for k in (
                       "case_id", "candidate_id", "reviewer_id", "key_id"))
            or not isinstance(record["snapshot_id"], str)
            or not 1 <= len(record["snapshot_id"]) <= 128
            or not isinstance(record["patch_sha256"], str)
            or not SHA256.fullmatch(record["patch_sha256"])
            or record["tier"] not in ("trivial", "lite", "full")
            or record["label"] not in ("defect", "clean")
            or record["blind_protocol"] != "separate_from_model_and_resolution_v1"
            or not isinstance(record["evidence_sha256"], str)
            or not SHA256.fullmatch(record["evidence_sha256"])
            or not isinstance(record["rationale"], str)
            or not 20 <= len(record["rationale"].strip()) <= 1600
            or not isinstance(record["signed_at"], str)
            or not record["signed_at"].endswith("Z")
            or len(record["signed_at"]) > 32):
        raise HumanVerificationError("Invalid independently signed label fields")
    try:
        value = datetime.fromisoformat(record["signed_at"].replace("Z", "+00:00"))
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("Not UTC")
    except (TypeError, ValueError, AttributeError) as exc:
        raise HumanVerificationError("Invalid label UTC signing timestamp") from exc


def _check_signature(record, trusted_keys):
    trust = trusted_keys.get(record["key_id"])
    if (not isinstance(trust, dict)
            or set(trust) != {"reviewer_id", "role", "enabled", "public_key_b64"}
            or trust["reviewer_id"] != record["reviewer_id"]
            or trust["role"] != "ground_truth_adjudicator"
            or trust["enabled"] is not True):
        raise HumanVerificationError("Ground truth signer is not independently trusted")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise HumanVerificationError("Independent labels require Ed25519 verification dependency") from exc
    try:
        pub = base64.b64decode(trust["public_key_b64"], validate=True)
        signature = base64.b64decode(record["signature_b64"], validate=True)
        if len(pub) != 32 or len(signature) != 64:
            raise ValueError("Invalid signature sizes")
        Ed25519PublicKey.from_public_bytes(pub).verify(
            signature, label_signing_bytes(record))
    except (ValueError, TypeError, binascii.Error, InvalidSignature) as exc:
        raise HumanVerificationError("Independent defect label signature invalid") from exc


def audit_independently_signed_labels(dataset: dict, labels: list,
                                       trusted_keys: dict, evidence_blobs: dict,
                                       *, min_reviewers: int = 2) -> dict:
    """Require two distinct signed independent human labels per source-bound case.

    Identical decisions authenticate consent, not correctness. Label evidence
    is never executed and the evaluator's copied resolution JSON isn't
    re-cryptographically verified by this module.
    """
    try:
        validate_resolution_dataset(dataset)
    except ValueError as exc:
        raise HumanVerificationError("Human quality dataset is not valid") from exc
    if (dataset["dataset_kind"] != "human_labeled"
            or not isinstance(labels, list) or not 1 <= len(labels) <= MAX_LABELS
            or not isinstance(trusted_keys, dict) or len(trusted_keys) > 128
            or not isinstance(evidence_blobs, dict) or len(evidence_blobs) > MAX_LABELS
            or type(min_reviewers) is not int or not 2 <= min_reviewers <= 4):
        raise HumanVerificationError("Invalid human-labeled corpus or signer limits")
    cases = {(c["id"], c["candidate_id"]): c for c in dataset["cases"]}
    seen = set()
    per_case = {key: [] for key in cases}
    audit_receipts = []
    for record in labels:
        _schema(record)
        key = record["case_id"], record["candidate_id"]
        case = cases.get(key)
        if case is None:
            raise HumanVerificationError("Independent label refers to unknown corpus case")
        if (record["snapshot_id"] != case["snapshot_id"]
                or record["patch_sha256"] != case["patch_sha256"]
                or record["tier"] != case["tier"]
                or record["label"] != case["label"]):
            raise HumanVerificationError("Label contradicts source identity or adjudicated corpus label")
        identity = key + (record["reviewer_id"],)
        if identity in seen:
            raise HumanVerificationError("One human cannot sign multiple labels for one case")
        seen.add(identity)
        if len(per_case[key]) >= MAX_HUMANS_PER_CASE:
            raise HumanVerificationError("Excessive adjudicators for one case")
        _check_signature(record, trusted_keys)
        digest = record["evidence_sha256"]
        blob = evidence_blobs.get(digest)
        if (not isinstance(blob, bytes) or not 1 <= len(blob) <= MAX_EVIDENCE_BYTES
                or hashlib.sha256(blob).hexdigest() != digest):
            raise HumanVerificationError("Missing or forged independent label evidence bytes")
        per_case[key].append(record)
        audit_receipts.append({
            "case_id": record["case_id"], "candidate_id": record["candidate_id"],
            "reviewer_id": record["reviewer_id"],
            "receipt_sha256": sha256_json(record),
            "evidence_sha256": digest,
            "signature_verified": True,
        })
    if any(len(members) < min_reviewers for members in per_case.values()):
        raise HumanVerificationError("Insufficient distinct independently trusted human label signers")
    score = evaluate_human_resolutions(dataset)
    return {
        "format": RESULT_FORMAT,
        "status": "authenticated_label_provenance_not_truth",
        "case_count": len(cases), "minimum_distinct_reviewers": min_reviewers,
        "signed_label_count": len(labels),
        "corpus_sha256": score["corpus_sha256"],
        "metrics": score["metrics"],
        "by_tier": score["by_tier"],
        "audit_receipts": sorted(audit_receipts, key=lambda r: (
            r["case_id"], r["candidate_id"], r["reviewer_id"])),
        "source": "host_enrolled_separate_human_ground_truth_adjudicator_keys",
        "identity_and_evidence_bytes_authenticated": True,
        "blind_review_confirmed_by_platform": False,
        "defect_truth_independently_proven": False,
        "resolution_reports_reverified": False,
        "model_quality_approved": False,
        "promotion_eligible": False, "merge_action": "none",
        "github_publication": "none",
        "policy": "Human signatures authenticate authorship, not the factual label or model "
                  "accuracy. Confirm blinded reviewer independence, source snapshots "
                  "and separate reproduction methods outside this evaluator.",
    }
