"""R8.05d.01–02: actual read-only performance and fault-injection probes."""
from pathlib import Path

import pytest

from daddy_reviews.ops_runtime import benchmark_review, probe_supervisor_faults
from daddy_reviews.ops_telemetry import OperationalError

PATCH = """diff --git a/app.py b/app.py
new file mode 100644
--- /dev/null
+++ b/app.py
@@ -0,0 +1,2 @@
+def calculate(x):
+    return x * 2
"""


def test_review_benchmark_uses_real_source_and_never_returns_code(tmp_path):
    (tmp_path / "app.py").write_text(
        "def calculate(x):\n    return x * 2\n", encoding="utf-8")
    result = benchmark_review(
        tmp_path, PATCH, samples=2, latency_budget_ms=30000,
        peak_budget_kib=262144)
    assert result["status"] == "local_benchmark_within_budget"
    assert result["changed_file_count"] == 1
    assert result["sample_count"] == 2
    assert result["errors"] == 0
    assert len(result["events"]) == 2
    assert all(x["outcome"] == "ok" for x in result["events"])
    assert result["p95_ms"] >= 0
    assert result["peak_python_kib"] > 0
    assert result["hard_runtime_deadline_enforced"] is False
    assert result["hard_rss_limit_enforced"] is False
    assert result["production_workload_slo_proven"] is False
    assert result["release_authorized"] is False
    assert "def calculate" not in str(result)
    assert "return x" not in str(result)


@pytest.mark.parametrize("kwargs", [
    {"samples": 0}, {"samples": 7},
    {"samples": True}, {"latency_budget_ms": False},
    {"latency_budget_ms": 0}, {"peak_budget_kib": 0},
    {"peak_budget_kib": 1048577},
])
def test_invalid_review_probe_budgets_are_rejected(tmp_path, kwargs):
    (tmp_path / "app.py").write_text("def calculate(x):return x * 2\n")
    with pytest.raises(OperationalError):
        benchmark_review(tmp_path, PATCH, **kwargs)


def test_oversized_or_empty_or_malformed_patch_fails_before_source_review(tmp_path):
    (tmp_path / "app.py").write_text("def calculate(x):return x * 2\n")
    for patch in ("", "invalid", "x" * 524289):
        with pytest.raises(OperationalError):
            benchmark_review(tmp_path, patch)


def test_real_fault_injection_covers_healthy_nonzero_flood_and_deadline(tmp_path):
    record = probe_supervisor_faults(tmp_path)
    assert record["status"] == "failure_controls_verified"
    assert record["scenario_count"] == 5
    assert {x["scenario"] for x in record["scenarios"]} == {
        "healthy", "nonzero", "output_flood", "deadline",
        "transient_read_only_recovery"}
    assert all(x["expected_failure_detected"] for x in record["scenarios"])
    assert len(record["events"]) == 5
    assert all(x["outcome"] == "ok" for x in record["events"])
    assert record["arbitrary_untrusted_commands_executed"] is False
    assert record["network_isolation_proven"] is False
    assert record["release_authorized"] is False
    assert "import time" not in str(record)


def test_failures_in_fault_probe_are_reported_not_swallowed(tmp_path, monkeypatch):
    from daddy_reviews import ops_runtime
    monkeypatch.setattr(
        ops_runtime, "run_bounded",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private-key=hidden")))
    result = probe_supervisor_faults(tmp_path)
    assert result["status"] == "failure_controls_regressed"
    assert all(not x["expected_failure_detected"] for x in result["scenarios"])
    assert all(x["outcome"] == "failure" for x in result["events"])
    assert "private-key" not in str(result)


def test_probe_budget_enforcement_remains_advisory_not_os_sandbox(tmp_path, monkeypatch):
    from daddy_reviews import ops_runtime
    (tmp_path / "app.py").write_text("def calculate(x): return x\n")
    monkeypatch.setattr(ops_runtime, "review_patch",
                        lambda root, patch: {"findings": []})
    result = benchmark_review(tmp_path, PATCH, samples=1,
                              latency_budget_ms=30000, peak_budget_kib=262144)
    assert result["hard_runtime_deadline_enforced"] is False
    assert result["release_authorized"] is False
