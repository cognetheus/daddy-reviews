"""R8.04e.02: only real verified artifact identities can join human logs.

Here the external gh verification is mocked; the separate Sigstore workflow
exercises a genuine GitHub-issued attestation and trust root in Actions.
"""
import hashlib
import json

import pytest

from daddy_reviews import cli as cli_module
from test_operator_artifacts import build_inputs

REPO = "cognetheus/daddy-reviews"
SIGNER = "cognetheus/daddy-reviews/.github/workflows/attestation-integration.yml"


def command(root):
    files = build_inputs(root)
    humans = json.loads(files["attestations_file"].read_text())
    digest = humans[0]["test"]["log_sha256"]
    artifact = files["evidence_dir"] / digest
    bundle = root / "bundle.jsonl"
    trusted = root / "trusted-root.jsonl"
    bundle.write_text('{"fixture":"untrusted"}\n')
    trusted.write_text('{"fixture":"root"}\n')
    return [
        "human-verify", "--root", str(root),
        "--diff-file", str(files["patch_file"]),
        "--report-file", str(files["report_file"]),
        "--attestations-file", str(files["attestations_file"]),
        "--trusted-keys-file", str(files["trust_keys_file"]),
        "--evidence-dir", str(files["evidence_dir"]),
        "--attested-artifact-file", str(artifact),
        "--attestation-bundle-file", str(bundle),
        "--sigstore-trusted-root-file", str(trusted),
        "--gh-binary", "/usr/bin/gh",
        "--gh-binary-sha256", "b" * 64,
        "--attestation-repo", REPO,
        "--attestation-repo-id", "12345",
        "--attestation-commit", "a" * 40,
        "--attestation-signer-workflow", SIGNER,
        "--attestation-artifact-sha256", digest,
    ], digest


def test_hosted_attestation_joins_signed_human_logs(monkeypatch, tmp_path, capsys):
    args, digest = command(tmp_path)
    verified = []
    def verifier(**opts):
        verified.append(opts)
        return {
            "status": "artifact_signature_and_identity_verified",
            "artifact_sha256": opts["expected_artifact_sha256"],
            "platform_oidc_verified": True,
            "test_outcome_proven": False,
        }
    monkeypatch.setattr(cli_module, "verify_github_attestation_offline", verifier)
    cli_module.main(args)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "human_attested_resolution"
    attestation = result["external_artifact_attestation"]
    assert attestation["status"] == "artifact_signature_and_identity_verified"
    assert attestation["linked_human_test_count"] == 2
    assert attestation["uncovered_human_test_log_count"] == 0
    assert verified[0]["expected_artifact_sha256"] == digest
    assert result["github_publication"] == result["merge_action"] == "none"


def test_attestation_for_different_digest_never_claims_human_proof(
        monkeypatch, tmp_path, capsys):
    args, digest = command(tmp_path)
    def verifier(**opts):
        return {"status": "artifact_signature_and_identity_verified",
                "artifact_sha256": "0" * 64,
                "platform_oidc_verified": True, "test_outcome_proven": False}
    monkeypatch.setattr(cli_module, "verify_github_attestation_offline", verifier)
    with pytest.raises(SystemExit) as e:
        cli_module.main(args)
    assert e.value.code == 2
    assert "does not bind" in capsys.readouterr().err


def test_partial_hosted_attestation_flags_fail_closed(monkeypatch, tmp_path, capsys):
    args, _ = command(tmp_path)
    index = args.index("--gh-binary-sha256")
    del args[index:index+2]
    called = []
    monkeypatch.setattr(cli_module, "verify_github_attestation_offline",
                        lambda **kw: called.append(kw))
    with pytest.raises(SystemExit) as e:
        cli_module.main(args)
    assert e.value.code == 2
    assert not called
