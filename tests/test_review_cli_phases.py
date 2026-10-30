"""CLI regression tests for the new read-only review surfaces."""
import json
from daddy_reviews.cli import main

def test_standards_cli_no_catalog(tmp_path, capsys):
    main(["standards", "--root", str(tmp_path), "--changed", "src/auth/login.py"])
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "not_configured"
    assert data["merge_enforcement"] == "disabled"

def test_adjudicate_cli_never_blocks(tmp_path, capsys):
    report = tmp_path / "review.json"
    report.write_text(json.dumps({"findings": [{
        "rule": "SAMPLE", "path": "src/a.py", "line": 3,
        "claim": "Potential bug", "evidence": "source code pattern",
        "severity": "critical", "verification": "unverified", "changed": True,
    }]}))
    main(["adjudicate", "--root", str(tmp_path), "--report-file", str(report)])
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "evaluated"
    assert data["findings"][0]["status"] == "investigate"
    assert data["merge_action"] == "none"
