"""R8.04j: preregistered, source-pinned, separately signed evaluation studies.

Seals a case frame and *exactly two* adjudicator identities BEFORE label audit.
A host-supplied study SHA-256 and enrolled Ed25519 registrar signature freeze
study content; these are NOT independent proof of registration chronology.
Adjudicator decisions support defect/clean/uncertain, but do not establish
ground-truth correctness or actual human blinding.
"""
from __future__ import annotations

import base64
import binascii
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from .ground_truth_labels import PERSON
from .human_attestation import HumanVerificationError, sha256_json
from .real_repository_frame import FORMAT as FRAME_FORMAT, build_opportunity_frame
from .real_repository_intake import RealIntakeError, _output_path
from .real_repository_quality import read_label_evidence

PLAN_FORMAT = "daddy-reviews-preregistered-opportunity-study-v1"
REGISTRATION_FORMAT = "daddy-reviews-signed-study-registration-v1"
RECORD_FORMAT = "daddy-reviews-study-adjudicator-record-v1"
AUDIT_FORMAT = "daddy-reviews-preregistered-study-audit-v1"
REGISTRATION_DOMAIN = b"daddy-reviews-study-registration-v1\n"
LABEL_DOMAIN = b"daddy-reviews-study-adjudicator-record-v1\n"
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
STUDY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,63}\Z")
LABELS = ("defect", "clean", "uncertain")
MAX_RECORDS = 320
MAX_EVIDENCE = 65_536
REGISTRATION_FIELDS = {"format", "plan", "registrar_id", "key_id", "signature_b64"}
LABEL_FIELDS = {
    "format", "study_plan_sha256", "case_id", "source_sha256",
    "line_sha256", "head_commit", "reviewer_id", "key_id",
    "decision", "blind_protocol", "signed_at", "evidence_sha256",
    "rationale", "signature_b64",
}


def _utc(value: str) -> datetime:
    if (not isinstance(value, str) or not 20 <= len(value) <= 32
            or not value.endswith("Z")):
        raise HumanVerificationError("Exact UTC timestamp required")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise HumanVerificationError("Invalid UTC timestamp") from exc
    if result.utcoffset().total_seconds() != 0:
        raise HumanVerificationError("UTC offset must be zero")
    return result


