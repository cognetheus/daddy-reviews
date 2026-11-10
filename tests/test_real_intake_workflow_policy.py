"""R8.04h: only blinded review packets leave real-source CI runners."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/real-corpus-intake.yml")


def test_only_blind_source_cases_are_uploaded_for_human_review():
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Publish ONLY blind source packet and operator-safe summary"
    assert marker in text
    publication = text.split(marker, 1)[1]
    assert "actions/upload-artifact@v4" in publication
    assert "name: daddy-blind-real-source-cases" in publication
    assert "/tmp/daddy-real-intake/blind.json" in publication
    assert "/tmp/daddy-real-intake/summary.json" in publication
    assert "/tmp/daddy-real-intake/model-ledger.json" not in publication
    assert "retention-days: 7" in publication
    assert "actions/upload-artifact" not in text.split(marker, 1)[0]


def test_real_intake_ci_has_read_only_permission_and_no_model_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "id-token: write" not in text
    assert "pull_request_target" not in text
    assert "real-model-report" not in text
    assert "source_commit" in text
    assert "git rev-parse" in text
    assert "--real-private-output /tmp/daddy-real-intake/model-ledger.json" in text
