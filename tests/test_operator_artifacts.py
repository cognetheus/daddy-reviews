"""R8.04d.01: operator ingestion rejects unsafe artifacts and drives real CLI."""
import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews.cli import main
from daddy_reviews.human_attestation import (
    FORMAT as HUMAN_FORMAT, HumanVerificationError, signing_bytes,
)
from daddy_reviews.human_resolution import candidate_digest
from daddy_reviews.investigative_agents import investigate_with_specialists
from daddy_reviews.operator_artifacts import (
    load_operator_inputs, read_operator_json, read_test_logs,
)

PATCH = ("diff --git a/src/auth.py b/src/auth.py\n"
         "new file mode 100644\n"
         "--- /dev/null\n+++ b/src/auth.py\n"
         "@@ -0,0 +1,2 @@\n"
         "+def authorize(user):\n"
         "+    return bool(user)\n")
LOG = b"Signed local test evidence: role policy observed failing\n"


def build_inputs(root, *, number=2):
    path = root / "src" / "auth.py"
    path.parent.mkdir()
    path.write_text("def authorize(user):\n    return bool(user)\n", encoding="utf-8")

    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {"tool": "read_file",
                    "path": "src/auth.py", "start_line": 1, "end_line": 2}}
        return {"kind": "final", "findings": [{
            "rule": "AUTH-BOOL", "path": "src/auth.py", "line": 2,
            "claim": "Boolean truthiness allows unexpected identity values",
            "evidence": "Only truthiness is checked at the changed line",
            "severity": "medium", "citations": ["E1"]}]}
    report = investigate_with_specialists(
        root, PATCH, provider, reviewers=("security",),
        allowed_tools={"read_file"}, max_workers=1)
    assert report["status"] == "complete"

    digest = hashlib.sha256(LOG).hexdigest()
    logs_dir = root / "evidence"
    logs_dir.mkdir()
    (logs_dir / digest).write_bytes(LOG)
    trust = {}
    attestations = []
    candidate = report["verification_queue"]["items"][0]
    for i in range(number):
        person = f"human-{i+1}"
        keyid = f"key-{i+1}"
        private = Ed25519PrivateKey.generate()
        pub = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        trust[keyid] = {
            "reviewer_id": person, "role": "human_verifier",
            "enabled": True, "public_key_b64": base64.b64encode(pub).decode(),
        }
        record = {
            "format": HUMAN_FORMAT, "candidate_id": candidate["id"],
            "candidate_digest": candidate_digest(report, candidate["id"]),
            "snapshot_id": report["snapshot_id"],
            "patch_sha256": report["patch_sha256"],
            "source_sha256": candidate["source_spans"][0]["sha256"],
            "reviewer_id": person, "key_id": keyid,
            "signed_at": "2026-11-06T12:00:00Z",
            "decision": "confirm",
            "rationale": "Confirmed the test outcome in a separate human review.",
            "challenge_sha256": None,
            "challenge_acknowledged": False,
            "test": {"test_id": "tests/test_auth.py::test_access",
                     "command": "pytest -q tests/test_auth.py",
                     "environment": "trusted-runner-linux",
                     "outcome": "reproduced", "log_sha256": digest},
            "signature_b64": "",
        }
        record["signature_b64"] = base64.b64encode(
            private.sign(signing_bytes(record))).decode()
        attestations.append(record)
    (root / "patch.diff").write_text(PATCH)
    (root / "report.json").write_text(json.dumps(report))
    (root / "attestations.json").write_text(json.dumps(attestations))
    (root / "trusted-keys.json").write_text(json.dumps(trust))
    return {
        "patch_file": root / "patch.diff",
        "report_file": root / "report.json",
        "attestations_file": root / "attestations.json",
        "trust_keys_file": root / "trusted-keys.json",
        "evidence_dir": logs_dir,
    }


def test_cli_human_signed_resolution_without_code_execution(tmp_path, capsys):
    opts = build_inputs(tmp_path)
    main(["human-verify", "--root", str(tmp_path),
          "--diff-file", str(opts["patch_file"]),
          "--report-file", str(opts["report_file"]),
          "--attestations-file", str(opts["attestations_file"]),
          "--trusted-keys-file", str(opts["trust_keys_file"]),
          "--evidence-dir", str(opts["evidence_dir"])])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "human_attested_resolution"
    assert result["resolved_count"] == 1
    assert result["human_attested_confirmations"] == 1
    assert result["github_publication"] == result["merge_action"] == "none"
    assert "Signed local test evidence" not in json.dumps(result)


def test_cli_missing_human_keeps_nonzero_exit(tmp_path, capsys):
    opts = build_inputs(tmp_path, number=1)
    args = ["human-verify", "--root", str(tmp_path),
            "--diff-file", str(opts["patch_file"]),
            "--report-file", str(opts["report_file"]),
            "--attestations-file", str(opts["attestations_file"]),
            "--trusted-keys-file", str(opts["trust_keys_file"]),
            "--evidence-dir", str(opts["evidence_dir"])]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "human_attention_required"


def test_duplicate_json_keys_and_nonfinite_values_rejected(tmp_path):
    source = tmp_path / "source.json"
    for body in ('{"a":1,"a":2}', '{"n":NaN}', '{"n":Infinity}'):
        source.write_text(body)
        with pytest.raises(HumanVerificationError):
            read_operator_json(source)


def test_symlinks_world_writable_registry_and_nonregular_files_rejected(tmp_path):
    source = tmp_path / "actual.json"
    source.write_text("{}")
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(source)
    with pytest.raises(HumanVerificationError):
        read_operator_json(symlink)
    dirlink = tmp_path / "linked-dir"
    dirlink.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(HumanVerificationError):
        read_operator_json(dirlink / "actual.json")
    source.chmod(0o666)
    with pytest.raises(HumanVerificationError):
        read_operator_json(source, protected=True)
    with pytest.raises(HumanVerificationError):
        read_operator_json(tmp_path)


def test_safe_log_ingestion_checks_digest_and_rejects_symlink(tmp_path):
    digest = hashlib.sha256(LOG).hexdigest()
    folder = tmp_path / "evidence"
    folder.mkdir()
    target = folder / digest
    target.write_bytes(LOG)
    attestations = [{"test": {"log_sha256": digest}}]
    assert read_test_logs(folder, attestations) == {digest: LOG}
    target.write_bytes(b"tampered")
    with pytest.raises(HumanVerificationError):
        read_test_logs(folder, attestations)
    target.unlink()
    outside = tmp_path / "secret"
    outside.write_bytes(LOG)
    target.symlink_to(outside)
    with pytest.raises(HumanVerificationError):
        read_test_logs(folder, attestations)


def test_unbounded_inputs_fail_closed(tmp_path):
    file = tmp_path / "oversized.json"
    file.write_text("x" * 100)
    with pytest.raises(HumanVerificationError):
        read_operator_json(file, max_bytes=50)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(HumanVerificationError):
        read_test_logs(evidence, [{"test": {"log_sha256": "../private"}}])
