"""R8.03 deterministic specialist investigation replay and quality calibration.

Scripts stand in for model turns ONLY. R8.02 still executes real R8.01
read-only tools against materialized source fixtures and validates host-issued
source-span evidence. No model is contacted and no untrusted code is executed.

Synthetic labels are kept separate from independently human-adjudicated labels;
neither format asserts that replay metrics reflect production model accuracy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Lock

from .agents import SPECIALISTS
from .diff import DiffError, parse_diff
from .investigative_agents import investigate_with_specialists
from .investigation import TOOLS
from .quality import LEVELS
from .semantic_contracts import _safe_path

FORMAT = "daddy-reviews-investigation-replay-v1"
RESULT_FORMAT = "daddy-reviews-investigation-replay-result-v1"
COMPARE_FORMAT = "daddy-reviews-investigation-replay-compare-v1"
MAX_DATASET_BYTES = 2_000_000
MAX_CASES = 200
MAX_FILES_PER_CASE = 20
MAX_FIXTURE_BYTES = 200_000
MAX_TURNS = 5
MAX_JSON_TURN_BYTES = 32_000
CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
HEX = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".cs"}
RATES = {"input": "input_usd_per_million", "output": "output_usd_per_million"}


class ReplayError(ValueError):
    """Invalid replay dataset, model script, or comparison input."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_fixture_path(path):
    return (isinstance(path, str) and 0 < len(path) <= 250
            and _safe_path(path) and not any(
                part in {".git", ".venv", "node_modules", ".github", "dist", "build"}
                for part in path.split("/")
            ) and (Path(path).suffix in ALLOWED_EXT or
                   Path(path).name in {"openapi.json", "swagger.json", "openapi-v3.json"}))


def _finding_valid(value):
    return (isinstance(value, dict) and set(value) == {
        "path", "line", "rule", "severity"
    } and _safe_fixture_path(value.get("path"))
        and type(value.get("line")) is int and value["line"] > 0
        and isinstance(value.get("rule"), str)
        and 0 < len(value["rule"]) <= 120 and value.get("severity") in LEVELS)


