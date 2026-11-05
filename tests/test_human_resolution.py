"""R8.04c: signed human test receipts, source binding and conflict adjudication."""
import base64
import copy
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews.human_attestation import (
    FORMAT as HUMAN_FORMAT, HumanVerificationError, sha256_json, signing_bytes,
)
from daddy_reviews.human_resolution import adjudicate_human_verification
from daddy_reviews.independent_challenge import challenge_findings
from daddy_reviews.investigative_agents import investigate_with_specialists

PATCH = (
    "diff --git a/src/auth.py b/src/auth.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n+++ b/src/auth.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def authorize(user):\n"
    "+    return bool(user)\n"
)
LOG = b"collected by human-controlled CI\nObserved authorization mismatch\n"


def _original(root):
    source = root / "src/auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def authorize(user):\n    return bool(user)\n", encoding="utf-8")

    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {"tool": "read_file",
                     "path": "src/auth.py", "start_line": 1, "end_line": 2}}
        return {"kind": "final", "findings": [{
            "rule": "AUTH-BOOL", "path": "src/auth.py", "line": 2,
            "claim": "Truthy strings might bypass authorization",
            "evidence": "Role checks are absent in the function",
            "severity": "high", "citations": ["E1"],
        }]}
    report = investigate_with_specialists(
        root, PATCH, provider, reviewers=("security",),
        allowed_tools={"read_file"}, max_workers=1,
    )
    assert report["status"] == "complete"
    assert len(report["verification_queue"]["items"]) == 1
    return report


def _challenge(root, report, verdict):
    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {"tool": "read_file",
                     "path": "src/auth.py", "start_line": 1, "end_line": 2}}
        return {"kind": "final", "verdict": verdict,
                "reason": "The caller may enforce role policy elsewhere",
                "citations": ["E1"]}
    result = challenge_findings(
        root, PATCH, report, provider, reviewer="code-quality",
        allowed_tools={"read_file"},
    )
    assert result["status"] == "completed_advisory"
    return result


def _key(reviewer):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, {"reviewer_id": reviewer, "role": "human_verifier",
                     "enabled": True, "public_key_b64": base64.b64encode(public).decode()}


def _signed(report, key_id, reviewer, private, *, decision="confirm",
            challenge=None, acknowledged=False, log=LOG):
    item = report["verification_queue"]["items"][0]
    digest = hashlib.sha256(log).hexdigest()
    evidence = {
        "test_id": "tests/test_auth.py::test_authorization",
        "command": "pytest -q tests/test_auth.py::test_authorization",
        "environment": "linux-ci python3.12 isolated test",
        "outcome": {"confirm": "reproduced", "reject": "not_reproduced",
                    "inconclusive": "inconclusive"}[decision],
        "log_sha256": digest,
    }
    record = {
        "format": HUMAN_FORMAT, "candidate_id": item["id"],
        "snapshot_id": report["snapshot_id"],
        "patch_sha256": report["patch_sha256"],
        "source_sha256": item["source_spans"][0]["sha256"],
        "reviewer_id": reviewer, "key_id": key_id,
        "signed_at": "2026-11-05T19:30:00Z",
        "decision": decision,
        "rationale": "I reviewed a bounded independent execution record.",
        "challenge_sha256": sha256_json(challenge["outcomes"][0]) if challenge else None,
        "challenge_acknowledged": acknowledged,
        "test": evidence, "signature_b64": "",
    }
    record["signature_b64"] = base64.b64encode(private.sign(signing_bytes(record))).decode()
    return record


@pytest.fixture
def scenario(tmp_path):
    report = _original(tmp_path)
    alice, ta = _key("alice")
    bob, tb = _key("bob")
    carol, tc = _key("carol")
    trusted = {"alice-key": ta, "bob-key": tb, "carol-key": tc}
    return tmp_path, report, trusted, {
        "alice": alice, "bob": bob, "carol": carol,
    }, {hashlib.sha256(LOG).hexdigest(): LOG}


def _records(report, keys, *, decision="confirm", challenge=None, acknowledged=False):
    return [
        _signed(report, "alice-key", "alice", keys["alice"], decision=decision,
                challenge=challenge, acknowledged=acknowledged),
        _signed(report, "bob-key", "bob", keys["bob"], decision=decision,
                challenge=challenge, acknowledged=acknowledged),
    ]


def _resolve(scenario, records, challenge=None, **kwargs):
    root, report, trusted, _, logs = scenario
    return adjudicate_human_verification(
        root, PATCH, report, records, trusted, logs,
        challenge=challenge, **kwargs,
    )


def test_two_distinct_signed_human_test_receipts_attest_without_publishing(scenario):
    _, report, _, keys, _ = scenario
    records = _records(report, keys)
    result = _resolve(scenario, records)
    assert result["status"] == "human_attested_resolution"
    assert result["decisions"][0]["status"] == "human_attested_confirmed"
    assert result["human_attested_confirmations"] == 1
    assert result["confirmed_findings"] == 0
    assert result["github_publication"] == result["merge_action"] == "none"
    assert len(result["audit"]) == 2
    assert all(r["signature_verified"] and r["log_digest_verified"] for r in result["audit"])
    assert "Observed authorization mismatch" not in str(result)
    assert result == _resolve(scenario, records)


