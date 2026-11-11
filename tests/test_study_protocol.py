"""R8.04j signed preregistration, unchanged source, uncertainty and human agreement.

Synthetic lab adjudications over ACTUAL local Git object fixtures; tests do
not imply external human researchers or authenticated registration chronology.
"""
import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from daddy_reviews import cli
from daddy_reviews.human_attestation import HumanVerificationError, sha256_json
from daddy_reviews.real_repository_frame import build_opportunity_frame
from daddy_reviews.real_repository_intake import RealIntakeError
from daddy_reviews.study_protocol import (
    PLAN_FORMAT, REGISTRATION_FORMAT, RECORD_FORMAT,
    create_study_plan, registration_signing_bytes, observation_signing_bytes,
    audit_preregistered_study, write_study_plan,
)
from test_real_repository_frame import repository_fixture, options
from test_real_repository_intake import model_report

STUDY = "preregistered-github-source-2026"
REVIEWERS = ("independent-ada", "independent-bob")
REGISTERED_AT = "2026-11-09T12:00:00Z"


def _key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode("ascii")


def material(tmp_path, *, with_model=True):
    root, base, head = repository_fixture(tmp_path)
    report = model_report(root, base, head) if with_model else None
    opts = options(base, head, report)
    frame = build_opportunity_frame(root, **opts)
    plan = create_study_plan(
        frame, study_id=STUDY, reviewer_ids=list(REVIEWERS)[::-1],
        registered_at=REGISTERED_AT)
    registrar_key, registrar_pub = _key()
    registration = {
        "format": REGISTRATION_FORMAT,
        "plan": plan,
        "registrar_id": "registrar-ops", "key_id": "registrar-key",
        "signature_b64": "",
    }
    registration["signature_b64"] = base64.b64encode(
        registrar_key.sign(registration_signing_bytes(registration))).decode("ascii")
    registrar_registry = {
        "registrar-key": {"reviewer_id": "registrar-ops",
                          "role": "study_registrar", "enabled": True,
                          "public_key_b64": registrar_pub}
    }
    keys = {}
    review_secrets = {}
    for name in REVIEWERS:
        private, pub = _key()
        review_secrets[name] = private
        keys[name + "-key"] = {
            "reviewer_id": name, "role": "ground_truth_adjudicator",
            "enabled": True, "public_key_b64": pub,
        }
    labels, evidence = [], {}
    for idx, case in enumerate(plan["cases"]):
        for name in REVIEWERS:
            raw = (
                f"Synthetic independently labeled source case {case['case_id']} "
                f"from Git HEAD {head}; labeler {name}"
            ).encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            evidence[digest] = raw
            observation = {
                "format": RECORD_FORMAT,
                "study_plan_sha256": sha256_json(plan),
                "case_id": case["case_id"],
                "source_sha256": case["source_sha256"],
                "line_sha256": case["line_sha256"],
                "head_commit": head,
                "reviewer_id": name, "key_id": name + "-key",
                "decision": "defect" if idx % 3 == 0 else "clean",
                "blind_protocol": "separate_from_model_and_resolution_v1",
                "signed_at": "2026-11-10T14:01:00Z",
                "evidence_sha256": digest,
                "rationale": "Fixture-only signed independent review observation; no real humans involved.",
                "signature_b64": "",
            }
            observation["signature_b64"] = base64.b64encode(
                review_secrets[name].sign(observation_signing_bytes(observation))).decode("ascii")
            labels.append(observation)
    return {
        "root": root, "opts": opts, "frame": frame, "plan": plan,
        "registration": registration, "registration_hash": sha256_json(registration),
        "registrar_keys": registrar_registry,
        "labels": labels, "adjudicator_keys": keys,
        "evidence": evidence, "reviewer_secrets": review_secrets,
        "registrar_secret": registrar_key,
    }