def _checked_case(case, dataset_kind):
    if not isinstance(case, dict) or not CASE_ID.fullmatch(str(case.get("id", ""))):
        raise ReplayError("Case IDs must be unique, printable and bounded")
    if case.get("tier") not in ("trivial", "lite", "full"):
        raise ReplayError("Case needs a review tier")
    labels = case.get("label_status")
    if labels != ("synthetic" if dataset_kind == "synthetic" else "human_verified"):
        raise ReplayError("Case labels disagree with declared dataset kind")
    if dataset_kind == "human_labeled":
        provenance = case.get("label_metadata")
        if (not isinstance(provenance, dict) or
                set(provenance) != {"reviewer_id", "reviewed_at", "protocol"} or
                not isinstance(provenance["reviewer_id"], str) or
                not 3 <= len(provenance["reviewer_id"]) <= 120 or
                provenance.get("protocol") != "human-adjudicated-v1"):
            raise ReplayError("Human labels need traceable review metadata")
        try:
            date.fromisoformat(provenance["reviewed_at"])
        except (ValueError, TypeError) as exc:
            raise ReplayError("Invalid label review date") from exc
    files = case.get("files")
    if (not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES_PER_CASE
            or any(not _safe_fixture_path(p) or not isinstance(source, str)
                   for p, source in files.items())
            or sum(len(x.encode("utf-8")) for x in files.values()) > MAX_FIXTURE_BYTES):
        raise ReplayError("Unsafe, oversized or empty source fixture")
    for path, source in files.items():
        if len(source.encode("utf-8")) > 350_000:
            raise ReplayError("Source file exceeds manifest budget")
    patch = case.get("patch")
    if not isinstance(patch, str) or not 0 < len(patch.encode("utf-8")) <= 24_000:
        raise ReplayError("Missing or oversized diff")
    try:
        changes = parse_diff(patch)
    except DiffError as exc:
        raise ReplayError("Invalid unified patch") from exc
    changed = {c.new_path: set(c.added_lines) for c in changes
               if c.new_path and c.added_lines}
    if not changed or not changed.keys() <= files.keys():
        raise ReplayError("All diff additions must have fixture source files")
    expected = case.get("expected")
    if (not isinstance(expected, list) or len(expected) > 40
            or any(not _finding_valid(e) for e in expected)):
        raise ReplayError("Ground-truth labels are malformed or exceed budget")
    keys = set()
    for e in expected:
        key = (e["path"], e["line"], e["rule"])
        if key in keys or e["line"] not in changed.get(e["path"], set()):
            raise ReplayError("Ground-truth defects must uniquely identify added lines")
        keys.add(key)
    reviewers = case.get("reviewers")
    if not isinstance(reviewers, list) or not 1 <= len(reviewers) <= 6:
        raise ReplayError("Each case needs 1–6 scripted specialists")
    names = set()
    for script in reviewers:
        if not isinstance(script, dict) or set(script) != {"name", "turns"}:
            raise ReplayError("Invalid specialist script")
        name = script["name"]
        if name not in SPECIALISTS or name in names:
            raise ReplayError("Duplicate or unsupported specialist")
        names.add(name)
        turns = script["turns"]
        if not isinstance(turns, list) or not 1 <= len(turns) <= MAX_TURNS:
            raise ReplayError("Specialist script must contain 1–5 turns")
        for turn in turns:
            if not isinstance(turn, dict) or len(_canonical(turn).encode("utf-8")) > MAX_JSON_TURN_BYTES:
                raise ReplayError("Scripted model turns must be bounded JSON objects")
            if turn.get("kind") == "transport_error":
                if set(turn) != {"kind", "error"} or turn["error"] not in {
                    "TimeoutError", "ConnectionError", "OSError",
                }:
                    raise ReplayError("Unsupported simulated transport fault")
            elif turn.get("kind") not in {"tool", "final"}:
                raise ReplayError("Script turn must be tool, final or transport_error")
    allowed_tools = case.get("allowed_tools")
    if (not isinstance(allowed_tools, list) or len(allowed_tools) != len(set(allowed_tools))
            or any(t not in TOOLS for t in allowed_tools)):
        raise ReplayError("Tool grant list must be explicit and unique")
    if case.get("expected_status") not in {"complete", "incomplete"}:
        raise ReplayError("Case needs expected complete/incomplete outcome")
    for key, upper in (("max_rounds", 5), ("max_tools", 4)):
        value = case.get(key, 4 if key == "max_rounds" else 3)
        if type(value) is not int or not 1 <= value <= upper:
            raise ReplayError("Invalid specialist investigation budgets")


def validate_replay_dataset(dataset):
    if not isinstance(dataset, dict) or dataset.get("format") != FORMAT:
        raise ReplayError("Expected investigation-replay-v1 dataset")
    if dataset.get("dataset_kind") not in {"synthetic", "human_labeled"}:
        raise ReplayError("Declare synthetic or human_labeled dataset_kind explicitly")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ReplayError("Dataset needs 1–200 bounded cases")
    seen = set()
    for case in cases:
        _checked_case(case, dataset["dataset_kind"])
        if case["id"] in seen:
            raise ReplayError("Duplicate case identifier")
        seen.add(case["id"])
    if len(_canonical(dataset).encode("utf-8")) > MAX_DATASET_BYTES:
        raise ReplayError("Replay dataset exceeds 2 MB")