def test_single_signature_and_inconclusive_do_not_resolve(scenario):
    _, report, _, keys, _ = scenario
    records = _records(report, keys)
    first = _resolve(scenario, records[:1])
    assert first["decisions"][0]["status"] == "insufficient_independent_human_evidence"
    neutral = _signed(report, "bob-key", "bob", keys["bob"], decision="inconclusive")
    result = _resolve(scenario, [records[0], neutral])
    assert result["status"] == "human_attention_required"
    assert result["resolved_count"] == 0


def test_two_human_rejections_remain_advisory(scenario):
    _, report, _, keys, _ = scenario
    records = _records(report, keys, decision="reject")
    result = _resolve(scenario, records)
    assert result["decisions"][0]["status"] == "human_attested_rejected"
    assert result["merge_action"] == "none"


def test_signed_model_disagreement_requires_explicit_acknowledgment(scenario):
    root, report, _, keys, _ = scenario
    challenge = _challenge(root, report, "refuted")
    missing_ack = _records(report, keys, challenge=challenge, acknowledged=False)
    result = _resolve(scenario, missing_ack, challenge)
    assert result["decisions"][0]["status"] == "model_disagreement_unacknowledged"
    assert result["decisions"][0]["model_disagreement"] is True
    acknowledged = _records(report, keys, challenge=challenge, acknowledged=True)
    result = _resolve(scenario, acknowledged, challenge)
    assert result["decisions"][0]["status"] == "human_attested_confirmed"
    assert result["decisions"][0]["disagreement_acknowledged"] is True
    assert result["github_publication"] == "none"


def test_human_disagreement_never_resolves(scenario):
    _, report, _, keys, _ = scenario
    confirm = _signed(report, "alice-key", "alice", keys["alice"])
    reject = _signed(report, "bob-key", "bob", keys["bob"], decision="reject")
    result = _resolve(scenario, [confirm, reject])
    assert result["decisions"][0]["status"] == "conflicting_human_attestations"
    assert result["status"] == "human_attention_required"


def test_source_log_and_signature_tampering_fail_closed(scenario):
    _, report, trusted, keys, logs = scenario
    record = _signed(report, "alice-key", "alice", keys["alice"])
    for field, bad in (
        ("decision", "reject"), ("rationale", "changed after signing"),
        ("source_sha256", "0" * 64), ("snapshot_id", "stale"),
        ("patch_sha256", "0" * 64), ("candidate_id", "forged"),
        ("signature_b64", "not-base64"),
    ):
        mutated = copy.deepcopy(record)
        mutated[field] = bad
        with pytest.raises(HumanVerificationError):
            _resolve(scenario, [mutated])
    changed_log = {next(iter(logs)): b"tampered log"}
    with pytest.raises(HumanVerificationError):
        adjudicate_human_verification(
            scenario[0], PATCH, report, [record], trusted, changed_log
        )
    no_log = {}
    with pytest.raises(HumanVerificationError):
        adjudicate_human_verification(
            scenario[0], PATCH, report, [record], trusted, no_log
        )


def test_key_registry_is_external_and_must_be_enabled(scenario):
    root, report, trust, keys, logs = scenario
    record = _signed(report, "alice-key", "alice", keys["alice"])
    for tamper in (
        lambda t: t["alice-key"].update(enabled=False),
        lambda t: t["alice-key"].update(role="agent"),
        lambda t: t["alice-key"].update(reviewer_id="mallory"),
        lambda t: t.pop("alice-key"),
    ):
        changed = copy.deepcopy(trust)
        tamper(changed)
        with pytest.raises(HumanVerificationError):
            adjudicate_human_verification(root, PATCH, report, [record], changed, logs)


def test_duplicate_human_and_replay_to_other_challenge_rejected(scenario):
    root, report, _, keys, _ = scenario
    record = _signed(report, "alice-key", "alice", keys["alice"])
    with pytest.raises(HumanVerificationError):
        _resolve(scenario, [record, record])
    challenged = _challenge(root, report, "uncertain")
    with pytest.raises(HumanVerificationError):
        _resolve(scenario, [record], challenged)
    different = _challenge(root, report, "refuted")
    bound = _signed(report, "alice-key", "alice", keys["alice"], challenge=challenged)
    with pytest.raises(HumanVerificationError):
        _resolve(scenario, [bound], different)


def test_modified_source_abstains_even_with_valid_human_signature(scenario):
    root, report, _, keys, _ = scenario
    record = _signed(report, "alice-key", "alice", keys["alice"])
    (root / "src/auth.py").write_text("def authorize(user):\n    return True\n")
    with pytest.raises(HumanVerificationError):
        _resolve(scenario, [record])


def test_unauthorized_fields_and_bad_outcome_rejected(scenario):
    _, report, _, keys, _ = scenario
    record = _signed(report, "alice-key", "alice", keys["alice"])
    for changed in (
        dict(record, merge_action="approve"),
        dict(record, signature_b64=""),
        dict(record, test=dict(record["test"], outcome="not_reproduced")),
    ):
        with pytest.raises(HumanVerificationError):
            _resolve(scenario, [changed])


def test_report_without_human_artifacts_not_clean_proof(scenario):
    result = _resolve(scenario, [])
    assert result["status"] == "human_attention_required"
    assert result["decisions"][0]["status"] == "awaiting_human_verification"
    assert result["resolved_count"] == 0
    assert result["confirmed_findings"] == 0
