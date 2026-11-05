"""R8.04c: independent Ed25519 human attestations and bounded test-log receipts.

Verification uses a public-key registry supplied by the host, not by the model
or the signed artifact. This module never runs tests or executes source code.
A signature authenticates the named key holder, not the truth of a conclusion.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re

FORMAT = "daddy-reviews-human-attestation-v1"
DOMAIN = b"daddy-reviews-human-attestation-v1\n"
MAX_RECORDS = 48
MAX_LOG_BYTES = 65_536
MAX_RATIONALE = 1600
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
_DECISIONS = {"confirm": "reproduced", "reject": "not_reproduced",
              "inconclusive": "inconclusive"}
_FIELDS = frozenset({
    "format", "candidate_id", "candidate_digest", "snapshot_id", "patch_sha256", "source_sha256",
    "reviewer_id", "key_id", "signed_at", "decision", "rationale",
    "challenge_sha256", "challenge_acknowledged", "test", "signature_b64",
})
_TEST_FIELDS = frozenset({
    "test_id", "command", "environment", "outcome", "log_sha256",
})


class HumanVerificationError(ValueError):
    """No authenticity or source provenance can be inferred from this artifact."""


def sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def signing_bytes(record: dict) -> bytes:
    """Domain-separated canonical payload; signature is excluded."""
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise HumanVerificationError("Human attestation has missing or unexpected fields")
    unsigned = {k: v for k, v in record.items() if k != "signature_b64"}
    try:
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HumanVerificationError("Non-canonical human attestation") from exc
    if len(canonical) > 6_000:
        raise HumanVerificationError("Human attestation exceeds byte ceiling")
    return DOMAIN + canonical


def _identity(value, limit=128):
    return isinstance(value, str) and len(value) <= limit and bool(IDENTIFIER.fullmatch(value))


def _digest(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _utc_timestamp(value):
    if not isinstance(value, str) or len(value) > 32 or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


def _verify_schema(record):
    signing_bytes(record)
    if (record["format"] != FORMAT
            or not all(_identity(record[key]) for key in (
                "candidate_id", "reviewer_id", "key_id"))
            or not isinstance(record["snapshot_id"], str)
            or not 1 <= len(record["snapshot_id"]) <= 128
            or not _digest(record["candidate_digest"])
            or not _digest(record["patch_sha256"])
            or not _digest(record["source_sha256"])
            or not _utc_timestamp(record["signed_at"])
            or record["decision"] not in _DECISIONS
            or not isinstance(record["rationale"], str)
            or not 10 <= len(record["rationale"].strip()) <= MAX_RATIONALE
            or (record["challenge_sha256"] is not None
                and not _digest(record["challenge_sha256"]))
            or type(record["challenge_acknowledged"]) is not bool):
        raise HumanVerificationError("Malformed or unbounded human attestation")
    test = record["test"]
    if (not isinstance(test, dict) or set(test) != _TEST_FIELDS
            or not _identity(test["test_id"])
            or not isinstance(test["command"], str)
            or not 1 <= len(test["command"].strip()) <= 400
            or not isinstance(test["environment"], str)
            or not 1 <= len(test["environment"].strip()) <= 300
            or test["outcome"] != _DECISIONS[record["decision"]]
            or not _digest(test["log_sha256"])):
        raise HumanVerificationError("Test receipt has invalid fields or decision mismatch")
    if record["challenge_acknowledged"] and record["challenge_sha256"] is None:
        raise HumanVerificationError("Cannot acknowledge an absent challenge")
    return test


def _public_key(trust_record, reviewer_id):
    if (not isinstance(trust_record, dict)
            or set(trust_record) != {"reviewer_id", "role", "enabled", "public_key_b64"}
            or trust_record.get("reviewer_id") != reviewer_id
            or trust_record.get("role") != "human_verifier"
            or trust_record.get("enabled") is not True):
        raise HumanVerificationError("Human identity is not trusted for verification")
    try:
        key = base64.b64decode(trust_record["public_key_b64"], validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HumanVerificationError("Invalid trusted public key") from exc
    if len(key) != 32:
        raise HumanVerificationError("Wrong Ed25519 public key length")
    return key


def verify_human_attestation(record: dict, trusted_keys: dict, log_blobs: dict) -> dict:
    """Verify signature, trusted identity and supplied evidence bytes.

    Trust keys and log bytes MUST originate outside untrusted model reports.
    No test is run and no log text is included in returned audit metadata.
    """
    test = _verify_schema(record)
    if not isinstance(trusted_keys, dict) or not isinstance(log_blobs, dict):
        raise HumanVerificationError("Host trust registry and logs are required")
    key = _public_key(trusted_keys.get(record["key_id"]), record["reviewer_id"])
    try:
        signature = base64.b64decode(record["signature_b64"], validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HumanVerificationError("Invalid signature encoding") from exc
    if len(signature) != 64:
        raise HumanVerificationError("Wrong Ed25519 signature length")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise HumanVerificationError(
            "Signature verification requires the optional verification dependency"
        ) from exc
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, signing_bytes(record))
    except (InvalidSignature, ValueError) as exc:
        raise HumanVerificationError("Invalid human attestation signature") from exc
    log_digest = test["log_sha256"]
    blob = log_blobs.get(log_digest)
    if not isinstance(blob, bytes) or not 1 <= len(blob) <= MAX_LOG_BYTES:
        raise HumanVerificationError("Missing or oversized independent test evidence blob")
    if hashlib.sha256(blob).hexdigest() != log_digest:
        raise HumanVerificationError("Test evidence bytes do not match the signed digest")
    return {
        "receipt_sha256": sha256_json(record),
        "reviewer_id": record["reviewer_id"], "key_id": record["key_id"],
        "candidate_id": record["candidate_id"], "decision": record["decision"],
        "signed_at": record["signed_at"], "test_id": test["test_id"],
        "test_outcome": test["outcome"], "log_sha256": log_digest,
        "challenge_sha256": record["challenge_sha256"],
        "challenge_acknowledged": record["challenge_acknowledged"],
        "signature_verified": True, "log_digest_verified": True,
    }
