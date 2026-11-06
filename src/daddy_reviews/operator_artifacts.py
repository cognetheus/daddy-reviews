"""R8.04d.01: strictly bounded, read-only operator artifact ingestion.

The operator chooses every input explicitly. JSON, trust records and test logs
are never sourced from model suggestions or executed as code. No URL fetching.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from .human_attestation import HumanVerificationError, MAX_LOG_BYTES, MAX_RECORDS

MAX_JSON_BYTES = 2_000_000
MAX_PATCH_BYTES = 24_000
MAX_TRUST_BYTES = 64_000
MAX_LOG_COUNT = 48


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HumanVerificationError("Duplicate JSON field not permitted")
        result[key] = value
    return result


def _bad_constant(value):
    raise HumanVerificationError("Non-finite JSON number not permitted")


def _safe_regular_read(path: Path, max_bytes: int, *, protected: bool = False) -> bytes:
    """Reject path traversal through symlinks and nonregular file descriptors.

    O_NOFOLLOW protects the final component during open; ancestor directory
    symlink checks are intentionally restrictive. The operator should use
    trusted local directories, not attacker-writable shared locations.
    """
    target = Path(os.path.abspath(os.fspath(path)))
    if not 0 < max_bytes <= MAX_JSON_BYTES:
        raise HumanVerificationError("Unsupported input byte ceiling")
    for entry in (target, *target.parents):
        if entry.is_symlink():
            raise HumanVerificationError("Symlinked operator input or parent rejected")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise HumanVerificationError("No-follow input reads are required")
    flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(target, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise HumanVerificationError("Input must be a bounded regular file")
        if protected and info.st_mode & 0o022:
            raise HumanVerificationError("Trusted registry must not be group/world writable")
        with os.fdopen(fd, "rb", closefd=True) as file:
            fd = None
            raw = file.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise HumanVerificationError("Input grew beyond byte ceiling")
        return raw
    except (OSError, ValueError) as exc:
        raise HumanVerificationError("Cannot safely read operator input") from exc
    finally:
        if fd is not None:
            os.close(fd)


def read_operator_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES,
                       protected: bool = False):
    raw = _safe_regular_read(path, max_bytes, protected=protected)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                          parse_constant=_bad_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HumanVerificationError("Invalid operator JSON input") from exc


def read_operator_patch(path: Path) -> str:
    raw = _safe_regular_read(path, MAX_PATCH_BYTES)
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise HumanVerificationError("Patch must be UTF-8") from exc


def read_test_logs(folder: Path, attestations: list[dict]) -> dict[str, bytes]:
    if not isinstance(attestations, list) or len(attestations) > MAX_RECORDS:
        raise HumanVerificationError("Invalid human attestation count")
    path = Path(os.path.abspath(os.fspath(folder)))
    for component in (path, *path.parents):
        if component.is_symlink():
            raise HumanVerificationError("Symlinked log directory rejected")
    if not path.is_dir():
        raise HumanVerificationError("Evidence directory missing")
    requested = set()
    for attestation in attestations:
        if not isinstance(attestation, dict) or not isinstance(attestation.get("test"), dict):
            raise HumanVerificationError("Malformed human log reference")
        digest = attestation["test"].get("log_sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise HumanVerificationError("Human log digest is invalid")
        requested.add(digest)
    if len(requested) > MAX_LOG_COUNT:
        raise HumanVerificationError("Excessive distinct evidence logs")
    result = {}
    for digest in sorted(requested):
        contents = _safe_regular_read(path / digest, MAX_LOG_BYTES)
        if not contents or hashlib.sha256(contents).hexdigest() != digest:
            raise HumanVerificationError("Observed log does not match human-signed SHA-256")
        result[digest] = contents
    return result


def load_operator_inputs(*, patch_file: Path, report_file: Path,
                         attestations_file: Path, trust_keys_file: Path,
                         evidence_dir: Path, challenge_file: Path | None = None) -> dict:
    """Load explicitly selected files, with no implicit discovery or writes."""
    patch = read_operator_patch(patch_file)
    report = read_operator_json(report_file)
    attestations = read_operator_json(attestations_file)
    trusted_keys = read_operator_json(trust_keys_file, max_bytes=MAX_TRUST_BYTES,
                                      protected=True)
    challenge = read_operator_json(challenge_file) if challenge_file is not None else None
    if (not isinstance(report, dict) or not isinstance(attestations, list)
            or not isinstance(trusted_keys, dict)
            or challenge is not None and not isinstance(challenge, dict)):
        raise HumanVerificationError("Operator artifact types do not match contracts")
    logs = read_test_logs(evidence_dir, attestations)
    return {"patch": patch, "report": report, "attestations": attestations,
            "trusted_keys": trusted_keys, "evidence_blobs": logs,
            "challenge": challenge}
