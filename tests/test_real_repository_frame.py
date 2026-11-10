"""R8.04i contract: real Git source outside the diff, model scope and signatures.

Fixture commits are real local Git objects. Label decisions are SYNTHETIC
tests, never real-human defect accuracy evidence.
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
from daddy_reviews.ground_truth_labels import FORMAT as SIGNED, label_signing_bytes
from daddy_reviews.human_attestation import HumanVerificationError
from daddy_reviews.real_repository_frame import (
    build_opportunity_frame, write_opportunity_frame_files, RealIntakeError,
)
from daddy_reviews.real_repository_frame_quality import audit_opportunity_labels
from test_real_repository_intake import run, model_report


def repository_fixture(tmp_path):
    root = tmp_path / "real-repo"
    root.mkdir()
    run(root, "init", "-q")
    source = root / "src"
    source.mkdir()
    (source / "check.py").write_text(
        "def allow(user):\n    return user is not None\n", encoding="utf-8")
    (source / "legacy.py").write_text(
        "def old_feature(x):\n"
        "    if x == 0:\n"
        "        return 0\n"
        "    return x * 2\n",
        encoding="utf-8")
    run(root, "add", ".")
    run(root, "-c", "user.name=Evidence Test",
        "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "base commit contains unchanged legacy code")
    base = run(root, "rev-parse", "HEAD")
    (source / "check.py").write_text(
        "def allow(user):\n"
        "    if user is None:\n"
        "        return False\n"
        "    if user == 'admin':\n"
        "        return True\n"
        "    return bool(user)\n",
        encoding="utf-8")
    run(root, "add", "src/check.py")
    run(root, "-c", "user.name=Evidence Test",
        "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "head commit modifies one file only")
    return root, base, run(root, "rev-parse", "HEAD")


def options(base, head, report=None):
    return {
        "repository": "owner/real-fixture",
        "repository_id": 178231,
        "base_commit": base, "head_commit": head,
        "seed": "blind-context-opportunities-2026",
        "max_cases": 20, "report": report,
    }


def signed_material(frame, opts):
    secret, registry = {}, {}
    for name in ("independent-one", "independent-two"):
        sk = Ed25519PrivateKey.generate()
        secret[name] = sk
        registry[name] = {
            "reviewer_id": name, "role": "ground_truth_adjudicator",
            "enabled": True,
            "public_key_b64": base64.b64encode(
                sk.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )).decode("ascii"),
        }
    private_by_id = {r["case_id"]: r for r in frame["private_ledger"]["cases"]}
    first_missed = next((r["case_id"] for r in private_by_id.values()
                         if r["stratum"] == "added_unflagged"), None)
    first_flagged = next((r["case_id"] for r in private_by_id.values()
                          if r["stratum"] == "added_flagged"), None)
    first_legacy = next((r["case_id"] for r in private_by_id.values()
                         if r["stratum"] == "unchanged_other"), None)
    defects = {first_missed, first_flagged, first_legacy} - {None}
    labels, blobs = [], {}
    for case in frame["blind_packet"]["cases"]:
        for name, key in secret.items():
            evidence = (
                "Fixture-only signed reproduction bytes. "
                + case["case_id"] + " checked by " + name
            ).encode("utf-8")
            digest = hashlib.sha256(evidence).hexdigest()
            blobs[digest] = evidence
            record = {
                "format": SIGNED, "case_id": case["case_id"],
                "candidate_id": case["case_id"],
                "snapshot_id": opts["head_commit"],
                "patch_sha256": frame["blind_packet"]["patch_sha256"],
                "tier": case["tier"],
                "label": "defect" if case["case_id"] in defects else "clean",
                "reviewer_id": name, "key_id": name,
                "signed_at": "2026-11-10T14:00:00Z",
                "blind_protocol": "separate_from_model_and_resolution_v1",
                "evidence_sha256": digest,
                "rationale": "Synthetic adjudication for negative security regression checks.",
                "signature_b64": "",
            }
            record["signature_b64"] = base64.b64encode(
                key.sign(label_signing_bytes(record))).decode("ascii")
            labels.append(record)
    return labels, registry, blobs, secret


def audit(root, frame, labels, registry, blobs, opts):
    return audit_opportunity_labels(
        root, frame["blind_packet"], frame["private_ledger"],
        labels, registry, blobs, **opts)


def test_immutable_git_frame_covers_changed_context_and_untouched_code(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    report = model_report(root, base, head)
    opts = options(base, head, report)
    left = build_opportunity_frame(root, **opts)
    right = build_opportunity_frame(root, **opts)
    assert left == right
    assert left["status"] == "real_source_opportunity_frame_not_labels"
    assert left["sampling_design"] == "deterministic_model_stratified_nonprobability_line_sample"
    assert left["defect_truth_claim"] is False
    assert left["population_accuracy_claim"] is False
    packet = left["blind_packet"]
    assert {c["stratum"] for c in packet["cases"]} == {
        "added", "unchanged_touched", "unchanged_other"}
    assert packet["model_predictions_included"] is False
    assert "SAMPLE-RULE" not in json.dumps(packet)
    assert "model_flagged" not in json.dumps(packet)
    assert all(c["label"] is None for c in packet["cases"])
    private = left["private_ledger"]
    strata = {c["stratum"] for c in private["cases"]}
    assert {"added_flagged", "added_unflagged", "unchanged_touched", "unchanged_other"} <= strata
    assert all(c["model_flagged"] is None
               for c in private["cases"] if c["stratum"].startswith("unchanged"))
    assert private["population"]["eligible_by_source_stratum"]["unchanged_other"] >= 2
    assert packet["head_commit"] == head
    assert private["blind_packet_sha256"]


def test_unreported_context_cannot_be_treated_as_model_missed_defect(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head, model_report(root, base, head))
    frame = build_opportunity_frame(root, **opts)
    labels, keys, blobs, _ = signed_material(frame, opts)
    result = audit(root, frame, labels, keys, blobs, opts)
    assert result["status"] == "scope_separated_sample_observations_only"
    assert result["counts"]["added_flagged_defect"] == 1
    assert result["counts"]["added_unflagged_defect"] == 1
    assert result["counts"]["unchanged_other_defect"] == 1
    assert result["observed_sample_metrics"]["added_sample_unweighted_recall"] == 0.5
    assert result["observed_sample_metrics"]["unchanged_other_defect_opportunities"] == 1
    assert result["observed_sample_metrics"]["eligible_scope"] == "added_lines_only"
    assert result["observed_sample_metrics"]["biased_stratified_sample_no_population_inference"]
    assert not result["factual_defect_truth_proven"]
    assert not result["population_accuracy_claim"]
    assert not result["promotion_eligible"]
    assert result["github_publication"] == result["merge_action"] == "none"


def test_without_model_all_code_can_be_labeled_but_no_prediction_metrics(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head)
    frame = build_opportunity_frame(root, **opts)
    assert frame["private_ledger"]["prediction_mode"] == "no_model_report"
    assert not any(c["model_flagged"] is not None for c in frame["private_ledger"]["cases"])
    labels, keys, blobs, _ = signed_material(frame, opts)
    result = audit(root, frame, labels, keys, blobs, opts)
    assert result["status"] == "source_labels_authenticated_model_predictions_absent"
    assert result["observed_sample_metrics"] is None
    assert result["counts"]["unchanged_other_defect"] == 1


def test_private_ledger_blind_and_seed_modification_are_rejected(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head, model_report(root, base, head))
    frame = build_opportunity_frame(root, **opts)
    labels, keys, blobs, _ = signed_material(frame, opts)
    for mutate in (
        lambda x: x["private_ledger"]["cases"][0].update(model_flagged=True),
        lambda x: x["blind_packet"]["cases"][0].update(stratum="added"),
        lambda x: x["blind_packet"]["population"].update(eligible_nonblank_lines=0),
        lambda x: x["private_ledger"]["population"].update(eligible_code_files=0),
    ):
        corrupted = copy.deepcopy(frame)
        mutate(corrupted)
        # Mutators must not be no-ops; change flag by inversion when already true.
        if corrupted["private_ledger"] == frame["private_ledger"] and corrupted["blind_packet"] == frame["blind_packet"]:
            corrupted["private_ledger"]["cases"][0]["model_rules"] = ["tampered"]
        with pytest.raises(HumanVerificationError):
            audit(root, corrupted, labels, keys, blobs, opts)
    with pytest.raises(HumanVerificationError):
        audit(root, frame, labels, keys, blobs, {**opts, "seed": "different-study-seed"})


def test_conflict_and_missing_signature_do_not_produce_score(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head, model_report(root, base, head))
    frame = build_opportunity_frame(root, **opts)
    labels, keys, blobs, secret = signed_material(frame, opts)
    with pytest.raises(HumanVerificationError):
        audit(root, frame, labels[1:], keys, blobs, opts)
    with pytest.raises(HumanVerificationError):
        audit(root, frame, [{**labels[0], "signature_b64": "forged"}, *labels[1:]],
              keys, blobs, opts)
    changed = copy.deepcopy(labels)
    changed[1]["label"] = "clean" if changed[1]["label"] == "defect" else "defect"
    changed[1]["signature_b64"] = base64.b64encode(
        secret[changed[1]["reviewer_id"]].sign(label_signing_bytes(changed[1]))
    ).decode("ascii")
    dispute = audit(root, frame, changed, keys, blobs, opts)
    assert dispute["status"] == "conflicting_labels_human_escalation"
    assert dispute["observed_sample_metrics"] is None
    assert dispute["counts"] is None
    assert dispute["promotion_eligible"] is False


def test_immutable_git_objects_not_changed_worktree(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head)
    frame = build_opportunity_frame(root, **opts)
    (root / "src/legacy.py").write_text("malicious worktree only\n")
    assert build_opportunity_frame(root, **opts) == frame


def test_exclusive_owner_only_frame_export_and_cli_summary(tmp_path, capsys):
    root, base, head = repository_fixture(tmp_path)
    folder = tmp_path / "research"
    folder.mkdir(mode=0o700)
    cli.main([
        "opportunity-sample", "--root", str(root),
        "--base", base, "--head", head,
        "--attestation-repo", "owner/real-fixture",
        "--attestation-repo-id", "178231",
        "--real-sample-seed", "blind-context-opportunities-2026",
        "--real-sample-max-cases", "20",
        "--real-blind-output", str(folder / "blind.json"),
        "--real-private-output", str(folder / "sealed-model.json"),
    ])
    reply = json.loads(capsys.readouterr().out)
    assert reply["status"] == "opportunity_blind_packet_created"
    assert reply["population_accuracy_claim"] is False
    assert "source_line_untrusted" not in json.dumps(reply)
    assert (folder / "blind.json").stat().st_mode & 0o077 == 0
    assert (folder / "sealed-model.json").stat().st_mode & 0o077 == 0
    assert "model_flagged" not in (folder / "blind.json").read_text()
    assert "model_flagged" in (folder / "sealed-model.json").read_text()
    with pytest.raises(RealIntakeError):
        write_opportunity_frame_files(
            build_opportunity_frame(root, **options(base, head)),
            folder / "blind.json", folder / "sealed-model.json")


def test_cli_audits_signed_labels_without_leaking_source_or_keys(tmp_path, capsys):
    root, base, head = repository_fixture(tmp_path)
    opts = options(base, head, model_report(root, base, head))
    frame = build_opportunity_frame(root, **opts)
    labels, keys, blobs, _ = signed_material(frame, opts)
    work = tmp_path / "private"
    work.mkdir(mode=0o700)
    blind, private, labels_file, trusted, report = (
        work / name for name in
        ("blind.json", "private.json", "labels.json", "keys.json", "report.json"))
    for path, obj in (
        (blind, frame["blind_packet"]), (private, frame["private_ledger"]),
        (labels_file, labels), (trusted, keys), (report, opts["report"]),
    ):
        path.write_text(json.dumps(obj))
    trusted.chmod(0o600)
    folder = work / "evidence"
    folder.mkdir()
    for digest, contents in blobs.items():
        (folder / digest).write_bytes(contents)
    cli.main([
        "opportunity-audit", "--root", str(root),
        "--base", base, "--head", head,
        "--attestation-repo", opts["repository"],
        "--attestation-repo-id", str(opts["repository_id"]),
        "--real-sample-seed", opts["seed"],
        "--real-sample-max-cases", str(opts["max_cases"]),
        "--real-model-report", str(report),
        "--real-blind-file", str(blind),
        "--real-private-file", str(private),
        "--label-attestations-file", str(labels_file),
        "--label-trust-keys-file", str(trusted),
        "--label-evidence-dir", str(folder),
    ])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "scope_separated_sample_observations_only"
    assert not result["factual_defect_truth_proven"]
    assert result["observed_sample_metrics"]["unchanged_other_defect_opportunities"] == 1
    assert "Fixture-only signed reproduction" not in json.dumps(result)


def test_git_symlink_masquerading_as_changed_code_rejected(tmp_path):
    root, base, head = repository_fixture(tmp_path)
    run(root, "checkout", "-q", "-b", "symlinks", base)
    path = root / "src" / "fake.py"
    path.symlink_to("legacy.py")
    run(root, "add", "src/fake.py")
    run(root, "-c", "user.name=Evidence Test",
        "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "malicious tracked symlink")
    new_head = run(root, "rev-parse", "HEAD")
    with pytest.raises(RealIntakeError):
        build_opportunity_frame(root, **options(base, new_head))
