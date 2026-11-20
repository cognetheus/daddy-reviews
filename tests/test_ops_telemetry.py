"""R8.05d.03: metrics are bounded closed-schema, never raw data or claims."""
import pytest

from daddy_reviews.ops_telemetry import (
    OperationalError, make_event, summarize_events, MAX_EVENTS,
)


def stream():
    return [
        make_event("review_probe", "ok", 3, 10),
        make_event("review_probe", "ok", 5, 11),
        make_event("supervisor_fault_probe", "ok", 1),
        make_event("supervisor_fault_probe", "ok", 10),
        make_event("supervisor_fault_probe", "ok", 1010),
        make_event("supervisor_fault_probe", "ok", 2),
    ]


def test_local_batch_reports_percentiles_counts_without_source_or_external_alert():
    summary = summarize_events(stream(), minimum=6, p95_budget_ms=100)
    assert summary["status"] == "local_candidate_within_budget"
    assert summary["observed_events"] == 6
    assert summary["review_probe_events"] == 2
    assert summary["fault_probe_events"] == 4
    assert summary["review_p95_ms"] == 5
    assert summary["review_peak_python_kib"] == 11
    assert summary["error_rate_ppm"] == 0
    assert summary["alerts"] == []
    assert summary["source_data_included"] is False
    assert summary["external_alert_sent"] is False
    assert summary["live_service_slo_proven"] is False
    assert summary["production_authorized"] is False


def test_candidate_alerts_on_failure_budget_breach_and_missing_sample():
    events = stream()
    events[1] = make_event("review_probe", "failure", 120, 11)
    summary = summarize_events(events, minimum=7, p95_budget_ms=100)
    assert summary["status"] == "local_candidate_alerts"
    assert "insufficient_observations" in summary["alerts"]
    assert "event_failure_budget_exceeded" in summary["alerts"]
    assert "review_latency_candidate_budget_exceeded" in summary["alerts"]
    assert summary["error_rate_ppm"] == 166666
    assert not summary["external_alert_sent"]


def test_missing_kind_of_probe_cannot_look_operationally_healthy():
    summary = summarize_events(
        [make_event("review_probe", "ok", 1)] * 5, minimum=5)
    assert summary["status"] == "local_candidate_alerts"
    assert "missing_review_or_failure_probe_coverage" in summary["alerts"]


@pytest.mark.parametrize("event", [
    {"format": "daddy-reviews-ops-event-v1", "operation": "review_probe",
     "outcome": "ok", "elapsed_ms": 10, "peak_python_kib": 1,
     "source": "super-secret=123"},
    {"format": "daddy-reviews-ops-event-v1", "operation": ["not-hashable"],
     "outcome": "ok", "elapsed_ms": 10, "peak_python_kib": 1},
    {"format": "daddy-reviews-ops-event-v1", "operation": "review_probe",
     "outcome": True, "elapsed_ms": 10, "peak_python_kib": 1},
    {"format": "daddy-reviews-ops-event-v1", "operation": "review_probe",
     "outcome": "ok", "elapsed_ms": True, "peak_python_kib": 1},
])
def test_untrusted_event_cannot_exfiltrate_metadata_or_bypass_schema(event):
    with pytest.raises(OperationalError):
        summarize_events([event], minimum=1)


def test_bound_event_count_and_integer_types():
    with pytest.raises(OperationalError):
        summarize_events(stream() * 22)
    with pytest.raises(OperationalError):
        make_event("review_probe", "ok", 120001)
    with pytest.raises(OperationalError):
        make_event("review_probe", "ok", 1, 1048577)
    with pytest.raises(OperationalError):
        summarize_events(stream(), max_failures=True)
