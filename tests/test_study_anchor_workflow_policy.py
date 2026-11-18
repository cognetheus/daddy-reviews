"""R8.04k workflow security: public digests only, no privileged workflow code."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/study-evidence-anchor.yml")


def test_manual_anchor_has_exact_public_digest_run_title():
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src
    assert "Daddy Study Anchor | ${{ inputs.kind }} | ${{ inputs.study_sha256 }} | ${{ inputs.payload_sha256 }}" in src
    assert "registration" in src and "reviewer" in src
    assert "^[a-f0-9]{64}$" in src
    assert "RUN_NAME" not in src
    assert '[[ "$STUDY" == "$PAYLOAD" ]]' not in src


def test_dedicated_anchor_has_no_repo_checkout_secrets_or_write_permissions():
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in src
    assert "    permissions:\n      contents: read" in src
    assert "id-token: write" not in src
    assert "attestations: write" not in src
    assert "actions/checkout" not in src
    assert "actions/setup-python" not in src
    assert "upload-artifact" not in src
    assert "pull_request_target" not in src
    assert "GH_TOKEN" not in src
    assert "secrets." not in src
    assert "github.event.inputs" not in src
    assert "gh api" not in src
    assert "curl " not in src
