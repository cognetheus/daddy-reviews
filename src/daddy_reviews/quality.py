"""Calibrated reviewer evaluation against explicitly labeled cases.

This does not invent real-world benchmark scores. Fixtures must be labeled by
human reviewers before numbers are interpreted as actual defect detection.
"""
from __future__ import annotations
from collections import defaultdict
import json
import math
from pathlib import Path

MAX_BYTES = 4_000_000
MAX_CASES = 500
LEVELS = {"critical", "high", "medium", "low", "suggestion"}
FORMAT = "daddy-reviews-quality-v1"


class QualityError(ValueError):
    pass


def _finding(value):
    return (isinstance(value, dict) and isinstance(value.get("path"), str) and
            0 < len(value["path"]) <= 400 and type(value.get("line")) is int and
            value["line"] > 0 and isinstance(value.get("rule"), str) and
            0 < len(value["rule"]) <= 120 and value.get("severity") in LEVELS)


def read_quality_dataset(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise QualityError("Quality dataset missing, symlinked or too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise QualityError("Invalid quality dataset") from exc
    validate_quality_dataset(data)
    return data


def validate_quality_dataset(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise QualityError("Expected quality-v1 dataset")
    cases = data.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise QualityError("Dataset must have 1..500 labeled cases")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise QualityError("Case must be an object")
        name = case.get("id")
        if not isinstance(name, str) or not name or name in ids:
            raise QualityError("Duplicate or missing case id")
        ids.add(name)
        if case.get("tier") not in ("trivial", "lite", "full"):
            raise QualityError("Case needs review tier")
        if case.get("label_status") != "human_verified":
            raise QualityError("Quality cases require human_verified labels")
        expected, observed = case.get("expected"), case.get("observed")
        if not isinstance(expected, list) or not isinstance(observed, list):
            raise QualityError("Case needs expected and observed arrays")
        if len(expected) > 100 or len(observed) > 100:
            raise QualityError("Too many findings per case")
        if any(not _finding(x) for x in expected + observed):
            raise QualityError("Invalid finding schema")
        if len({_key(x) for x in expected}) != len(expected):
            raise QualityError("Duplicate human ground truth label")


def _key(f):
    return f["path"], f["line"], f["rule"]


def _pct(a, b):
    return round(a / b, 4) if b else None


def score_quality(data: dict) -> dict:
    validate_quality_dataset(data)
    totals = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "clean": 0,
                                  "clean_flagged": 0, "severity_correct": 0})
    cases = []
    for case in data["cases"]:
        truth = {_key(f): f for f in case["expected"]}
        predicted = {_key(f): f for f in case["observed"]}
        overlap = truth.keys() & predicted.keys()
        tp, fp, fn = len(overlap), len(predicted.keys() - truth.keys()), len(truth.keys() - predicted.keys())
        sev_correct = sum(predicted[k]["severity"] == truth[k]["severity"] for k in overlap)
        clean, flagged = int(not truth), int(not truth and bool(predicted))
        for group in ("all", case["tier"]):
            t = totals[group]
            for label, value in (("tp", tp), ("fp", fp), ("fn", fn),
                                 ("severity_correct", sev_correct),
                                 ("clean", clean), ("clean_flagged", flagged)):
                t[label] += value
        cases.append({
            "id": case["id"], "tier": case["tier"], "true_positives": tp,
            "false_positives": fp, "false_negatives": fn,
            "severity_correct": sev_correct,
            "unexpected": [dict(path=p, line=l, rule=r) for p, l, r
                           in sorted(predicted.keys() - truth.keys())],
            "missed": [dict(path=p, line=l, rule=r) for p, l, r
                       in sorted(truth.keys() - predicted.keys())],
        })
    metrics = {}
    for group, t in sorted(totals.items()):
        precision = _pct(t["tp"], t["tp"] + t["fp"])
        recall = _pct(t["tp"], t["tp"] + t["fn"])
        f1 = _pct(2 * t["tp"], 2 * t["tp"] + t["fp"] + t["fn"])
        metrics[group] = {
            **t, "precision": precision, "recall": recall, "f1": f1,
            "severity_accuracy_on_matched": _pct(t["severity_correct"], t["tp"]),
            "clean_case_false_positive_rate": _pct(t["clean_flagged"], t["clean"]),
        }
    return {
        "format": "daddy-reviews-quality-result-v1",
        "case_count": len(cases), "metrics_by_tier": metrics, "cases": cases,
        "limitations": [
            "Human-verified input labels are asserted by the dataset author, not cryptographically certified.",
            "Rules are compared by exact path/line/rule identity; semantic equivalents need manual annotation.",
            "Synthetic fixtures are not evidence of real-world model defect-detection accuracy.",
            "Small samples, especially a single clean case, cannot estimate production false-positive rates.",
        ],
    }


def summarize_runtime(reports: list[dict], input_usd_per_million: float | None = None,
                      output_usd_per_million: float | None = None) -> dict:
    """Aggregate actual recorded tokens and wall time; pricing is caller-supplied.

    Missing usage is reported, never estimated as zero.
    """
    for rate in (input_usd_per_million, output_usd_per_million):
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float))
                                 or not 0 <= rate <= 1000):
            raise QualityError("Invalid price per million tokens")
    if not isinstance(reports, list) or len(reports) > 1000:
        raise QualityError("Expected up to 1000 runtime reports")
    runs = []
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("reviewer_runs"), list):
            raise QualityError("Invalid runtime report")
        for row in report["reviewer_runs"]:
            if not isinstance(row, dict) or row.get("status") not in ("completed", "failed"):
                raise QualityError("Invalid reviewer status")
            runtime_ms = row.get("latency_ms")
            if (not isinstance(runtime_ms, (int, float)) or isinstance(runtime_ms, bool)
                    or not math.isfinite(runtime_ms) or runtime_ms < 0):
                raise QualityError("Missing or invalid measured latency")
            tokens = row.get("usage")
            if tokens is not None:
                if not isinstance(tokens, dict) or any(type(tokens.get(k)) is not int or
                        tokens[k] < 0 for k in ("input_tokens", "output_tokens")):
                    raise QualityError("Malformed model token counts")
            runs.append(row)
    latencies = sorted(x["latency_ms"] for x in runs)
    def percentile(q):
        if not latencies:
            return None
        idx = min(len(latencies) - 1, max(0, int((len(latencies) - 1) * q + 0.999999)))
        return round(latencies[idx], 2)
    usage = [x["usage"] for x in runs if x.get("usage") is not None]
    input_tokens = sum(x["input_tokens"] for x in usage)
    output_tokens = sum(x["output_tokens"] for x in usage)
    cost = None
    if (len(usage) == len(runs) and input_usd_per_million is not None
            and output_usd_per_million is not None):
        cost = round((input_tokens * input_usd_per_million +
                      output_tokens * output_usd_per_million) / 1_000_000, 6)
    return {
        "report_count": len(reports), "reviewer_runs": len(runs),
        "complete_runs": sum(x["status"] == "completed" for x in runs),
        "failed_runs": sum(x["status"] == "failed" for x in runs),
        "p50_latency_ms": percentile(0.50), "p95_latency_ms": percentile(0.95),
        "reported_input_tokens": input_tokens, "reported_output_tokens": output_tokens,
        "runs_missing_usage": len(runs) - len(usage),
        "estimated_cost_usd": cost,
        "pricing_note": "User-supplied dollars per million input/output tokens; None means unavailable",
        "limitations": ["No tokens or costs are inferred for missing usage.",
                        "These are observed model run metrics, not end-to-end reviewer quality."],
    }
