"""R8.04d.02: cryptographically bound, independently signed runner receipts.

An operator must enroll a separate trusted runner key and retain its public
registry independently. This authenticates control of that key and links
recorded job metadata to observed log bytes. It does NOT validate GitHub OIDC,
Sigstore transparency logs, or that the claimed workflow actually executed.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

from .human_attestation import HumanVerificationError, sha256_json

FORMAT = "daddy-reviews-runner-receipt-v1"
DOMAIN = b"daddy-reviews-runner-receipt-v1\n"
FIELDS = frozenset({
    "format", "key_id", "runner_id", "provider", "repository", "commit_sha",
    "workflow_ref", "run_id", "run_attempt", "job_id", "observed_at",
    "snapshot_id", "patch_sha256", "test_id", "test_outcome",
    "log_sha256", "signature_b64",
})
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
OUTCOMES = {"reproduced", "not_reproduced", "inconclusive"}


def runner_signing_bytes(record: dict) -> bytes:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise HumanVerificationError("Runner receipt has missing or extra fields")
    try:
        raw = json.dumps({k: v for k, v in record.items() if k != "signature_b64"},
                         ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HumanVerificationError("Noncanonical CI receipt") from exc
    if len(raw) > 5_000:
        raise HumanVerificationError("Runner receipt exceeds byte ceiling")
    return DOMAIN + raw


def _valid_record(record):
    runner_signing_bytes(record)
    if (record["format"] != FORMAT or record["provider"] != "github_actions"
            or any(not isinstance(record[k], str) or not IDENT.fullmatch(record[k])
                   for k in ("key_id", "runner_id", "test_id"))
            or not isinstance(record["repository"], str)
            or REPO.fullmatch(record["repository"]) is None
            or not isinstance(record["commit_sha"], str)
            or SHA1.fullmatch(record["commit_sha"]) is None
            or not isinstance(record["workflow_ref"], str)
            or not 1 <= len(record["workflow_ref"]) <= 256
            or not record["workflow_ref"].startswith(".github/workflows/")
            or ".." in record["workflow_ref"].split("/")
            or any(type(record[k]) is not int or record[k] <= 0 for k in (
                "run_id", "run_attempt", "job_id"))
            or not isinstance(record["observed_at"], str)
            or not record["observed_at"].endswith("Z")
            or len(record["observed_at"]) > 32
            or not isinstance(record["snapshot_id"], str)
            or not 1 <= len(record["snapshot_id"]) <= 128
            or any(not isinstance(record[k], str) or SHA256.fullmatch(record[k]) is None
                   for k in ("patch_sha256", "log_sha256"))
            or record["test_outcome"] not in OUTCOMES):
        raise HumanVerificationError("Malformed runner receipt")
    return record


def verify_runner_receipts(receipts: list, trusted_runner_keys: dict,
                           resolution: dict, human_records: list,
                           evidence_blobs: dict, *, expected_commit: str) -> dict:
    """Verify signer-role separation, canonical signatures and matching logs.

    A good runner signature raises evidence integrity but is not an OIDC-based
    platform attestation. No shell, network or workload execution is performed.
    """
    if (not isinstance(receipts, list) or not 1 <= len(receipts) <= 48
            or not isinstance(trusted_runner_keys, dict)
            or not 1 <= len(trusted_runner_keys) <= 64
            or not isinstance(resolution, dict) or not isinstance(human_records, list)
            or not isinstance(evidence_blobs, dict)
            or not isinstance(expected_commit, str) or SHA1.fullmatch(expected_commit) is None):
        raise HumanVerificationError("Runner authenticity inputs and pinned commit required")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise HumanVerificationError("Runner receipts require optional verification dependency") from exc

    human_tests = set()
    for record in human_records:
        if not isinstance(record, dict) or not isinstance(record.get("test"), dict):
            raise HumanVerificationError("Human record missing test receipt")
        test = record["test"]
        human_tests.add((test.get("test_id"), test.get("log_sha256"), test.get("outcome")))
    recognized = set()
    verified_receipts = []
    seen = set()
    for record in receipts:
        _valid_record(record)
        key = trusted_runner_keys.get(record["key_id"])
        if (not isinstance(key, dict)
                or set(key) != {"runner_id", "role", "enabled", "public_key_b64"}
                or key["runner_id"] != record["runner_id"]
                or key["role"] != "ci_runner_attestor"
                or key["enabled"] is not True):
            raise HumanVerificationError("Runner signing identity is not independently trusted")
        if (record["snapshot_id"] != resolution.get("snapshot_id")
                or record["patch_sha256"] != resolution.get("patch_sha256")
                or record["commit_sha"] != expected_commit):
            raise HumanVerificationError("Runner receipt references wrong source or commit")
        identity = (record["run_id"], record["run_attempt"], record["job_id"],
                    record["test_id"], record["log_sha256"])
        if identity in seen:
            raise HumanVerificationError("Duplicate CI runner receipt")
        seen.add(identity)
        blob = evidence_blobs.get(record["log_sha256"])
        if (not isinstance(blob, bytes) or not blob
                or len(blob) > 65_536
                or hashlib.sha256(blob).hexdigest() != record["log_sha256"]):
            raise HumanVerificationError("Runner test-log bytes unavailable or modified")
        try:
            public = base64.b64decode(key["public_key_b64"], validate=True)
            signature = base64.b64decode(record["signature_b64"], validate=True)
            if len(public) != 32 or len(signature) != 64:
                raise ValueError("Wrong signature size")
            Ed25519PublicKey.from_public_bytes(public).verify(
                signature, runner_signing_bytes(record))
        except (ValueError, TypeError, InvalidSignature, binascii.Error) as exc:
            raise HumanVerificationError("Invalid CI runner receipt signature") from exc
        testkey = (record["test_id"], record["log_sha256"], record["test_outcome"])
        if testkey not in human_tests:
            raise HumanVerificationError("Runner receipt is not linked to a signed human test claim")
        recognized.add(testkey)
        verified_receipts.append({
            "runner_id": record["runner_id"],
            "repository": record["repository"], "commit_sha": record["commit_sha"],
            "workflow_ref": record["workflow_ref"], "run_id": record["run_id"],
            "run_attempt": record["run_attempt"], "job_id": record["job_id"],
            "test_id": record["test_id"], "log_sha256": record["log_sha256"],
            "signature_verified": True, "receipt_sha256": sha256_json(record),
        })
    missing = sorted(human_tests - recognized)
    return {
        "format": "daddy-reviews-runner-provenance-evaluation-v1",
        "status": "runner_key_verified" if not missing else "incomplete_runner_evidence",
        "verified_receipts": sorted(verified_receipts,
                                   key=lambda r: (r["run_id"], r["job_id"], r["test_id"])),
        "unmatched_human_test_count": len(missing),
        "signature_basis": "host_enrolled_ci_runner_attestor_ed25519",
        "platform_oidc_verified": False,
        "github_actions_execution_proven": False,
        "github_publication": "none", "merge_action": "none",
        "limits": "Signed runner identity does not validate GitHub Actions or CI artifact provenance.",
    }
