"""R6 shadow/canary comparison is non-deploying and rejects misleading inputs."""
from copy import deepcopy
import pytest

from daddy_reviews.calibration import compare_quality
from daddy_reviews.quality import QualityError


def f(rule, line):
    return {"path": "code.py", "line": line, "rule": rule, "severity": "high"}


def labeled():
    return {"format": "daddy-reviews-quality-v1", "cases": [
        {"id": "real-bug-fixture", "tier": "full", "label_status": "human_verified",
         "expected": [f("BUG", 1)], "observed": [f("BUG", 1)]},
        {"id": "clean-case", "tier": "trivial", "label_status": "human_verified",
         "expected": [], "observed": []},
    ]}


def test_shadow_detects_precision_and_recall_regression_without_deployment():
    before = labeled()
    after = deepcopy(before)
    after["cases"][0]["observed"] = []
    after["cases"][1]["observed"] = [f("FALSE", 2)]
    comparison = compare_quality(before, after)
    assert comparison["status"] == "regression_detected"
    assert comparison["release_action"] == "none"
    assert {x["metric"] for x in comparison["regressions"]} >= {
        "recall", "clean_case_false_positive_rate",
    }


def test_shadow_same_small_sample_does_not_claim_production_certainty():
    source = labeled()
    score = compare_quality(source, deepcopy(source))
    assert score["status"] == "inconclusive"
    assert score["sample_note"].startswith("Fewer than 20")
    assert score["metric_deltas"]["all"]["recall"] == 0


def test_shadow_rejects_changed_labels_or_missing_cases():
    before, after = labeled(), labeled()
    after["cases"][0]["expected"] = []
    with pytest.raises(QualityError):
        compare_quality(before, after)
    after = labeled()
    after["cases"].pop()
    with pytest.raises(QualityError):
        compare_quality(before, after)
    with pytest.raises(QualityError):
        compare_quality(before, before, max_false_alarm_increase=3)