def read_replay_dataset(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATASET_BYTES:
        raise ReplayError("Dataset missing, symlinked or too large")
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReplayError("Malformed replay JSON") from exc
    validate_replay_dataset(dataset)
    return dataset


class _ScriptedProvider:
    """Thread-safe provider of recorded MODEL decisions, not recorded tool results."""

    def __init__(self, scripts):
        self.turns = {script["name"]: script["turns"] for script in scripts}
        self.consumed = {name: 0 for name in self.turns}
        self.observed_tool_results = {name: [] for name in self.turns}
        self.lock = Lock()

    def __call__(self, reviewer, messages):
        with self.lock:
            if reviewer not in self.turns:
                raise ReplayError("Unscripted specialist")
            index = self.consumed[reviewer]
            turns = self.turns[reviewer]
            if index >= len(turns):
                raise ReplayError("Model requested an unrecorded replay turn")
            if not isinstance(messages, list) or len(messages) != 1 + 2 * index:
                raise ReplayError("Replay message sequence disagrees with scripted turns")
            if index:
                previous = turns[index - 1]
                if previous.get("kind") != "tool":
                    raise ReplayError("Unexpected model call after terminal script action")
                try:
                    observed = json.loads(messages[-1]["content"])
                    result = observed["tool_result"]
                    proof = observed["host_evidence_ids"]
                except (ValueError, KeyError, TypeError) as exc:
                    raise ReplayError("Host did not provide a real tool response") from exc
                if result.get("status") != "complete" or not isinstance(proof, dict):
                    raise ReplayError("Replay expected a successful real tool response")
                if result["tool"] != previous.get("call", {}).get("tool"):
                    raise ReplayError("Tool response does not match preceding scripted tool request")
                self.observed_tool_results[reviewer].append({
                    "tool": result["tool"], "status": result["status"],
                    "response_sha256": _digest(result),
                    "evidence_sha256": _digest(proof),
                    "issued_evidence_count": len(proof),
                })
            item = turns[index]
            self.consumed[reviewer] += 1
            if item["kind"] == "transport_error":
                err = item["error"]
                if err == "TimeoutError":
                    raise TimeoutError("Synthetic replay timeout")
                if err == "ConnectionError":
                    raise ConnectionError("Synthetic replay connection failure")
                raise OSError("Synthetic replay transport failure")
            # Return a JSON round-trip copy so the harness cannot mutate fixtures.
            return json.loads(_canonical(item))


def _key(item):
    return item["path"], item["line"], item["rule"]


def _quality(expected, observed):
    """Duplicate predictions are counted as extra false positives, not collapsed."""
    truth = {_key(x): x for x in expected}
    found = Counter(_key(x) for x in observed)
    overlap = set(truth) & set(found)
    tp = len(overlap)
    fp = sum(found.values()) - tp
    fn = len(truth) - tp
    matched_severity = sum(
        next(x["severity"] for x in observed if _key(x) == key) ==
        truth[key]["severity"]
        for key in overlap
    )
    return {
        "tp": tp, "fp": fp, "fn": fn, "severity_correct": matched_severity,
        "unexpected": [dict(path=k[0], line=k[1], rule=k[2])
                       for k in sorted(found) for _ in range(
                           found[k] - int(k in truth)
                       )],
        "missed": [dict(path=k[0], line=k[1], rule=k[2])
                   for k in sorted(truth.keys() - overlap)],
    }


def _fraction(a, b):
    return round(a / b, 4) if b else None


def _aggregate(cases):
    buckets = defaultdict(lambda: {
        "tp": 0, "fp": 0, "fn": 0, "severity_correct": 0,
        "clean_cases": 0, "clean_flagged": 0, "incomplete": 0,
        "cases": 0, "tool_calls": 0, "model_turns": 0,
    })
    for case in cases:
        for name in ("all", case["tier"]):
            slot = buckets[name]
            slot["cases"] += 1
            for key in ("tp", "fp", "fn", "severity_correct", "tool_calls", "model_turns"):
                slot[key] += case[key]
            slot["clean_cases"] += int(case["ground_truth_count"] == 0)
            slot["clean_flagged"] += int(case["ground_truth_count"] == 0 and case["fp"] > 0)
            slot["incomplete"] += int(case["status"] != "complete")
    scores = {}
    for name, t in sorted(buckets.items()):
        scores[name] = {
            **t, "precision": _fraction(t["tp"], t["tp"] + t["fp"]),
            "recall": _fraction(t["tp"], t["tp"] + t["fn"]),
            "f1": _fraction(2 * t["tp"], 2 * t["tp"] + t["fp"] + t["fn"]),
            "severity_accuracy_on_matches": _fraction(t["severity_correct"], t["tp"]),
            "clean_case_false_positive_rate": _fraction(t["clean_flagged"], t["clean_cases"]),
            "incomplete_rate": _fraction(t["incomplete"], t["cases"]),
            "avg_tool_calls_per_case": _fraction(t["tool_calls"], t["cases"]),
            "avg_model_turns_per_case": _fraction(t["model_turns"], t["cases"]),
        }
    return scores


def evaluate_replay(dataset):
    """Replay real tools against isolated fixture worktrees; never call a model."""
    validate_replay_dataset(dataset)
    results = []
    for case in dataset["cases"]:
        scripted = _ScriptedProvider(case["reviewers"])
        with TemporaryDirectory(prefix="daddy-replay-") as temporary:
            root = Path(temporary)
            for name, source in case["files"].items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            try:
                report = investigate_with_specialists(
                    root, case["patch"], scripted,
                    allowed_tools=case["allowed_tools"],
                    reviewers=tuple(x["name"] for x in case["reviewers"]),
                    max_rounds=case.get("max_rounds", 4),
                    max_tools_per_reviewer=case.get("max_tools", 3),
                    max_workers=1,
                )
            except Exception as exc:
                # An orchestration crash or invalid fixture is not converted
                # into a successful replay or a supposed true negative.
                raise ReplayError(f"Investigation failed for case {case['id']}: "
                                  f"{type(exc).__name__}") from exc
        observed = report["model_findings"]
        summary = _quality(case["expected"], observed)
        consumed = all(
            scripted.consumed[x["name"]] == len(x["turns"])
            for x in case["reviewers"]
        )
        status = report["status"]
        runs = report["reviewer_runs"]
        fingerprint = {
            "snapshot_id": report["snapshot_id"],
            "patch_sha256": report["patch_sha256"],
            "status": status,
            "reviewer_runs": [{
                "reviewer": r["reviewer"], "status": r["status"],
                "reason": r["reason"], "round_count": r["round_count"],
                "tool_calls": r["tool_calls"], "audit": r["audit"],
                "findings": r["findings"],
            } for r in runs],
            "tool_results": scripted.observed_tool_results,
        }
        result = {
            "id": case["id"], "tier": case["tier"], "status": status,
            "expected_status": case["expected_status"],
            "expectation_met": status == case["expected_status"] and consumed,
            "script_fully_consumed": consumed,
            "ground_truth_count": len(case["expected"]),
            "observed_count": len(observed),
            **summary,
            "tool_calls": sum(r["tool_calls"] for r in runs),
            "model_turns": sum(r["round_count"] for r in runs),
            "tool_failures": sum(
                1 for r in runs for a in r["audit"]
                if a["action"] == "tool" and a["status"] != "complete"
            ),
            "replayed_tool_results": scripted.observed_tool_results,
            "reviewers": [{
                "name": r["reviewer"], "status": r["status"],
                "failure_reason": r["reason"],
                "round_count": r["round_count"], "tool_calls": r["tool_calls"],
                "latency_ms": r["latency_ms"],
                "usage_source": "not_recorded_in_synthetic_replay",
            } for r in runs],
            "trace_sha256": _digest(fingerprint),
        }
        results.append(result)
    # Bind comparison to source/patch/truth, not the candidate model transcript.
    identity = [{
        "id": case["id"], "tier": case["tier"], "files": case["files"],
        "patch": case["patch"], "expected": case["expected"],
        "label_status": case["label_status"],
        "label_metadata": case.get("label_metadata"),
    } for case in sorted(dataset["cases"], key=lambda c: c["id"])]
    metrics = _aggregate(results)
    expected_ok = all(r["expectation_met"] for r in results)
    return {
        "format": RESULT_FORMAT,
        "status": "evaluated" if expected_ok else "contract_failed",
        "dataset_kind": dataset["dataset_kind"],
        "fixture_set_sha256": _digest(identity),
        "case_count": len(results),
        "metrics_by_tier": metrics,
        "cases": results,
        "tool_turns": sum(r["tool_calls"] for r in results),
        "scripted_model_turns": sum(r["model_turns"] for r in results),
        "cases_with_unexpected_execution": sum(not r["expectation_met"] for r in results),
        "performance": {
            "measurement": "local_replay_worktree_and_tool_execution_not_model_latency",
            "reviewer_latency_ms": [
                run["latency_ms"] for row in results for run in row["reviewers"]
            ],
            "reported_input_tokens": None,
            "reported_output_tokens": None,
            "estimated_cost_usd": None,
        },
        "production_model_quality_claim": False,
        "limitations": [
            "Synthetic cases do not estimate production precision or model recall.",
            "Scripted model turns replay deterministic decisions; no model is called.",
            "Tools are re-executed on fresh isolated fixture files, not substituted with canned results.",
            "Exact path/line/rule matches need human semantic adjudication for equivalent findings.",
            "Incompleted investigations count as missed truth in coverage-adjusted recall; "
            "they are not treated as clean reviews.",
            "Latency measures local replay and tool execution; model inference cost is unavailable.",
            "Human-label metadata is asserted by dataset author, not independently verified.",
        ],
    }


def compare_replay(baseline, candidate, *, max_precision_drop=0.02,
                   max_recall_drop=0.02, max_incomplete_rise=0.02,
                   min_cases=20):
    """Detect paired-case regressions; small sets explicitly abstain from promotion."""
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        if (not isinstance(report, dict) or report.get("format") != RESULT_FORMAT
                or report.get("status") != "evaluated"
                or report.get("dataset_kind") not in ("synthetic", "human_labeled")
                or not isinstance(report.get("cases"), list)
                or not HEX.fullmatch(str(report.get("fixture_set_sha256", "")))):
            raise ReplayError(f"Invalid {label} replay result")
    if (baseline["fixture_set_sha256"] != candidate["fixture_set_sha256"] or
            baseline["dataset_kind"] != candidate["dataset_kind"] or
            {x["id"] for x in baseline["cases"]} !=
            {x["id"] for x in candidate["cases"]} or
            len(baseline["cases"]) != len(candidate["cases"])):
        raise ReplayError("Baseline and candidate must use identical ground-truth source fixtures")
    for rate in (max_precision_drop, max_recall_drop, max_incomplete_rise):
        if (isinstance(rate, bool) or not isinstance(rate, (float, int)) or
                not math.isfinite(rate) or not 0 <= rate <= 1):
            raise ReplayError("Regression threshold must be finite fraction 0..1")
    if type(min_cases) is not int or not 1 <= min_cases <= MAX_CASES:
        raise ReplayError("Invalid minimum benchmark sample")
    before, after = (baseline["metrics_by_tier"]["all"],
                     candidate["metrics_by_tier"]["all"])
    def difference(field):
        x, y = before[field], after[field]
        return None if x is None or y is None else round(y - x, 4)
    deltas = {key: difference(key) for key in (
        "precision", "recall", "f1", "clean_case_false_positive_rate",
        "incomplete_rate", "avg_tool_calls_per_case",
    )}
    regressions = []
    for name, threshold in (("precision", max_precision_drop),
                            ("recall", max_recall_drop)):
        if deltas[name] is not None and deltas[name] < -threshold:
            regressions.append(name + "_regression")
    if (deltas["incomplete_rate"] is not None
            and deltas["incomplete_rate"] > max_incomplete_rise):
        regressions.append("incomplete_rate_regression")
    prior = {x["id"]: x for x in baseline["cases"]}
    newly_broken = sorted(
        x["id"] for x in candidate["cases"]
        if x["status"] != "complete" and prior[x["id"]]["status"] == "complete"
    )
    if newly_broken:
        regressions.append("new_incomplete_cases")
    enough = len(candidate["cases"]) >= min_cases
    if regressions:
        status = "regression"
    elif not enough or candidate["dataset_kind"] == "synthetic":
        status = "insufficient_evidence"
    else:
        status = "no_observed_regression"
    return {
        "format": COMPARE_FORMAT, "status": status,
        "dataset_kind": candidate["dataset_kind"],
        "sample_size": len(candidate["cases"]),
        "min_cases_for_promotion": min_cases,
        "delta": deltas,
        "regression_flags": regressions,
        "newly_incomplete_case_ids": newly_broken,
        "promotion_eligible": status == "no_observed_regression",
        "limitations": [
            "A synthetic dataset is never eligible to establish model quality.",
            "No observed regression is not proof of defect-free investigation.",
            "Relative rates are undefined (null) when the denominator is zero.",
        ],
    }