def _canonical(value: dict, excluded: tuple = ()) -> bytes:
    if not isinstance(value, dict):
        raise HumanVerificationError("Signed object must be a map")
    try:
        raw = json.dumps(
            {k: v for k, v in value.items() if k not in excluded},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise HumanVerificationError("Invalid or noncanonical signing payload") from exc
    if len(raw) > 128_000:
        raise HumanVerificationError("Oversized signed study payload")
    return raw


def _reviewer_pair(reviewer_ids) -> list:
    if (not isinstance(reviewer_ids, (tuple, list))
            or len(reviewer_ids) != 2
            or any(not isinstance(item, str) or not PERSON.fullmatch(item)
                   for item in reviewer_ids)
            or len(set(reviewer_ids)) != 2):
        raise HumanVerificationError("Study requires exactly two distinct pre-enrolled reviewers")
    return sorted(reviewer_ids)


def create_study_plan(frame: dict, *, study_id: str, reviewer_ids: list,
                      registered_at: str) -> dict:
    """Create a blinded, model-free frozen roster from an already built frame.

    Calling this function alone does NOT prove the source frame was generated
    from true Git objects; the audited path replays the whole source frame.
    """
    if (not isinstance(frame, dict) or frame.get("format") != FRAME_FORMAT
            or frame.get("status") != "real_source_opportunity_frame_not_labels"
            or not isinstance(study_id, str) or not STUDY_ID.fullmatch(study_id)):
        raise HumanVerificationError("Study ID or opportunity frame invalid")
    frozen_at = _utc(registered_at)
    reviewers = _reviewer_pair(reviewer_ids)
    blind, ledger = frame.get("blind_packet"), frame.get("private_ledger")
    if (not isinstance(blind, dict) or not isinstance(ledger, dict)
            or blind.get("model_predictions_included") is not False
            or ledger.get("blind_packet_sha256") != sha256_json(blind)
            or not isinstance(blind.get("cases"), list)
            or not 1 <= len(blind["cases"]) <= 160):
        raise HumanVerificationError("Blind and private source frame linkage invalid")
    cases = []
    seen = set()
    for case in blind["cases"]:
        if (not isinstance(case, dict)
                or not isinstance(case.get("case_id"), str)
                or case["case_id"] in seen
                or case.get("label") is not None
                or case.get("stratum") not in (
                    "added", "unchanged_touched", "unchanged_other")
                or not isinstance(case.get("source_sha256"), str)
                or not SHA256.fullmatch(case["source_sha256"])
                or not isinstance(case.get("line_sha256"), str)
                or not SHA256.fullmatch(case["line_sha256"])):
            raise HumanVerificationError("Invalid or pre-labeled blind source opportunity")
        seen.add(case["case_id"])
        cases.append({
            "case_id": case["case_id"], "source_stratum": case["stratum"],
            "source_sha256": case["source_sha256"],
            "line_sha256": case["line_sha256"],
        })
    if (not isinstance(blind.get("head_commit"), str)
            or not SHA1.fullmatch(blind["head_commit"])):
        raise HumanVerificationError("Study requires pinned Git HEAD")
    _ = frozen_at
    return {
        "format": PLAN_FORMAT, "study_id": study_id,
        "registered_at": registered_at,
        "repository": blind["repository"],
        "repository_id": blind["repository_id"],
        "base_commit": blind["base_commit"],
        "head_commit": blind["head_commit"],
        "frame_sha256": frame["frame_sha256"],
        "blind_packet_sha256": sha256_json(blind),
        "sealed_ledger_sha256": sha256_json(ledger),
        "model_report_sha256": ledger.get("model_report_sha256"),
        "sampling_design": frame["sampling_design"],
        "sampling_unit": "nonblank_source_line_anchor_not_unique_defect",
        "frozen_reviewer_ids": reviewers,
        "labels_per_case": 2,
        "allowed_decisions": list(LABELS),
        "uncertainty_policy": "uncertain_or_disagreement_excluded_and_escalated",
        "score_scope": "descriptive_sample_added_lines_only",
        "case_count": len(cases),
        "cases": sorted(cases, key=lambda item: item["case_id"]),
        "model_predictions_included": False,
        "chronology_independently_proven": False,
        "population_accuracy_claim": False, "promotion_eligible": False,
        "merge_action": "none", "github_publication": "none",
    }


def registration_signing_bytes(record: dict) -> bytes:
    if not isinstance(record, dict) or set(record) != REGISTRATION_FIELDS:
        raise HumanVerificationError("Invalid signed study-registration envelope")
    return REGISTRATION_DOMAIN + _canonical(record, ("signature_b64",))


def observation_signing_bytes(record: dict) -> bytes:
    if not isinstance(record, dict) or set(record) != LABEL_FIELDS:
        raise HumanVerificationError("Invalid signed study observation fields")
    return LABEL_DOMAIN + _canonical(record, ("signature_b64",))


def _verify_key(record, registry: dict, *, role: str, identity_field: str,
                payload: bytes) -> bytes:
    if (not isinstance(registry, dict) or not 1 <= len(registry) <= 128
            or not isinstance(record.get("key_id"), str)):
        raise HumanVerificationError("Invalid independent trust registry")
    trust = registry.get(record["key_id"])
    if (not isinstance(trust, dict)
            or set(trust) != {"reviewer_id", "role", "enabled", "public_key_b64"}
            or trust["role"] != role or trust["enabled"] is not True
            or trust["reviewer_id"] != record[identity_field]):
        raise HumanVerificationError("Signer not independently enrolled for required role")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise HumanVerificationError("Ed25519 verification dependency is required") from exc
    try:
        pub = base64.b64decode(trust["public_key_b64"], validate=True)
        sig = base64.b64decode(record["signature_b64"], validate=True)
        if len(pub) != 32 or len(sig) != 64:
            raise ValueError("Invalid signature byte lengths")
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, payload)
    except (ValueError, binascii.Error, TypeError, InvalidSignature) as exc:
        raise HumanVerificationError("Independent study signature does not verify") from exc
    return pub


