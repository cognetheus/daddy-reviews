"""R8.05d.05: no operational evidence is authority to approve, post, or merge."""
import copy
import json
from pathlib import Path

import pytest

from daddy_reviews import cli, ops_readiness
from daddy_reviews.ops_telemetry import OperationalError, make_event


def evidence():
    events = [
        make_event("review_probe", "ok", 10, 15),
        make_event("review_probe", "ok", 20, 16),
        make_event("supervisor_fault_probe", "ok", 1),
        make_event("supervisor_fault_probe", "ok", 2),
        make_event("supervisor_fault_probe", "ok", 3),
        make_event("supervisor_fault_probe", "ok", 4),
    ]
    return {
        "format": ops_readiness.FORMAT,
        "source_commit": "a" * 40,
        "benchmark": {
            "format": "daddy-reviews-ops-benchmark-v1",
            "status": "local_benchmark_within_budget",
            "hard_runtime_deadline_enforced": False,
            "hard_rss_limit_enforced": False,
            "events": events[:2],
        },
        "fault_injection": {
            "format": "daddy-reviews-ops-fault-injection-v1",
            "status": "failure_controls_verified", "events": events[2:],
        },
        "static_security": {
            "format": "daddy-reviews-ops-static-security-v1",
            "status": "local_static_security_checks_passed",
            "live_github_branch_protection_verified": False,
        },
        "telemetry": {
            "format": "daddy-reviews-ops-telemetry-v1",
            "status": "local_candidate_within_budget",
            "live_service_slo_proven": False,
            "external_alert_sent": False,
        },
    }


def test_all_local_controls_cannot_authorize_production():
    result = ops_readiness.assess_operational_evidence(evidence())
    assert result["status"] == "local_operational_candidate"
    assert result["local_checks_passed"] is True
    assert result["local_blockers"] == []
    assert result["external_release_blockers"] == list(
        ops_readiness.EXTERNAL_RELEASE_GATES)
    assert result["evidence_provenance"] == "local_unattested_operator_report"
    assert result["external_human_defect_truth_proven"] is False
    assert result["github_branch_protection_proven"] is False
    assert result["model_quality_approved"] is False
    assert result["production_ready"] is False
    assert result["release_authorized"] is False
    assert result["github_publication"] == result["merge_action"] == "none"


def test_degraded_benchmark_and_security_produce_specific_blockers():
    data = evidence()
    data["benchmark"]["status"] = "local_benchmark_failed"
    data["static_security"]["status"] = "local_static_security_checks_failed"
    result = ops_readiness.assess_operational_evidence(data)
    assert result["status"] == "local_operational_checks_blocked"
    assert "benchmark_unverified_or_failed" in result["local_blockers"]
    assert "static_security_unverified_or_failed" in result["local_blockers"]


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(source_commit="not-sha"),
    lambda d: d.update(benchmark=[]),
    lambda d: d["benchmark"].update(release_authorized=True),
    lambda d: d["static_security"].update(live_github_branch_protection_verified=True),
    lambda d: d["telemetry"].update(external_alert_sent=True),
    lambda d: d["telemetry"].update(live_service_slo_proven=True),
    lambda d: d["benchmark"].update(hard_rss_limit_enforced=True),
    lambda d: d["benchmark"].update(hard_runtime_deadline_enforced=True),
])
def test_forged_operator_claims_are_rejected(mutate):
    data = evidence()
    mutate(data)
    with pytest.raises(OperationalError):
        ops_readiness.assess_operational_evidence(data)


def test_local_git_head_requires_actual_root(tmp_path):
    with pytest.raises(OperationalError):
        ops_readiness.pinned_local_head(tmp_path)


def test_operational_preflight_detects_source_change_between_probes(tmp_path, monkeypatch):
    data = evidence()
    head = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(ops_readiness, "pinned_local_head", lambda root: next(head))
    monkeypatch.setattr(ops_readiness, "benchmark_review",
                        lambda *a, **k: data["benchmark"])
    monkeypatch.setattr(ops_readiness, "probe_supervisor_faults",
                        lambda root: {
                            **data["fault_injection"], "scenario_count": 4})
    monkeypatch.setattr(ops_readiness, "static_security_preflight",
                        lambda root: data["static_security"])
    with pytest.raises(OperationalError, match="HEAD changed"):
        ops_readiness.run_operational_preflight(tmp_path, "fixture-patch")


def test_cli_ops_readiness_is_always_nonzero_for_production(tmp_path, capsys):
    path = tmp_path / "ops-evidence.json"
    path.write_text(json.dumps(evidence()))
    with pytest.raises(SystemExit) as ex:
        cli.main(["ops-readiness", "--root", str(tmp_path),
                  "--ops-evidence-file", str(path)])
    assert ex.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "local_operational_candidate"
    assert report["release_authorized"] is False


def test_cli_local_telemetry_is_observational_only(tmp_path, capsys):
    event_file = tmp_path / "events.json"
    source = [
        make_event("review_probe", "ok", 10),
        make_event("review_probe", "ok", 10),
        *[make_event("supervisor_fault_probe", "ok", 1) for _ in range(4)],
    ]
    event_file.write_text(json.dumps(source))
    cli.main(["ops-telemetry", "--root", str(tmp_path),
              "--ops-evidence-file", str(event_file)])
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "local_candidate_within_budget"
    assert report["external_alert_sent"] is False


def test_preflight_cli_passes_pinned_budget_and_untrusted_diff_safely(
        tmp_path, capsys, monkeypatch):
    args = []
    def fake_run(root, patch, **kw):
        args.append((root, patch, kw))
        return {"readiness": {"status": "local_operational_candidate"},
                "source_commit": "a"*40, "format": ops_readiness.FORMAT}
    monkeypatch.setattr(cli, "run_operational_preflight", fake_run)
    patch = tmp_path / "input.diff"
    patch.write_text("synthetic")
    cli.main([
        "ops-preflight", "--root", str(tmp_path), "--diff-file", str(patch),
        "--ops-samples", "3", "--ops-p95-ms", "4000",
        "--ops-peak-kib", "65536",
    ])
    result = json.loads(capsys.readouterr().out)
    assert result["readiness"]["status"] == "local_operational_candidate"
    assert args[0][1] == "synthetic"
    assert args[0][2] == {
        "samples": 3, "latency_budget_ms": 4000, "peak_budget_kib": 65536}
