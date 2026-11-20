"""R8.05d: no privileged writes, source leaks or release self-approval in ops CI."""
from pathlib import Path

FILE = (Path(__file__).resolve().parents[1] /
        ".github/workflows/operational-readiness-preview.yml")


def test_real_source_ops_workflow_is_read_only_and_does_not_publish_source():
    text = FILE.read_text(encoding="utf-8")
    marker = "      - name: Upload ONLY source-free local candidate operational summary and blocked release report"
    assert marker in text
    before, after = text.split(marker, 1)
    assert "actions/upload-artifact" not in before
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in after
    assert "name: daddy-ops-local-readiness-preview" in after
    assert "/tmp/daddy-operational/summary.json" in after
    assert "/tmp/daddy-operational/acceptance.json" in after
    assert "retention-days: 7" in after
    assert "private" not in after
    assert ".env" not in after
    assert "src/" not in after
    assert "secrets." not in text
    assert "pull_request_target" not in text
    assert "permissions:\n  contents: read" in text
    assert "id-token: write" not in text
    assert "attestations: write" not in text
    assert "persist-credentials: false" in text
    assert "fetch-depth: 0" in text


def test_release_remains_nonzero_even_when_local_probes_pass():
    text = FILE.read_text(encoding="utf-8")
    assert "ops-preflight" in text
    assert "tests/test_ops_recovery.py" in text
    assert "result['fault_injection']['scenario_count']==5" in text
    assert "ops-readiness" in text
    assert "if python -m daddy_reviews.cli ops-readiness" in text
    assert "Unsafe: local evidence authorized production" in text
    assert "result['release_authorized'] is False" in text
    assert "result['production_ready'] is False" in text
    assert "result['external_human_defect_truth_proven'] is False" in text
    assert "result['github_branch_protection_proven'] is False" in text