def run_audit(s, **changes):
    args = {
        "root": s["root"], "registration": s["registration"],
        "expected_registration_sha256": s["registration_hash"],
        "blind_packet": s["frame"]["blind_packet"],
        "private_ledger": s["frame"]["private_ledger"],
        "labels": s["labels"],
        "registrar_keys": s["registrar_keys"],
        "adjudicator_keys": s["adjudicator_keys"],
        "evidence_blobs": s["evidence"],
        **s["opts"],
    }
    args.update(changes)
    root = args.pop("root")
    return audit_preregistered_study(root, **args)


def resign(s, label):
    label["signature_b64"] = base64.b64encode(
        s["reviewer_secrets"][label["reviewer_id"]].sign(
            observation_signing_bytes(label))).decode("ascii")


def test_study_plan_freezes_sample_and_approved_reviewer_roster(tmp_path):
    s = material(tmp_path)
    plan = s["plan"]
    assert plan["format"] == PLAN_FORMAT
    assert plan["frozen_reviewer_ids"] == sorted(REVIEWERS)
    assert plan["labels_per_case"] == 2
    assert plan["registered_at"] == REGISTERED_AT
    assert plan["model_predictions_included"] is False
    assert plan["frame_sha256"] == s["frame"]["frame_sha256"]
    assert plan["sealed_ledger_sha256"] == sha256_json(s["frame"]["private_ledger"])
    assert set(x["case_id"] for x in plan["cases"]) == set(
        x["case_id"] for x in s["frame"]["blind_packet"]["cases"])
    assert "model_flagged" not in json.dumps(plan)
    assert plan["chronology_independently_proven"] is False
    assert not plan["population_accuracy_claim"]
    assert plan["score_scope"] == "descriptive_sample_added_lines_only"


def test_signed_registration_and_two_reviewers_all_agree(tmp_path):
    s = material(tmp_path)
    result = run_audit(s)
    assert result["status"] == "preregistered_sample_observations_only"
    assert result["registration_sha256"] == s["registration_hash"]
    assert result["expected_cases"] == len(s["plan"]["cases"])
    assert result["completion"]["pending"] == 0
    assert result["completion"]["disagreements"] == 0
    assert result["completion"]["mutual_uncertainty"] == 0
    assert result["signed_observations"] == 2 * len(s["plan"]["cases"])
    assert result["inter_rater_agreement"]["raw_agreement"] == 1.0
    assert result["inter_rater_agreement"]["cohen_kappa_three_label"] == 1.0
    assert result["sample_observations"]["biased_stratified_line_sample"]
    assert result["sample_observations"]["context_defects_not_model_false_negatives"] >= 0
    assert result["preregistration_chronology_independently_proven"] is False
    assert result["population_accuracy_claim"] is False
    assert result["promotion_eligible"] is False
    assert result["github_publication"] == result["merge_action"] == "none"


def test_no_model_report_keeps_all_prediction_metrics_unavailable(tmp_path):
    s = material(tmp_path, with_model=False)
    result = run_audit(s)
    assert result["status"] == "preregistered_labels_authenticated_no_model_report"
    assert result["sample_observations"] is None
    assert result["completion"]["pending"] == 0


@pytest.mark.parametrize("modified", [
    "registration-sha", "registrar-signature", "registrar-role",
    "roster", "registered-at", "source-head", "private-ledger",
])
def test_frozen_registration_and_source_cannot_be_refitted_after_labeling(tmp_path, modified):
    s = material(tmp_path)
    modified_args = {}
    if modified == "registration-sha":
        modified_args["expected_registration_sha256"] = "0" * 64
    elif modified == "registrar-signature":
        s["registration"]["signature_b64"] = "invalid-signature"
        s["registration_hash"] = sha256_json(s["registration"])
    elif modified == "registrar-role":
        s["registrar_keys"]["registrar-key"]["role"] = "ground_truth_adjudicator"
    elif modified == "roster":
        s["registration"]["plan"]["frozen_reviewer_ids"] = ["different", "person"]
        s["registration_hash"] = sha256_json(s["registration"])
    elif modified == "registered-at":
        s["registration"]["plan"]["registered_at"] = "2026-11-12T00:00:00Z"
        s["registration_hash"] = sha256_json(s["registration"])
    elif modified == "source-head":
        modified_args["head_commit"] = "b" * 40
    else:
        sealed = copy.deepcopy(s["frame"]["private_ledger"])
        sealed["population"]["eligible_nonblank_lines"] = -1
        modified_args["private_ledger"] = sealed
    with pytest.raises((HumanVerificationError, ValueError)):
        run_audit(s, **modified_args)


