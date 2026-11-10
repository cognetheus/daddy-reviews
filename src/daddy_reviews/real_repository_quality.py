"""R8.04h.02: replay real Git objects and audit independent blind labels.

The ledger is NEVER supplied to human adjudicators. The evaluator only accepts
precommitted sample identities rederived from pinned Git objects and separately
signed labels. A label signature cannot establish bug truth, and selection
based on changed lines is not a statistically representative defect survey.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path
import re

from .ground_truth_labels import _check_signature, _schema
from .human_attestation import HumanVerificationError, sha256_json
from .operator_artifacts import _safe_regular_read
from .real_repository_intake import build_real_repository_intake, BLIND, LEDGER

FORMAT = "daddy-reviews-real-repository-label-audit-v1"
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
MAX_LABELS = 640
MAX_EVIDENCE = 65_536


def read_label_evidence(folder: Path, labels: list) -> dict:
    """Read only digest-named evidence files through O_NOFOLLOW and bounded reads."""
    if not isinstance(labels, list) or len(labels) > MAX_LABELS:
        raise HumanVerificationError("Independent real-repository label count invalid")
    directory = Path(os.path.abspath(os.fspath(folder)))
    for entry in (directory, *directory.parents):
        if entry.is_symlink():
            raise HumanVerificationError("Symlinked real-repository evidence directory")
    if not directory.is_dir():
        raise HumanVerificationError("Independent evidence directory missing")
    digests = set()
    for label in labels:
        if not isinstance(label, dict):
            raise HumanVerificationError("Malformed real-repository label")
        digest = label.get("evidence_sha256")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise HumanVerificationError("Independent label evidence digest invalid")
        digests.add(digest)
    if len(digests) > MAX_LABELS:
        raise HumanVerificationError("Excessive distinct label evidence digests")
    result = {}
    for digest in sorted(digests):
        raw = _safe_regular_read(directory / digest, MAX_EVIDENCE)
        if not raw or hashlib.sha256(raw).hexdigest() != digest:
            raise HumanVerificationError("Independent label evidence was altered or unavailable")
        result[digest] = raw
    return result


def audit_real_repository_labels(root: Path, blind_packet: dict, private_ledger: dict,
                                 labels: list, trusted_keys: dict,
                                 evidence_blobs: dict, *, repository: str,
                                 repository_id: int, base_commit: str,
                                 head_commit: str, seed: str, max_cases: int,
                                 report: dict | None = None,
                                 min_reviewers: int = 2) -> dict:
    """Validate every source anchor and two+ human signatures *before* scoring.

    Model report must be the original completed harness report if supplied.
    Missing predictions do not get converted into reported clean decisions;
    they are merely independently reviewed source locations.
    """
    if (not isinstance(blind_packet, dict) or blind_packet.get("format") != BLIND
            or not isinstance(private_ledger, dict)
            or private_ledger.get("format") != LEDGER
            or not isinstance(labels, list) or not 1 <= len(labels) <= MAX_LABELS
            or not isinstance(trusted_keys, dict) or not 1 <= len(trusted_keys) <= 128
            or not isinstance(evidence_blobs, dict) or len(evidence_blobs) > MAX_LABELS
            or type(min_reviewers) is not int or not 2 <= min_reviewers <= 4):
        raise HumanVerificationError("Invalid blind human-label evidence inputs")
    original = build_real_repository_intake(
        root, repository=repository, repository_id=repository_id,
        base_commit=base_commit, head_commit=head_commit, seed=seed,
        max_cases=max_cases, report=report)
    # Prevent both colluding JSON files from redefining the population or
    # source model predictions. Require byte-equivalent canonical objects.
    if (sha256_json(blind_packet) != sha256_json(original["blind_packet"])
            or sha256_json(private_ledger) != sha256_json(original["private_ledger"])):
        raise HumanVerificationError("Blind packet or sealed prediction ledger disagrees with Git objects")
    cases = {c["case_id"]: c for c in original["blind_packet"]["cases"]}
    predictions = {c["case_id"]: c for c in original["private_ledger"]["cases"]}
    grouped = {key: [] for key in cases}
    seen = set()
    receipts = []
    for rec in labels:
        _schema(rec)
        case = cases.get(rec["case_id"])
        if case is None:
            raise HumanVerificationError("Label refers to unknown real-repository source anchor")
        if (rec["candidate_id"] != rec["case_id"]
                or rec["snapshot_id"] != head_commit
                or rec["patch_sha256"] != blind_packet["patch_sha256"]
                or rec["tier"] != case["tier"]):
            raise HumanVerificationError("Signed label does not match its Git source anchor")
        identity = rec["case_id"], rec["reviewer_id"]
        if identity in seen:
            raise HumanVerificationError("Duplicate human label or signer on source anchor")
        seen.add(identity)
        if len(grouped[rec["case_id"]]) >= 4:
            raise HumanVerificationError("Excessive labels for one source anchor")
        _check_signature(rec, trusted_keys)
        digest = rec["evidence_sha256"]
        contents = evidence_blobs.get(digest)
        if (not isinstance(contents, bytes)
                or not 1 <= len(contents) <= MAX_EVIDENCE
                or hashlib.sha256(contents).hexdigest() != digest):
            raise HumanVerificationError("Human-signed reproduction evidence missing or modified")
        grouped[rec["case_id"]].append(rec)
        receipts.append({
            "case_id": rec["case_id"], "reviewer_id": rec["reviewer_id"],
            "label_receipt_sha256": sha256_json(rec),
            "evidence_sha256": digest,
        })
    if any(len(group) < min_reviewers for group in grouped.values()):
        raise HumanVerificationError("Every source case requires enough independent registered humans")
    disagreements = sorted(case for case, records in grouped.items()
                           if len({r["label"] for r in records}) != 1)
    if disagreements:
        return {
            "format": FORMAT, "status": "conflicting_human_labels_escalate",
            "case_count": len(cases), "conflicting_case_ids": disagreements,
            "audit_receipts": sorted(receipts, key=lambda r: (
                r["case_id"], r["reviewer_id"])),
            "counts": None, "observed_sample_metrics": None,
            "model_quality_approved": False, "population_accuracy_claim": False,
            "promotion_eligible": False, "github_publication": "none",
            "merge_action": "none",
        }
    scoreable = report is not None
    stats = Counter()
    outcomes = []
    for case_id in sorted(cases):
        label = grouped[case_id][0]["label"]
        prediction = predictions[case_id]["model_flagged"]
        item = ("true_positive" if prediction and label == "defect"
                else "false_positive" if prediction
                else "sampled_unflagged_defect" if label == "defect"
                else "sampled_unflagged_clean")
        stats[item] += 1
        outcomes.append({"case_id": case_id, "human_label": label,
                         "model_flagged": prediction if scoreable else None,
                         "sample_classification": item if scoreable else "not_scored_no_model"})
    total = len(cases)
    positives = stats["true_positive"] + stats["false_positive"]
    defects = stats["true_positive"] + stats["sampled_unflagged_defect"]
    observed_metrics = ({
        "sampled_case_count": total,
        "precision_among_sampled_flagged": (
            round(stats["true_positive"]/positives, 6) if positives else None),
        "recall_among_sampled_changed_line_anchors": (
            round(stats["true_positive"]/defects, 6) if defects else None),
        "unflagged_defect_yield_in_sample": (
            round(stats["sampled_unflagged_defect"]/
                  (stats["sampled_unflagged_defect"]+stats["sampled_unflagged_clean"]), 6)
            if stats["sampled_unflagged_defect"]+stats["sampled_unflagged_clean"] else None),
    } if scoreable else None)
    return {
        "format": FORMAT,
        "status": "sample_audited_not_population_accuracy" if scoreable
                  else "labels_authenticated_model_predictions_missing",
        "case_count": total,
        "population": original["private_ledger"]["population"],
        "sample_manifest_sha256": original["manifest_sha256"],
        "signed_label_count": len(labels),
        "counts": dict(sorted(stats.items())) if scoreable else None,
        "observed_sample_metrics": observed_metrics,
        "outcomes": outcomes,
        "audit_receipts": sorted(receipts, key=lambda r: (
            r["case_id"], r["reviewer_id"])),
        "ground_truth_claim": "human_signature_authentication_not_defect_truth",
        "blinding_cryptographically_proven": False,
        "population_accuracy_claim": False,
        "model_quality_approved": False, "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
        "limitations": [
            "Real Git objects establish sample provenance, not correctness of human defect labels.",
            "Deterministic seed and stratification do not by themselves provide unbiased PR-wide recall.",
            "Added-line anchors can miss pre-existing flaws and uncited defect regions.",
            "Reproducibility and independent signed labels are required before internal sample scoring.",
            "An independent model report must be present to score model predictions.",
        ],
    }
