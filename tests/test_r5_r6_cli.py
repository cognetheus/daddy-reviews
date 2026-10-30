"""CLI end-to-end smoke tests for R5/R6 without network access."""
import json
from pathlib import Path

import pytest

from daddy_reviews.cli import main


def test_pr_publish_dry_run_is_offline_and_requires_human_approval(tmp_path, capsys):
    report = tmp_path / "approved.json"
    report.write_text(json.dumps({"findings": [{
        "rule": "R01", "path": "src/api.py", "line": 2,
        "claim": "Regression", "evidence": "repro test",
        "severity": "high", "verification": "confirmed",
        "verification_artifact": "tests/test_api.py::test_case",
        "changed": True, "human_approved": True
    }]}))
    main(["pr-publish", "--root", str(tmp_path), "--repo", "acme/repo",
          "--pr", "2", "--report-file", str(report)])
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["eligible_count"] == 1
    assert output["posted"] == []


def test_pr_publish_apply_without_expected_sha_fails_before_network(tmp_path):
    report = tmp_path / "empty.json"
    report.write_text(json.dumps({"findings": []}))
    with pytest.raises(SystemExit) as error:
        main(["pr-publish", "--root", str(tmp_path), "--repo", "acme/repo",
              "--pr", "2", "--report-file", str(report), "--apply"])
    assert error.value.code == 2


def test_quality_eval_and_shadow_compare_cli(tmp_path, capsys):
    data = {"format": "daddy-reviews-quality-v1", "cases": [{
        "id": "case-01", "tier": "trivial", "label_status": "human_verified",
        "expected": [], "observed": []
    }]}
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(data))
    b.write_text(json.dumps(data))
    main(["quality-eval", "--root", str(tmp_path), "--dataset", str(a)])
    score = json.loads(capsys.readouterr().out)
    assert score["case_count"] == 1
    main(["quality-compare", "--root", str(tmp_path),
          "--baseline-dataset", str(a), "--candidate-dataset", str(b)])
    compare = json.loads(capsys.readouterr().out)
    assert compare["status"] == "inconclusive"
    assert compare["release_action"] == "none"


def test_telemetry_cli_records_unknown_usage(tmp_path, capsys):
    report = tmp_path / "run.json"
    report.write_text(json.dumps({"reviewer_runs": [{
        "reviewer": "security", "status": "completed",
        "latency_ms": 25, "usage": None
    }]}))
    main(["telemetry", "--root", str(tmp_path), "--report-file", str(report)])
    data = json.loads(capsys.readouterr().out)
    assert data["reviewer_runs"] == 1
    assert data["runs_missing_usage"] == 1
    assert data["estimated_cost_usd"] is None