@pytest.mark.parametrize("field,new_value", [
    ("source_sha256", "0" * 64),
    ("line_sha256", "0" * 64),
    ("case_id", "fakecase"),
    ("head_commit", "b" * 40),
    ("study_plan_sha256", "0" * 64),
    ("evidence_sha256", "0" * 64),
    ("signature_b64", "totally-invalid"),
    ("reviewer_id", "unlisted-human"),
    ("decision", "defect_and_clean"),
])
def test_signed_observation_tampering_is_rejected(tmp_path, field, new_value):
    s = material(tmp_path)
    observed = copy.deepcopy(s["labels"])
    observed[0][field] = new_value
    with pytest.raises(HumanVerificationError):
        run_audit(s, labels=observed)


def test_separate_human_signatures_missing_and_untrusted_evidence(tmp_path):
    s = material(tmp_path)
    report = run_audit(s, labels=s["labels"][:-1])
    assert report["status"] == "pending_or_disputed_human_adjudication"
    assert report["completion"]["pending"] == 1
    assert report["sample_observations"] is None
    with pytest.raises(HumanVerificationError):
        run_audit(s, labels=[s["labels"][0], s["labels"][0], *s["labels"][1:]])
    broken = dict(s["evidence"])
    broken[s["labels"][0]["evidence_sha256"]] = b"modified-evidence"
    with pytest.raises(HumanVerificationError):
        run_audit(s, evidence_blobs=broken)


def test_uncertain_and_conflicting_labels_are_escalated_not_scored(tmp_path):
    s = material(tmp_path)
    conflicted = copy.deepcopy(s["labels"])
    first_two = conflicted[:2]
    assert first_two[0]["case_id"] == first_two[1]["case_id"]
    first_two[1]["decision"] = ("clean" if first_two[0]["decision"] == "defect"
                                 else "defect")
    resign(s, first_two[1])
    result = run_audit(s, labels=conflicted)
    assert result["status"] == "pending_or_disputed_human_adjudication"
    assert result["completion"]["disagreements"] == 1
    assert result["completion"]["unresolved_case_ids"] == [first_two[0]["case_id"]]
    assert result["sample_observations"] is None

    undecided = copy.deepcopy(s["labels"])
    undecided[0]["decision"] = "uncertain"
    undecided[1]["decision"] = "uncertain"
    for rec in undecided[:2]:
        resign(s, rec)
    result = run_audit(s, labels=undecided)
    assert result["completion"]["mutual_uncertainty"] == 1
    assert result["sample_observations"] is None
    assert result["inter_rater_agreement"]["raw_agreement"] == 1.0


def test_registrar_key_and_review_key_cannot_be_reused(tmp_path):
    s = material(tmp_path)
    used_pub = s["registrar_keys"]["registrar-key"]["public_key_b64"]
    s["adjudicator_keys"]["independent-ada-key"]["public_key_b64"] = used_pub
    with pytest.raises(HumanVerificationError):
        run_audit(s)


def test_registrar_identity_cannot_sign_its_own_human_verdicts(tmp_path):
    s = material(tmp_path)
    registration = s["registration"]
    registration["plan"]["frozen_reviewer_ids"] = [
        "independent-bob", "registrar-ops",
    ]
    registration["signature_b64"] = base64.b64encode(
        s["registrar_secret"].sign(registration_signing_bytes(registration))
    ).decode("ascii")
    s["registration_hash"] = sha256_json(registration)
    with pytest.raises(HumanVerificationError, match="registrar"):
        run_audit(s)


