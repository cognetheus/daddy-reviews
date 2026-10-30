"""Side-by-side shadow/canary quality comparison on identical labeled PR cases.

Pure offline comparison: does not deploy a model, route traffic, or override
repository policies. Abstains on incomparable samples and missing metrics.
"""
from __future__ import annotations
from .quality import QualityError, score_quality


def compare_quality(baseline: dict, candidate: dict,
                    min_precision_delta: float = -0.03,
                    min_recall_delta: float = -0.03,
                    max_false_alarm_increase: float = 0.01) -> dict:
    for value in (min_precision_delta, min_recall_delta, max_false_alarm_increase):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1 <= value <= 1:
            raise QualityError("Calibration threshold outside [-1,1]")
    a = baseline.get("cases") if isinstance(baseline, dict) else None
    b = candidate.get("cases") if isinstance(candidate, dict) else None
    if not isinstance(a, list) or not isinstance(b, list):
        raise QualityError("Both datasets require labeled cases")
    left = {case.get("id"): case for case in a if isinstance(case, dict)}
    right = {case.get("id"): case for case in b if isinstance(case, dict)}
    if len(left) != len(a) or len(right) != len(b) or left.keys() != right.keys():
        raise QualityError("Baseline and candidate must contain exactly the same case IDs")
    for name in left:
        first, second = left[name], right[name]
        if (first.get("tier") != second.get("tier") or
                first.get("expected") != second.get("expected") or
                first.get("label_status") != second.get("label_status")):
            raise QualityError("Ground-truth labels or tiers differ between candidates: " + name)
    baseline_score, candidate_score = score_quality(baseline), score_quality(candidate)
    groups = sorted(set(baseline_score["metrics_by_tier"]) | set(candidate_score["metrics_by_tier"]))
    deltas = {}
    regressions = []
    insufficient = []
    for tier in groups:
        orig = baseline_score["metrics_by_tier"].get(tier)
        new = candidate_score["metrics_by_tier"].get(tier)
        if orig is None or new is None:
            insufficient.append(tier)
            continue
        row = {}
        for metric in ("precision", "recall", "f1", "severity_accuracy_on_matched",
                       "clean_case_false_positive_rate"):
            old, now = orig[metric], new[metric]
            row[metric] = None if old is None or now is None else round(now - old, 4)
        deltas[tier] = row
        for metric, bound, direction in (
            ("precision", min_precision_delta, "min"),
            ("recall", min_recall_delta, "min"),
            ("clean_case_false_positive_rate", max_false_alarm_increase, "max"),
        ):
            value = row[metric]
            if value is None:
                insufficient.append(f"{tier}.{metric}")
            elif (direction == "min" and value < bound or
                  direction == "max" and value > bound):
                regressions.append({"tier": tier, "metric": metric, "delta": value,
                                    "threshold": bound})
    small_sample = len(a) < 20
    return {
        "format": "daddy-reviews-shadow-comparison-v1",
        "case_count": len(a),
        "status": "regression_detected" if regressions else
                  "inconclusive" if insufficient or small_sample else "within_thresholds",
        "sample_note": "Fewer than 20 cases; treat results as exploratory" if small_sample else None,
        "baseline_metrics": baseline_score["metrics_by_tier"],
        "candidate_metrics": candidate_score["metrics_by_tier"],
        "metric_deltas": deltas, "regressions": regressions,
        "unavailable": sorted(set(insufficient)),
        "release_action": "none",
        "limitations": [
            "Offline comparison only; no live canary traffic or model deployment.",
            "Metrics compare exact path/line/rule labels, not semantic equivalence.",
            "Passing thresholds does not establish real production defect accuracy.",
        ],
    }
