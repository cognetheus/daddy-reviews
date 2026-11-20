"""R8.05d.01–02: real review benchmarks and isolated failure-injection probes.

Benchmarks time a read-only repository review in-process and measure Python
traced allocations; they are NOT process RSS or hard CPU/memory enforcement.
The fault probe runs only trusted fixed strings with a bounded subprocess,
never an operator/model-supplied command or source from the reviewed repo.
"""
from __future__ import annotations

from math import ceil
from pathlib import Path
import hashlib
import os
import sys
import tracemalloc
from time import perf_counter_ns

from .bounded_exec import run_bounded
from .ops_recovery import RetryDecision, retry_classified_read_only
from .diff import DiffError, parse_diff
from .ops_telemetry import make_event, OperationalError
from .review import review_patch

BENCHMARK = "daddy-reviews-ops-benchmark-v1"
FAULT = "daddy-reviews-ops-fault-injection-v1"
MAX_PATCH_BYTES = 524_288


def _p95(samples: list[int]) -> int:
    seq = sorted(samples)
    return seq[ceil(0.95 * len(seq)) - 1]


def benchmark_review(root: Path, patch: str, *, samples: int = 3,
                     latency_budget_ms: int = 30_000,
                     peak_budget_kib: int = 262_144) -> dict:
    if (not isinstance(root, Path) or not root.is_dir()
            or not isinstance(patch, str)
            or not 1 <= len(patch.encode("utf-8")) <= MAX_PATCH_BYTES
            or type(samples) is not int or not 1 <= samples <= 6
            or type(latency_budget_ms) is not int or not 1 <= latency_budget_ms <= 120_000
            or type(peak_budget_kib) is not int or not 1 <= peak_budget_kib <= 1_048_576):
        raise OperationalError("Review benchmarking requires a bounded patch and explicit budgets")
    try:
        changes = parse_diff(patch)
    except DiffError as exc:
        raise OperationalError("Benchmark patch is not a supported source diff") from exc
    if not changes or len(changes) > 200:
        raise OperationalError("Benchmark requires one to 200 changed paths")
    latencies = []
    peak_kib = 0
    events = []
    file_count = len(changes)
    finding_count = None
    errors = 0
    for _ in range(samples):
        start = perf_counter_ns()
        # tracemalloc is process-global, so this probe must not be run
        # concurrently with another Python memory probe.
        if tracemalloc.is_tracing():
            raise OperationalError("Overlapping process-global allocation tracer")
        tracemalloc.start()
        tracemalloc.reset_peak()
        try:
            review = review_patch(root, patch)
            finding_count = len(review.get("findings", []))
            success = True
        except Exception:
            success = False
            errors += 1
        finally:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        elapsed = round((perf_counter_ns() - start) / 1_000_000)
        peak_sample = (peak + 1023) // 1024
        peak_kib = max(peak_kib, peak_sample)
        latencies.append(elapsed)
        outcome = ("failure" if not success else
                   "budget_exceeded" if elapsed > latency_budget_ms
                   or peak_sample > peak_budget_kib else "ok")
        events.append(make_event("review_probe", outcome, elapsed, peak_sample))
    p95 = _p95(latencies)
    return {
        "format": BENCHMARK,
        "status": ("local_benchmark_within_budget" if not errors
                   and p95 <= latency_budget_ms and peak_kib <= peak_budget_kib
                   else "local_benchmark_failed"),
        "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "changed_file_count": file_count,
        "finding_count_last_sample": finding_count,
        "sample_count": samples, "errors": errors,
        "p95_ms": p95, "latency_samples_ms": latencies,
        "peak_python_kib": peak_kib,
        "budget": {
            "p95_ms": latency_budget_ms,
            "peak_python_kib": peak_budget_kib,
            "max_patch_bytes": MAX_PATCH_BYTES,
        },
        "events": events,
        "hard_runtime_deadline_enforced": False,
        "hard_rss_limit_enforced": False,
        "production_workload_slo_proven": False,
        "source_or_findings_included": False,
        "release_authorized": False,
    }


def probe_supervisor_faults(root: Path) -> dict:
    """Check expected fail-closed behavior via the real bounded subprocess."""
    if not isinstance(root, Path) or not root.is_dir():
        raise OperationalError("Expected trusted source working directory")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    scenarios = [
        ("healthy", "import sys;sys.stdout.write('healthy')", 2, 1024),
        ("nonzero", "import sys;sys.exit(17)", 2, 1024),
        ("output_flood", "import sys;sys.stdout.buffer.write(b'x'*131072)", 2, 1024),
        ("deadline", "import time;time.sleep(4)", 1, 1024),
    ]
    observed = []
    events = []
    for name, source, timeout, size in scenarios:
        try:
            result = run_bounded(
                [sys.executable, "-c", source],
                cwd=root, env=env, timeout=timeout, max_output=size)
            valid = (
                (name == "healthy" and result.returncode == 0
                 and result.output_complete and not result.timeout_expired
                 and result.stdout == b"healthy")
                or (name == "nonzero" and result.returncode == 17
                    and result.output_complete and not result.timeout_expired)
                or (name == "output_flood" and not result.output_complete
                    and not result.timeout_expired and len(result.stdout) <= size)
                or (name == "deadline" and result.returncode == 124
                    and result.timeout_expired and not result.output_complete)
            )
            elapsed = result.elapsed_ms
        except (OSError, ValueError):
            valid = False
            elapsed = 0
        observed.append({
            "scenario": name, "expected_failure_detected": bool(valid),
            "elapsed_ms": min(elapsed, 120_000),
        })
        events.append(make_event("supervisor_fault_probe",
                                 "ok" if valid else "failure",
                                 min(elapsed, 120_000)))
    # Idempotent transient probe: first call exits with a known synthetic
    # retryable code, the second succeeds. No workspace/source writes.
    def read_only_probe(attempt):
        source = ("import sys;sys.exit(75)" if attempt == 1
                  else "import sys;sys.exit(0)")
        result = run_bounded(
            [sys.executable, "-c", source], cwd=root, env=env,
            timeout=2, max_output=1024)
        if result.output_complete and not result.timeout_expired:
            if result.returncode == 0:
                return RetryDecision("ok")
            if result.returncode == 75:
                return RetryDecision("retryable")
        return RetryDecision("permanent")

    recovery = retry_classified_read_only(
        read_only_probe, operation="fixed_health_probe",
        max_attempts=3, base_backoff_ms=10, total_budget_ms=2000)
    recovered = (recovery.status == "recovered"
                 and recovery.attempts == 2 and recovery.retry_count == 1)
    observed.append({
        "scenario": "transient_read_only_recovery",
        "expected_failure_detected": recovered,
        "elapsed_ms": min(recovery.elapsed_ms, 120_000),
    })
    events.append(make_event("supervisor_fault_probe",
                             "ok" if recovered else "failure",
                             min(recovery.elapsed_ms, 120_000)))
    return {
        "format": FAULT,
        "status": ("failure_controls_verified" if all(
            case["expected_failure_detected"] for case in observed)
                   else "failure_controls_regressed"),
        "scenario_count": len(observed),
        "scenarios": observed,
        "events": events,
        "real_processes_executed": True,
        "arbitrary_untrusted_commands_executed": False,
        "network_isolation_proven": False,
        "release_authorized": False,
    }
