"""R8.05d.03: privacy-preserving operational events and local SLO candidates.

Events are closed-schema counters/timings only, never exceptions, source text,
URLs, paths, tokens, diffs, names or repository metadata. This is a batch
summary, not a running metrics collector or an external alert service.
"""
from __future__ import annotations

from math import ceil

FORMAT = "daddy-reviews-ops-event-v1"
SUMMARY_FORMAT = "daddy-reviews-ops-telemetry-v1"
OPERATIONS = frozenset(("review_probe", "supervisor_fault_probe"))
OUTCOMES = frozenset(("ok", "failure", "budget_exceeded"))
MAX_EVENTS = 128


class OperationalError(ValueError):
    """Invalid or unsafe operational evidence."""


def make_event(operation: str, outcome: str, elapsed_ms: int,
               peak_python_kib: int = 0) -> dict:
    if (not isinstance(operation, str) or operation not in OPERATIONS
            or not isinstance(outcome, str) or outcome not in OUTCOMES
            or type(elapsed_ms) is not int or not 0 <= elapsed_ms <= 120_000
            or type(peak_python_kib) is not int
            or not 0 <= peak_python_kib <= 1_048_576):
        raise OperationalError("Invalid bounded, code-free operational event")
    return {
        "format": FORMAT, "operation": operation, "outcome": outcome,
        "elapsed_ms": elapsed_ms, "peak_python_kib": peak_python_kib,
    }


def _checked(event: dict) -> dict:
    if (not isinstance(event, dict)
            or set(event) != {
                "format", "operation", "outcome", "elapsed_ms", "peak_python_kib"}
            or event.get("format") != FORMAT):
        raise OperationalError("Operational telemetry requires closed-schema records")
    make_event(event["operation"], event["outcome"],
               event["elapsed_ms"], event["peak_python_kib"])
    return event


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


def summarize_events(events: list[dict], *, minimum: int = 5,
                     max_failures: int = 0, p95_budget_ms: int = 30_000) -> dict:
    """Aggregate bounded, strictly anonymous structured events.

    Every alert is a *local candidate*. No HTTP callback or external
    telemetry publisher is provided; alerting integration needs operator
    controls, authenticated transport and retention policy.
    """
    if (not isinstance(events, list) or len(events) > MAX_EVENTS
            or type(minimum) is not int or not 1 <= minimum <= MAX_EVENTS
            or type(max_failures) is not int or not 0 <= max_failures <= 16
            or type(p95_budget_ms) is not int or not 1 <= p95_budget_ms <= 120_000):
        raise OperationalError("Invalid telemetry batch/budget")
    checked = [_checked(event) for event in events]
    failures = sum(e["outcome"] != "ok" for e in checked)
    review = [e for e in checked if e["operation"] == "review_probe"]
    faults = [e for e in checked if e["operation"] == "supervisor_fault_probe"]
    p95 = _p95([e["elapsed_ms"] for e in review])
    alerts = []
    if len(checked) < minimum:
        alerts.append("insufficient_observations")
    if not review or not faults:
        alerts.append("missing_review_or_failure_probe_coverage")
    if failures > max_failures:
        alerts.append("event_failure_budget_exceeded")
    if review and p95 > p95_budget_ms:
        alerts.append("review_latency_candidate_budget_exceeded")
    return {
        "format": SUMMARY_FORMAT,
        "status": "local_candidate_alerts" if alerts else "local_candidate_within_budget",
        "observed_events": len(checked),
        "review_probe_events": len(review),
        "fault_probe_events": len(faults),
        "error_count": failures,
        "error_rate_ppm": failures * 1_000_000 // len(checked) if checked else None,
        "review_p95_ms": p95 if review else None,
        "review_peak_python_kib": max((e["peak_python_kib"] for e in review), default=None),
        "budget": {
            "minimum_events": minimum, "maximum_failures": max_failures,
            "review_p95_ms": p95_budget_ms,
        },
        "alerts": sorted(alerts),
        "external_alert_sent": False,
        "live_service_slo_proven": False,
        "source_data_included": False,
        "production_authorized": False,
    }