def test_two_reviewer_names_cannot_share_one_ed25519_key(tmp_path):
    s = material(tmp_path)
    s["adjudicator_keys"]["independent-bob-key"]["public_key_b64"] = (
        s["adjudicator_keys"]["independent-ada-key"]["public_key_b64"])
    for rec in s["labels"]:
        if rec["reviewer_id"] == "independent-bob":
            rec["signature_b64"] = base64.b64encode(
                s["reviewer_secrets"]["independent-ada"].sign(
                    observation_signing_bytes(rec))).decode("ascii")
    with pytest.raises(HumanVerificationError, match="same human adjudicator public key"):
        run_audit(s)


def test_owner_only_preregistration_write_and_no_overwrite(tmp_path):
    s = material(tmp_path)
    folder = tmp_path / "private-study"
    folder.mkdir(mode=0o700)
    path = folder / "preregistration-plan.json"
    summary = write_study_plan(s["plan"], path)
    assert summary["study_id"] == STUDY
    assert summary["plan_sha256"] == sha256_json(s["plan"])
    assert summary["registration_signed"] is False
    assert not summary["chronology_independently_proven"]
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(RealIntakeError):
        write_study_plan(s["plan"], path)


def test_study_plan_and_signed_audit_cli_real_git_replay(tmp_path, capsys):
    s = material(tmp_path)
    opts = s["opts"]
    root = s["root"]
    folder = tmp_path / "study-files"
    folder.mkdir(mode=0o700)
    names = {
        "blind": folder / "blind.json",
        "ledger": folder / "ledger.json",
        "plan": folder / "plan.json",
        "registration": folder / "registration.json",
        "registrar": folder / "registrar-keys.json",
        "labels": folder / "labels.json",
        "reviewer": folder / "reviewer-keys.json",
        "evidence": folder / "evidence",
        "model": folder / "model-report.json",
    }
    names["evidence"].mkdir()
    for name, value in (
        ("blind", s["frame"]["blind_packet"]),
        ("ledger", s["frame"]["private_ledger"]),
        ("registration", s["registration"]),
        ("registrar", s["registrar_keys"]),
        ("labels", s["labels"]),
        ("reviewer", s["adjudicator_keys"]),
        ("model", opts["report"]),
    ):
        names[name].write_text(json.dumps(value))
    names["registrar"].chmod(0o600)
    names["reviewer"].chmod(0o600)
    for digest, raw in s["evidence"].items():
        (names["evidence"] / digest).write_bytes(raw)
    common = [
        "--root", str(root),
        "--attestation-repo", opts["repository"],
        "--attestation-repo-id", str(opts["repository_id"]),
        "--base", opts["base_commit"], "--head", opts["head_commit"],
        "--real-sample-seed", opts["seed"],
        "--real-sample-max-cases", str(opts["max_cases"]),
        "--real-model-report", str(names["model"]),
        "--real-blind-file", str(names["blind"]),
        "--real-private-file", str(names["ledger"]),
    ]
    cli.main([
        "study-plan", *common, "--study-id", STUDY,
        "--study-registered-at", REGISTERED_AT,
        "--study-reviewers", ",".join(REVIEWERS),
        "--study-plan-output", str(names["plan"]),
    ])
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "study_plan_created_not_chronologically_anchored"
    assert created["plan_sha256"] == sha256_json(s["plan"])
    cli.main([
        "study-audit", *common,
        "--study-registration-file", str(names["registration"]),
        "--study-registration-sha256", s["registration_hash"],
        "--study-registrar-keys-file", str(names["registrar"]),
        "--label-attestations-file", str(names["labels"]),
        "--label-trust-keys-file", str(names["reviewer"]),
        "--label-evidence-dir", str(names["evidence"]),
    ])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "preregistered_sample_observations_only"
    assert result["completion"]["pending"] == 0
    assert "Fixture-only signed" not in json.dumps(result)