def audit_preregistered_study(root: Path, *, registration: dict,
                              expected_registration_sha256: str,
                              blind_packet: dict, private_ledger: dict,
                              labels: list, registrar_keys: dict,
                              adjudicator_keys: dict, evidence_blobs: dict,
                              repository: str, repository_id: int,
                              base_commit: str, head_commit: str, seed: str,
                              max_cases: int, report: dict | None = None) -> dict:
    """Check pinned signed plan, rederive source, then audit two human decisions.

    A caller must separately anchor expected_registration_sha256 outside of
    the dataset (Git committed file, independent timestamp service, etc.).
    This API verifies content binding, NOT that such anchoring predates labels.
    """
    if (not isinstance(registration, dict)
            or set(registration) != REGISTRATION_FIELDS
            or registration["format"] != REGISTRATION_FORMAT
            or not isinstance(expected_registration_sha256, str)
            or not SHA256.fullmatch(expected_registration_sha256)
            or sha256_json(registration) != expected_registration_sha256
            or not isinstance(registration.get("plan"), dict)
            or not isinstance(labels, list) or len(labels) > MAX_RECORDS
            or not isinstance(evidence_blobs, dict) or len(evidence_blobs) > MAX_RECORDS):
        raise HumanVerificationError("Signed preregistration does not match independently pinned SHA-256")
    plan = registration["plan"]
    if (not isinstance(registration["registrar_id"], str)
            or not PERSON.fullmatch(registration["registrar_id"])):
        raise HumanVerificationError("Invalid named study registrar")
    registrar_pub = _verify_key(
        registration, registrar_keys, role="study_registrar",
        identity_field="registrar_id",
        payload=registration_signing_bytes(registration))
    try:
        actual_frame = build_opportunity_frame(
            root, repository=repository, repository_id=repository_id,
            base_commit=base_commit, head_commit=head_commit,
            seed=seed, max_cases=max_cases, report=report)
    except (RealIntakeError, OSError, ValueError) as exc:
        raise HumanVerificationError("Preregistered source frame cannot be independently rebuilt") from exc
    if (sha256_json(blind_packet) != sha256_json(actual_frame["blind_packet"])
            or sha256_json(private_ledger) != sha256_json(actual_frame["private_ledger"])):
        raise HumanVerificationError("Frozen blind/private source inputs disagree with real Git objects")
    if not isinstance(plan.get("study_id"), str) or not isinstance(
            plan.get("frozen_reviewer_ids"), list):
        raise HumanVerificationError("Study registration omits planned enrollment")
    expected_plan = create_study_plan(
        actual_frame, study_id=plan["study_id"],
        reviewer_ids=plan["frozen_reviewer_ids"],
        registered_at=plan.get("registered_at"))
    if sha256_json(plan) != sha256_json(expected_plan):
        raise HumanVerificationError("Study plan changed after source or reviewer freeze")
    registered = _utc(plan["registered_at"])
    if not isinstance(adjudicator_keys, dict) or len(adjudicator_keys) > 128:
        raise HumanVerificationError("No controlled adjudicator registry")
    case_map = {item["case_id"]: item for item in expected_plan["cases"]}
    required = tuple(plan["frozen_reviewer_ids"])
    for reviewer in required:
        if not any(isinstance(t, dict) and t.get("reviewer_id") == reviewer
                   and t.get("role") == "ground_truth_adjudicator"
                   and t.get("enabled") is True for t in adjudicator_keys.values()):
            raise HumanVerificationError("A frozen study reviewer is no longer enrolled")
    seen, reviewer_pubs = set(), {}
    decisions = {cid: {} for cid in case_map}
    receipts = []
    for record in labels:
        observation_signing_bytes(record)
        if (record["format"] != RECORD_FORMAT
                or record.get("study_plan_sha256") != sha256_json(plan)
                or record.get("case_id") not in case_map
                or record.get("head_commit") != head_commit
                or record.get("reviewer_id") not in required
                or record.get("decision") not in LABELS
                or record.get("blind_protocol") != "separate_from_model_and_resolution_v1"
                or record.get("source_sha256") != case_map[record["case_id"]]["source_sha256"]
                or record.get("line_sha256") != case_map[record["case_id"]]["line_sha256"]
                or not isinstance(record.get("evidence_sha256"), str)
                or not SHA256.fullmatch(record["evidence_sha256"])
                or not isinstance(record.get("rationale"), str)
                or not 20 <= len(record["rationale"].strip()) <= 1600
                or not isinstance(record.get("reviewer_id"), str)):
            raise HumanVerificationError("Signed observation differs from frozen study source or rubric")
        if _utc(record.get("signed_at")) <= registered:
            raise HumanVerificationError("Signed observation claims to predate study registration")
        identity = record["case_id"], record["reviewer_id"]
        if identity in seen:
            raise HumanVerificationError("Duplicate human decision for one preregistered case")
        seen.add(identity)
        pub = _verify_key(
            record, adjudicator_keys, role="ground_truth_adjudicator",
            identity_field="reviewer_id", payload=observation_signing_bytes(record))
        if pub == registrar_pub:
            raise HumanVerificationError("Registrar key cannot double as a study adjudicator key")
        if record["reviewer_id"] in reviewer_pubs and reviewer_pubs[record["reviewer_id"]] != pub:
            raise HumanVerificationError("Adjudicator switched enrolled signing key during study")
        reviewer_pubs[record["reviewer_id"]] = pub
        raw = evidence_blobs.get(record["evidence_sha256"])
        if (not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_EVIDENCE
                or hashlib.sha256(raw).hexdigest() != record["evidence_sha256"]):
            raise HumanVerificationError("Observation evidence absent, oversized or tampered")
        decisions[record["case_id"]][record["reviewer_id"]] = record["decision"]
        receipts.append({
            "case_id": record["case_id"], "reviewer_id": record["reviewer_id"],
            "observation_sha256": sha256_json(record),
            "evidence_sha256": record["evidence_sha256"],
        })
    if (len(reviewer_pubs) == 2 and reviewer_pubs[required[0]] == reviewer_pubs[required[1]]):
        raise HumanVerificationError("Two identities cannot share the same human adjudicator public key")
    counts = Counter()
    confusion = {a: {b: 0 for b in LABELS} for a in LABELS}
    outstanding = []
    outcomes = []
    for case_id in sorted(case_map):
        observations = decisions[case_id]
        if len(observations) != 2:
            counts["pending"] += 1
            outstanding.append(case_id)
            continue
        a, b = observations[required[0]], observations[required[1]]
        confusion[a][b] += 1
        counts["both_submitted"] += 1
        if a != b:
            counts["disagreements"] += 1
            outstanding.append(case_id)
            continue
        counts["agreements"] += 1
        if a == "uncertain":
            counts["mutual_uncertainty"] += 1
            outstanding.append(case_id)
            continue
        counts["consensus_" + a] += 1
        outcomes.append({"case_id": case_id, "source_stratum": case_map[case_id]["source_stratum"],
                         "consensus_label": a})
    complete = counts["both_submitted"]
    agreement = counts["agreements"] / complete if complete else None
    marginal = (
        sum((sum(confusion[category].values())/complete) *
            (sum(confusion[row][category] for row in LABELS)/complete)
            for category in LABELS)
        if complete else None)
    kappa = ((agreement-marginal)/(1-marginal)
             if complete and marginal is not None and 1-marginal > 1e-12
             else None)
    all_resolved = complete == len(case_map) and not outstanding
    if not all_resolved:
        status = "pending_or_disputed_human_adjudication"
    elif report is None:
        status = "preregistered_labels_authenticated_no_model_report"
    else:
        status = "preregistered_sample_observations_only"
    observed = None
    if all_resolved and report is not None:
        indexed = {c["case_id"]: c for c in private_ledger["cases"]}
        tally = Counter()
        for item in outcomes:
            scope = item["source_stratum"]
            pred = indexed[item["case_id"]]["model_flagged"]
            label = item["consensus_label"]
            if scope == "added":
                tally[("added_flagged_" if pred else "added_unflagged_") + label] += 1
            else:
                tally[scope + "_" + label] += 1
        tp, fp, fn = (
            tally["added_flagged_defect"], tally["added_flagged_clean"],
            tally["added_unflagged_defect"])
        observed = {
            "counts": dict(sorted(tally.items())),
            "unweighted_added_sample_precision": round(tp/(tp+fp), 6) if tp+fp else None,
            "unweighted_added_sample_recall": round(tp/(tp+fn), 6) if tp+fn else None,
            "context_defects_not_model_false_negatives": (
                tally["unchanged_touched_defect"] + tally["unchanged_other_defect"]),
            "biased_stratified_line_sample": True,
        }
    return {
        "format": AUDIT_FORMAT,
        "status": status, "study_id": plan["study_id"],
        "registration_sha256": expected_registration_sha256,
        "plan_sha256": sha256_json(plan),
        "frozen_reviewer_ids": list(required), "expected_cases": len(case_map),
        "signed_observations": len(labels),
        "completion": {
            "both_signed": complete, "pending": counts["pending"],
            "disagreements": counts["disagreements"],
            "mutual_uncertainty": counts["mutual_uncertainty"],
            "consensus_defect": counts["consensus_defect"],
            "consensus_clean": counts["consensus_clean"],
            "unresolved_case_ids": sorted(outstanding),
        },
        "inter_rater_agreement": {
            "paired_cases": complete,
            "raw_agreement": round(agreement, 6) if agreement is not None else None,
            "cohen_kappa_three_label": round(kappa, 6) if kappa is not None else None,
            "kappa_undefined_when_marginals_degenerate": kappa is None,
            "decision_order": list(LABELS),
            "confusion": confusion,
        },
        "sample_observations": observed,
        "audit_receipts": sorted(receipts, key=lambda x: (x["case_id"], x["reviewer_id"])),
        "preregistration_chronology_independently_proven": False,
        "genuine_human_independence_proven": False,
        "factual_defect_truth_proven": False, "population_accuracy_claim": False,
        "model_quality_approved": False, "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
    }


def write_study_plan(plan: dict, path: Path) -> dict:
    """Owner-only, no-overwrite study plan. Operator externally signs and anchors."""
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise HumanVerificationError("Invalid unsigned study plan")
    destination = _output_path(path)
    payload = _canonical(plan) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise HumanVerificationError("Cannot exclusively write frozen study plan") from exc
    return {
        "status": "study_plan_created_not_chronologically_anchored",
        "study_id": plan["study_id"],
        "plan_sha256": sha256_json(plan),
        "case_count": plan["case_count"],
        "registration_signed": False,
        "chronology_independently_proven": False,
        "model_quality_approved": False, "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
    }
