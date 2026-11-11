"""R8.04j regression guard for honest, non-publishing study preview."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/study-preregistration-preview.yml")


def test_ci_exports_unsigned_plan_only_never_model_predictions_or_evidence():
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Publish only UNSIGNED source plan and safe summary for registrar handoff"
    assert marker in source
    earlier, publication = source.split(marker, 1)
    assert "actions/upload-artifact" not in earlier
    assert "actions/upload-artifact@v4" in publication
    assert "name: daddy-unsigned-study-plan-preview" in publication
    assert "/tmp/daddy-study-preview/plan.json" in publication
    assert "/tmp/daddy-study-preview/summary.json" in publication
    assert "/tmp/daddy-study-preview/private.json" not in publication
    assert "/tmp/daddy-study-preview/blind.json" not in publication
    assert "retention-days: 7" in publication
    assert "registration_signed'] is False" in earlier
    assert "chronology_independently_proven'] is False" in earlier


def test_study_preview_has_no_signing_or_github_write_permissions():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in source
    assert "id-token: write" not in source
    assert "attestations: write" not in source
    assert "actions/attest" not in source
    assert "pull_request_target" not in source
    assert "persist-credentials: false" in source
    assert "fetch-depth: 0" in source
    assert "study-plan" in source
    assert "study-audit" not in source  # no synthetic labels posing as human findings
    assert "gh api" not in source
