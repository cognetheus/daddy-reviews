"""R8.04i.02: independently signed opportunity-frame labels, with scope-safe scoring.

This is deliberately *not* a repository-wide recall estimator. An R8.02
reviewer may report defects only on added diff lines. Unchanged context source
is independently examined as an opportunity study, never misreported as
false negatives of the diff-only reviewer.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

from .ground_truth_labels import _schema, _check_signature
from .human_attestation import HumanVerificationError, sha256_json
from .real_repository_frame import build_opportunity_frame, BLIND, LEDGER
from .real_repository_quality import read_label_evidence

FORMAT = "daddy-reviews-opportunity-frame-label-audit-v1"
MAX_LABELS = 640
MAX_EVIDENCE_BYTES = 65_536


def audit_opportunity_labels(root: Path, blind_packet: dict,
                             private_ledger: dict, labels: list,
                             trusted_keys: dict, evidence_blobs: dict, *,
                             repository: str, repository_id: int,
                             base_commit: str, head_commit: str, seed: str,
                             max_cases: int, report: dict | None = None,
                             min_reviewers: int = 2) -> dict:
    """Rebuild real Git frame and cryptographically verify separate adjudicators.

    No arbitrary metrics from label JSON are trusted. A signed label proves
    provenance, not factual correctness, blinding, or reviewer independence.
    """
    if (not isinstance(blind_packet, dict) or blind_packet.get("format") != BLIND
            or not isinstance(private_ledger, dict)
            or private_ledger.get("format") != LEDGER
            or not isinstance(labels, list) or not 1 <= len(labels) <= MAX_LABELS
            or not isinstance(trusted_keys, dict) or not 1 <= len(trusted_keys) <= 128
            or not isinstance(evidence_blobs, dict) or len(evidence_blobs) > MAX_LABELS
            or type(min_reviewers) is not int or not 2 <= min_reviewers <= 4):
        raise HumanVerificationError("Invalid opportunity-frame labels, trust keys or reviewer threshold")
    source = build_opportunity_frame(
        root, repository=repository, repository_id=repository_id,
        base_commit=base_commit, head_commit=head_commit,
        seed=seed, max_cases=max_cases, report=report)
    if (sha256_json(blind_packet) != sha256_json(source["blind_packet"])
            or sha256_json(private_ledger) != sha256_json(source["private_ledger"])):
        raise HumanVerificationError("Blind or private opportunity-frame document differs from immutable Git objects")
    cases = {c["case_id"]: c for c in source["blind_packet"]["cases"]}
    predictions = {c["case_id"]: c for c in source["private_ledger"]["cases"]}
    grouped = {case_id: [] for case_id in cases}
    seen = set()
    receipts = []
    for label in labels:
        _schema(label)
        item = cases.get(label["case_id"])
        if item is None:
            raise HumanVerificationError("Unknown case or source anchor in signed research label")
        if (label["candidate_id"] != label["case_id"]
                or label["snapshot_id"] != head_commit
                or label["patch_sha256"] != blind_packet["patch_sha256"]
                or label["tier"] != item["tier"]):
            raise HumanVerificationError("Signed label does not match exact Git source and frame")
        identity = label["case_id"], label["reviewer_id"]
        if identity in seen:
            raise HumanVerificationError("Duplicate source label by the same adjudicator")
        seen.add(identity)
        if len(grouped[label["case_id"]]) >= 4:
            raise HumanVerificationError("More than four independent labels per case")
        _check_signature(label, trusted_keys)
        contents = evidence_blobs.get(label["evidence_sha256"])
        if (not isinstance(contents, bytes)
                or not 1 <= len(contents) <= MAX_EVIDENCE_BYTES
                or hashlib.sha256(contents).hexdigest() != label["evidence_sha256"]):
            raise HumanVerificationError("Human adjudicator evidence bytes do not match signed SHA-256")
        grouped[label["case_id"]].append(label)
        receipts.append({
            "case_id": label["case_id"], "reviewer_id": label["reviewer_id"],
            "label_receipt_sha256": sha256_json(label),
            "evidence_sha256": label["evidence_sha256"],
        })
    if any(len(v) < min_reviewers for v in grouped.values()):
        raise HumanVerificationError("At least two distinct enrolled signers required for every source case")
    disagreements = sorted(k for k, v in grouped.items()
                           if len({item["label"] for item in v}) != 1)
    common = {
        "format": FORMAT, "case_count": len(cases),
        "source_frame_sha256": source["frame_sha256"],
        "source_population": source["blind_packet"]["population"],
        "signed_label_count": len(labels),
        "audit_receipts": sorted(receipts, key=lambda item:
                                 (item["case_id"], item["reviewer_id"])),
        "independent_label_authentication": "two_or_more_trusted_Ed25519_keys",
        "factual_defect_truth_proven": False,
        "actual_blinding_proven": False,
        "population_accuracy_claim": False,
        "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
    }
    if disagreements:
        return {
            **common, "status": "conflicting_labels_human_escalation",
            "conflicting_case_ids": disagreements, "counts": None,
            "observed_sample_metrics": None, "outcomes": [],
        }
    counts = Counter()
    outcomes = []
    has_model = report is not None
    for case_id in sorted(cases):
        item = cases[case_id]
        prediction = predictions[case_id]
        actual = grouped[case_id][0]["label"]
        public_stratum = item["stratum"]
        flagged = prediction["model_flagged"] if has_model else None
        if public_stratum == "added" and has_model:
            classification = ("added_flagged_" if flagged else "added_unflagged_") + actual
        elif public_stratum == "added":
            classification = "added_no_model_" + actual
        else:
            # Context defects cannot be false negatives of an added-line-only
            # reviewer; treating them as FN would manufacture poor recall.
            classification = public_stratum + "_" + actual
        counts[classification] += 1
        outcomes.append({
            "case_id": case_id, "source_stratum": public_stratum,
            "authenticated_human_label": actual,
            "model_flagged": flagged,
            "classification": classification,
            "within_diff_model_scope": prediction["within_diff_model_scope"],
        })
    if has_model:
        tp = counts["added_flagged_defect"]
        fp = counts["added_flagged_clean"]
        missed = counts["added_unflagged_defect"]
        observed = {
            "added_sample_unweighted_precision": (
                round(tp/(tp+fp), 6) if tp+fp else None),
            "added_sample_unweighted_recall": (
                round(tp/(tp+missed), 6) if tp+missed else None),
            "added_sample_unflagged_defect_count": missed,
            "unchanged_touched_defect_opportunities": counts["unchanged_touched_defect"],
            "unchanged_other_defect_opportunities": counts["unchanged_other_defect"],
            "eligible_scope": "added_lines_only",
            "biased_stratified_sample_no_population_inference": True,
        }
        status = "scope_separated_sample_observations_only"
    else:
        observed = None
        status = "source_labels_authenticated_model_predictions_absent"
    return {
        **common, "status": status, "counts": dict(sorted(counts.items())),
        "observed_sample_metrics": observed, "outcomes": outcomes,
        "limitations": [
            "Changed-line-only models cannot be penalized for legacy or context-only findings.",
            "Model strata were oversampled; displayed sample precision/recall are unweighted and biased.",
            "Line anchors are neither independent defect opportunities nor necessarily unique bugs.",
            "Human signatures prove key-controlled claims and intact evidence, not factual correctness.",
            "No CI fixture represents a genuine external blinded human study.",
        ],
    }
