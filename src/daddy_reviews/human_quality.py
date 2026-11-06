"""R8.04d.03: conservative offline evaluation of human resolution outcomes.

This scores supplied, independently labeled candidate cases. Labels and copied
resolution reports are not re-authenticated here; this evaluator never
promotes a reviewer or authorizes publication based on dataset claims.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from .human_attestation import sha256_json
from .operator_artifacts import read_operator_json

FORMAT = "daddy-reviews-human-resolution-eval-v1"
RESULT = "daddy-reviews-human-resolution-score-v1"
COMPARE = "daddy-reviews-human-resolution-comparison-v1"
LABELS = frozenset({"defect", "clean"})
TIERS = frozenset({"trivial", "lite", "full"})
RESOLVED = frozenset({"human_attested_confirmed", "human_attested_rejected"})
ABSTENTIONS = frozenset({
    "escalate_invalid_source_candidate",
    "escalate_incomplete_original_review",
    "escalate_incomplete_independent_challenge",
    "conflicting_human_attestations",
    "model_disagreement_unacknowledged",
    "insufficient_independent_human_evidence",
    "awaiting_human_verification",
})
SHA256 = frozenset("0123456789abcdef")
MAX_CASES = 200


class HumanQualityError(ValueError):
    """Invalid, contradictory or noncomparable labeled evaluation source."""


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= SHA256


def _validate_case(case, kind):
    if not isinstance(case, dict) or set(case) != {
        "id", "tier", "label", "label_metadata", "candidate_id", "snapshot_id",
        "patch_sha256", "resolution",
    }:
        raise HumanQualityError("Human evaluation case fields are invalid")
    if (not isinstance(case["id"], str) or not 1 <= len(case["id"]) <= 96
            or not isinstance(case["candidate_id"], str)
            or not 1 <= len(case["candidate_id"]) <= 128
            or not isinstance(case["snapshot_id"], str)
            or not 1 <= len(case["snapshot_id"]) <= 128
            or case["tier"] not in TIERS or case["label"] not in LABELS
            or not _sha(case["patch_sha256"])):
        raise HumanQualityError("Human evaluation case source identity is invalid")
    meta = case["label_metadata"]
    if (not isinstance(meta, dict) or set(meta) != {
            "reviewer_id", "reviewed_at", "protocol", "label_kind"}
            or not isinstance(meta["reviewer_id"], str)
            or not 1 <= len(meta["reviewer_id"]) <= 128
            or not isinstance(meta["reviewed_at"], str)
            or len(meta["reviewed_at"]) != 10
            or meta["reviewed_at"][4] != "-" or meta["reviewed_at"][7] != "-"
            or meta["protocol"] != "independent-human-label-v1"
            or meta["label_kind"] != kind):
        raise HumanQualityError("Missing or inconsistent independent label metadata")
    report = case["resolution"]
    if (not isinstance(report, dict)
            or report.get("format") != "daddy-reviews-human-resolution-v1"
            or report.get("snapshot_id") != case["snapshot_id"]
            or report.get("patch_sha256") != case["patch_sha256"]
            or not isinstance(report.get("decisions"), list)
            or len(report["decisions"]) > 48):
        raise HumanQualityError("Resolution report does not match labeled source")
    matches = [d for d in report["decisions"]
               if isinstance(d, dict) and d.get("candidate_id") == case["candidate_id"]]
    if len(matches) != 1:
        raise HumanQualityError("Exactly one resolution for each labeled candidate required")
    decision = matches[0]
    status = decision.get("status")
    if status not in RESOLVED | ABSTENTIONS:
        raise HumanQualityError("Unknown human resolution state")
    if status in RESOLVED:
        reviewers = decision.get("independent_human_reviewers")
        if (type(decision.get("verified_human_receipts")) is not int
                or decision["verified_human_receipts"] < 2
                or not isinstance(reviewers, list) or len(reviewers) < 2
                or any(not isinstance(x, str) or not x for x in reviewers)
                or len(reviewers) != len(set(reviewers))):
            raise HumanQualityError("Purportedly resolved decision lacks two distinct humans")
    return status, decision.get("challenge_verdict")


def validate_resolution_dataset(dataset):
    if (not isinstance(dataset, dict) or set(dataset) != {
            "format", "dataset_kind", "cases"}
            or dataset["format"] != FORMAT
            or dataset["dataset_kind"] not in {"synthetic", "human_labeled"}
            or not isinstance(dataset["cases"], list)
            or not 1 <= len(dataset["cases"]) <= MAX_CASES):
        raise HumanQualityError("Invalid bounded human-resolution dataset")
    seen = set()
    for case in dataset["cases"]:
        _validate_case(case, dataset["dataset_kind"])
        identity = case["id"], case["candidate_id"]
        if identity in seen:
            raise HumanQualityError("Duplicate case/candidate identity")
        seen.add(identity)
    return dataset


def read_resolution_dataset(path):
    return validate_resolution_dataset(read_operator_json(path))


def _ratio(num, den):
    return round(num / den, 6) if den else None


def evaluate_human_resolutions(dataset):
    validate_resolution_dataset(dataset)
    counts = Counter()
    tier_rows = {k: Counter() for k in ("trivial", "lite", "full")}
    outcomes = []
    for case in sorted(dataset["cases"], key=lambda c: (c["id"], c["candidate_id"])):
        status, challenge = _validate_case(case, dataset["dataset_kind"])
        tier = case["tier"]
        label = case["label"]
        key = ("tp" if label == "defect" and status == "human_attested_confirmed"
               else "fp" if label == "clean" and status == "human_attested_confirmed"
               else "fn" if label == "defect" and status == "human_attested_rejected"
               else "tn" if label == "clean" and status == "human_attested_rejected"
               else "abstained")
        for bucket in (counts, tier_rows[tier]):
            bucket["cases"] += 1
            bucket[key] += 1
            bucket["defects" if label == "defect" else "clean"] += 1
            if status == "conflicting_human_attestations":
                bucket["human_conflicts"] += 1
            if status == "model_disagreement_unacknowledged":
                bucket["model_conflicts"] += 1
            if status in RESOLVED:
                bucket["resolved"] += 1
            if status not in RESOLVED and label == "defect":
                bucket["unresolved_defects"] += 1
        outcomes.append({
            "id": case["id"], "candidate_id": case["candidate_id"],
            "tier": tier, "label": label, "resolution_status": status,
            "challenge_verdict": challenge, "classification": key,
        })

    def metrics(stats):
        tp, fp, fn = stats["tp"], stats["fp"], stats["fn"]
        return {
            **{key: stats[key] for key in (
                "cases", "defects", "clean", "tp", "fp", "fn", "tn",
                "abstained", "resolved", "unresolved_defects",
                "human_conflicts", "model_conflicts")},
            "precision": _ratio(tp, tp + fp),
            "resolved_recall": _ratio(tp, tp + fn),
            "coverage_adjusted_recall": _ratio(tp, stats["defects"]),
            "clean_false_alarm_rate": _ratio(fp, stats["clean"]),
            "confirmed_miss_rate": _ratio(fn, stats["defects"]),
            "resolution_coverage": _ratio(stats["resolved"], stats["cases"]),
        }

    labels_only = [{
        "id": c["id"], "candidate_id": c["candidate_id"],
        "tier": c["tier"], "label": c["label"],
        "label_metadata": c["label_metadata"],
        "snapshot_id": c["snapshot_id"], "patch_sha256": c["patch_sha256"],
    } for c in sorted(dataset["cases"], key=lambda c: (c["id"], c["candidate_id"]))]
    return {
        "format": RESULT, "status": "evaluation_only",
        "dataset_kind": dataset["dataset_kind"], "case_count": len(outcomes),
        "corpus_sha256": sha256_json(labels_only),
        "metrics": metrics(counts),
        "by_tier": {k: metrics(v) for k, v in tier_rows.items()},
        "outcomes": outcomes,
        "label_authentication": "self_declared_not_cryptographically_attested",
        "real_world_accuracy_claim": False,
        "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
    }


def compare_human_resolutions(baseline, candidate, *, min_cases=20):
    if type(min_cases) is not int or not 1 <= min_cases <= MAX_CASES:
        raise HumanQualityError("Invalid minimum evaluation corpus size")
    left = evaluate_human_resolutions(baseline)
    right = evaluate_human_resolutions(candidate)
    if (left["corpus_sha256"] != right["corpus_sha256"]
            or left["dataset_kind"] != right["dataset_kind"]
            or left["case_count"] != right["case_count"]):
        raise HumanQualityError("Compared human resolution sources do not share labels and source identities")
    a, b = left["metrics"], right["metrics"]
    def diff(key):
        old, new = a[key], b[key]
        return round(new - old, 6) if old is not None and new is not None else None
    changes = {
        name: diff(name) for name in (
            "precision", "coverage_adjusted_recall", "resolution_coverage",
            "clean_false_alarm_rate", "confirmed_miss_rate",
        )
    }
    regression = (
        changes["precision"] is not None and changes["precision"] < -0.02
        or changes["coverage_adjusted_recall"] is not None
        and changes["coverage_adjusted_recall"] < -0.02
        or changes["resolution_coverage"] is not None
        and changes["resolution_coverage"] < -0.02
        or changes["clean_false_alarm_rate"] is not None
        and changes["clean_false_alarm_rate"] > 0.02
        or changes["confirmed_miss_rate"] is not None
        and changes["confirmed_miss_rate"] > 0.02
        or b["unresolved_defects"] > a["unresolved_defects"]
    )
    return {
        "format": COMPARE,
        "status": "regression" if regression else "insufficient_evidence",
        "dataset_kind": left["dataset_kind"],
        "case_count": left["case_count"],
        "corpus_sha256": left["corpus_sha256"],
        "changes": changes,
        "new_unresolved_defects": max(0, b["unresolved_defects"] - a["unresolved_defects"]),
        "minimum_cases_for_review": min_cases,
        "promotion_eligible": False,
        "real_world_accuracy_claim": False,
        "reason": "Regression blocks; lack of regression is not evidence of production quality. "
                  "Labels and resolution JSON were not independently authenticated.",
    }
