"""R8.04i guard: Actions must never upload the sealed model scoring ledger."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/real-opportunity-frame.yml")


def test_workflow_exports_only_blind_packet_and_safe_summary():
    source = WORKFLOW.read_text(encoding="utf-8")
    anchor = "      - name: Publish ONLY blind context opportunities and safe summary"
    assert anchor in source
    before, publish = source.split(anchor, 1)
    assert "actions/upload-artifact" not in before
    assert "actions/upload-artifact@v4" in publish
    assert "name: daddy-blind-opportunity-frame" in publish
    assert "/tmp/daddy-opportunity-intake/blind.json" in publish
    assert "/tmp/daddy-opportunity-intake/summary.json" in publish
    assert "/tmp/daddy-opportunity-intake/private.json" not in publish
    assert "retention-days: 7" in publish


def test_source_intake_is_read_only_and_never_executes_llm_or_labels():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in source
    assert "persist-credentials: false" in source
    assert "fetch-depth: 0" in source
    assert "id-token: write" not in source
    assert "attestations: write" not in source
    assert "pull_request_target" not in source
    assert "--real-model-report" not in source
    assert "opportunity-sample" in source
    assert "assert private[\"prediction_mode\"] == \"no_model_report\"" in source
    assert "assert not any(case[\"label\"] is not None" in source
    assert "assert \"unchanged_touched\" in strata" in source
    assert "assert \"unchanged_other\" in strata" in source
