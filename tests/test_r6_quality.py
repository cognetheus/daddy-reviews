"""R6: independently labeled review fixtures and evidence-based runtime metrics."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest

from daddy_reviews.quality import (
    QualityError, read_quality_dataset, score_quality, summarize_runtime,
)


def finding(rule, line=1, severity="high"):
    return {"path": "src/app.py", "line": line, "rule": rule, "severity": severity}


def dataset():
    return {"format": "daddy-reviews-quality-v1", "cases": [
        {
            "id": "hit-and-false-alarm", "tier": "full",
            "label_status": "human_verified",
            "expected": [finding("BUG_001", severity="high"), finding("BUG_002", 2)],
            "observed": [finding("BUG_001", severity="medium"), finding("FALSE", 3)],
        },
        {
            "id": "clean-change", "tier": "trivial",
            "label_status": "human_verified", "expected": [], "observed": [],
        },
        {
            "id": "clean-false-alarm", "tier": "lite",
            "label_status": "human_verified", "expected": [], "observed": [finding("FALSE", 10)],
        },
    ]}


def test_quality_confusion_matrix_by_tier():
    result = score_quality(dataset())
    overall = result["metrics_by_tier"]["all"]
    assert (overall["tp"], overall["fp"], overall["fn"]) == (1, 2, 1)
    assert overall["precision"] == 0.3333
    assert overall["recall"] == 0.5
    assert overall["f1"] == 0.4
    assert overall["severity_accuracy_on_matched"] == 0
    assert overall["clean_case_false_positive_rate"] == 0.5
    assert result["metrics_by_tier"]["trivial"]["clean_case_false_positive_rate"] == 0.0
    assert result["metrics_by_tier"]["lite"]["clean_case_false_positive_rate"] == 1.0


def test_unlabeled_and_duplicate_ground_truth_rejected():
    d = dataset()
    d["cases"][0]["label_status"] = "model_labeled"
    with pytest.raises(QualityError, match="human_verified"):
        score_quality(d)
    d = dataset()
    d["cases"][0]["expected"].append(finding("BUG_001"))
    with pytest.raises(QualityError, match="Duplicate human ground"):
        score_quality(d)


def test_file_reader_bounds_and_json_invalidity():
    with TemporaryDirectory() as temp:
        path = Path(temp) / "quality.json"
        path.write_text(json.dumps(dataset()))
        assert read_quality_dataset(path)["format"] == "daddy-reviews-quality-v1"
        path.write_text("{oops")
        with pytest.raises(QualityError):
            read_quality_dataset(path)
        path.unlink()
        path.symlink_to(Path(temp) / "anything")
        with pytest.raises(QualityError):
            read_quality_dataset(path)


def test_actual_token_telemetry_with_explicit_pricing():
    runs = [{
        "reviewer_runs": [
            {"reviewer": "security", "status": "completed", "latency_ms": 100,
             "usage": {"input_tokens": 10_000, "output_tokens": 2_000}},
            {"reviewer": "performance", "status": "completed", "latency_ms": 500,
             "usage": {"input_tokens": 5_000, "output_tokens": 1_000}},
            {"reviewer": "standards", "status": "failed", "latency_ms": 1000,
             "usage": {"input_tokens": 1_000, "output_tokens": 100}},
        ]
    }]
    data = summarize_runtime(runs, input_usd_per_million=1,
                             output_usd_per_million=2)
    assert data["reviewer_runs"] == 3
    assert data["complete_runs"] == 2
    assert data["failed_runs"] == 1
    assert data["p50_latency_ms"] == 500
    assert data["p95_latency_ms"] == 1000
    assert data["reported_input_tokens"] == 16000
    assert data["reported_output_tokens"] == 3100
    assert data["estimated_cost_usd"] == 0.0222
    assert data["runs_missing_usage"] == 0


def test_missing_usage_is_unknown_not_free():
    runs = [{"reviewer_runs": [
        {"reviewer": "code-quality", "status": "completed",
         "latency_ms": 110, "usage": None},
    ]}]
    data = summarize_runtime(runs, input_usd_per_million=0,
                             output_usd_per_million=0)
    assert data["runs_missing_usage"] == 1
    assert data["estimated_cost_usd"] is None
    assert data["p95_latency_ms"] == 110


def test_invalid_latency_or_usage_or_rate_rejected():
    with pytest.raises(QualityError):
        summarize_runtime([{"reviewer_runs": [
            {"status": "completed", "latency_ms": -1}
        ]}])
    with pytest.raises(QualityError):
        summarize_runtime([], input_usd_per_million=-1)
    with pytest.raises(QualityError):
        summarize_runtime([{"reviewer_runs": [
            {"status": "failed", "latency_ms": 1,
             "usage": {"input_tokens": 3, "output_tokens": -2}}
        ]}])


def test_nonfinite_latency_is_not_valid_telemetry():
    with pytest.raises(QualityError):
        summarize_runtime([{"reviewer_runs": [
            {"status": "completed", "latency_ms": float("nan"), "usage": None}
        ]}])
