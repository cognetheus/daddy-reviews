"""R8.05d.05: source-pinned local operational acceptance, always advisory.

No input (including signed-looking operator JSON) grants merge privileges,
model promotion, or production readiness. Only an authorized future release
process can combine a protected live branch, genuine independently human-labeled
accuracy study, performance evidence and operator sign-off.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

from .ops_telemetry import OperationalError, summarize_events
from .ops_runtime import benchmark_review, probe_supervisor_faults
from .ops_security import static_security_preflight

FORMAT = "daddy-reviews-operational-preflight-v1"
ASSESSMENT = "daddy-reviews-operational-acceptance-v1"
SHA = re.compile(r"[0-9a-f]{40}\Z")
EXTERNAL_RELEASE_GATES = (
    "live_protected_main_and_required_reviews",
    "independent_precommitted_human_defect_study",
    "full_cross_platform_dependency_and_runtime_provenance",
    "human_authorized_production_PR_pilot_and_rollback",
)


def pinned_local_head(root: Path) -> str:
    """Read Git identity without network, shell, checkout or repository writes."""
    if not isinstance(root, Path) or not root.is_dir():
        raise OperationalError("Expected source checkout")
    root = root.resolve(strict=True)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=False, timeout=8,
        )
        toplevel = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=False, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationalError("Cannot read pinned local Git source") from exc
    head = result.stdout.strip()
    if (result.returncode != 0 or toplevel.returncode != 0
            or not SHA.fullmatch(head)
            or Path(toplevel.stdout.strip()).resolve() != root):
        raise OperationalError("Operational preflight must run at the exact Git repository root")
    return head


def assess_operational_evidence(evidence: dict) -> dict:
    """Validate self-reported evidence, NEVER treat it as externally attested.

    In particular a forged input can at most say local checks *appear* to
    pass; production gates remain unsatisfied and non-overridable.
    """
    if (not isinstance(evidence, dict)
            or evidence.get("format") != FORMAT
            or not isinstance(evidence.get("source_commit"), str)
            or not SHA.fullmatch(evidence["source_commit"])):
        raise OperationalError("Invalid source-bound operational evidence format")
    benchmark = evidence.get("benchmark")
    faults = evidence.get("fault_injection")
    security = evidence.get("static_security")
    telemetry = evidence.get("telemetry")
    if not all(isinstance(item, dict) for item in
               (benchmark, faults, security, telemetry)):
        raise OperationalError("Incomplete operational evidence")
    expected = {
        "benchmark": ("daddy-reviews-ops-benchmark-v1",
                      "local_benchmark_within_budget"),
        "fault_injection": ("daddy-reviews-ops-fault-injection-v1",
                            "failure_controls_verified"),
        "static_security": ("daddy-reviews-ops-static-security-v1",
                            "local_static_security_checks_passed"),
        "telemetry": ("daddy-reviews-ops-telemetry-v1",
                      "local_candidate_within_budget"),
    }
    values = {
        "benchmark": benchmark, "fault_injection": faults,
        "static_security": security, "telemetry": telemetry,
    }
    blockers = []
    for label, (fmt, status) in expected.items():
        result = values[label]
        if result.get("format") != fmt or result.get("status") != status:
            blockers.append(label + "_unverified_or_failed")
        if result.get("release_authorized") is True or result.get(
                "production_authorized") is True:
            raise OperationalError("Self-reported evidence cannot grant release authority")
    if benchmark.get("hard_runtime_deadline_enforced") is True or benchmark.get(
            "hard_rss_limit_enforced") is True:
        raise OperationalError("Local review benchmark cannot claim hard OS budget enforcement")
    if security.get("live_github_branch_protection_verified") is True:
        raise OperationalError("Offline static source scan cannot authenticate GitHub branch protections")
    if telemetry.get("live_service_slo_proven") is True or telemetry.get(
            "external_alert_sent") is True:
        raise OperationalError("Local batch telemetry cannot prove live service SLAs")
    return {
        "format": ASSESSMENT,
        "source_commit": evidence["source_commit"],
        "status": ("local_operational_candidate" if not blockers
                   else "local_operational_checks_blocked"),
        "local_checks_passed": not blockers,
        "local_blockers": sorted(blockers),
        "external_release_blockers": list(EXTERNAL_RELEASE_GATES),
        "evidence_provenance": "local_unattested_operator_report",
        "observed_real_source_code": False,  # cannot prove origins from JSON
        "external_human_defect_truth_proven": False,
        "github_branch_protection_proven": False,
        "model_quality_approved": False,
        "production_ready": False,
        "release_authorized": False,
        "human_signoff_required": True,
        "github_publication": "none", "merge_action": "none",
    }


def run_operational_preflight(root: Path, patch: str, *,
                              samples: int = 2, latency_budget_ms: int = 60_000,
                              peak_budget_kib: int = 262_144) -> dict:
    """Actual local review benchmark + real child failure tests + static scan.

    The fixed source and model arguments are read-only; no GitHub API call is
    made. Output intentionally excludes source text, diff, paths and secrets.
    """
    commit_before = pinned_local_head(root)
    benchmark = benchmark_review(
        root, patch, samples=samples, latency_budget_ms=latency_budget_ms,
        peak_budget_kib=peak_budget_kib)
    faults = probe_supervisor_faults(root)
    security = static_security_preflight(root)
    telemetry = summarize_events(
        [*benchmark["events"], *faults["events"]],
        minimum=samples + faults["scenario_count"],
        max_failures=0, p95_budget_ms=latency_budget_ms)
    commit_after = pinned_local_head(root)
    if commit_before != commit_after:
        raise OperationalError("Local source HEAD changed during operational preflight")
    evidence = {
        "format": FORMAT, "source_commit": commit_before,
        "benchmark": benchmark, "fault_injection": faults,
        "static_security": security, "telemetry": telemetry,
    }
    evidence["readiness"] = assess_operational_evidence(evidence)
    return evidence
