"""R8.06c: GitHub workflow is advisory read-only and cannot leak full findings."""
from pathlib import Path

FILE=(Path(__file__).resolve().parents[1]/
      ".github/workflows/advisory-pr-pilot.yml")


def test_pr_workflow_uses_read_only_event_and_two_separate_source_checkouts():
    content=FILE.read_text()
    assert "pull_request:" in content
    assert "pull_request_target:" not in content
    assert "permissions:\n  contents: read\n  pull-requests: read" in content
    assert "id-token: write" not in content
    assert "attestations: write" not in content
    assert "issues: write" not in content
    assert "pull-requests: write" not in content
    assert "persist-credentials: false" in content
    assert content.count("persist-credentials: false")==2
    assert "ref: ${{ github.event.pull_request.base.sha }}" in content
    assert "ref: refs/pull/${{ github.event.pull_request.number }}/head" in content
    assert "path: daddy-tools" in content
    assert "path: pr-source" in content
    assert "pip install --constraint daddy-tools/" in content
    assert "-e './daddy-tools[verification]'" in content
    assert "-e ./pr-source" not in content
    assert "--root \"$GITHUB_WORKSPACE/pr-source\"" in content


def test_no_unsafe_posting_approvals_git_writes_or_model_execution():
    content=FILE.read_text()
    assert "pilot-pr" in content
    assert "--expected-head-sha \"$PILOT_HEAD\"" in content
    assert "GH_TOKEN: ${{ github.token }}" in content
    assert "pr-publish" not in content
    assert "--apply" not in content
    assert "gh api --method POST" not in content
    assert "git push" not in content
    assert "merge" not in content.split("Analyze exact PR SHA",1)[1].split(
        "- name: Verify source-free",1)[0]
    assert "actions/attest@" not in content


def test_private_evidence_not_ever_uploaded_in_artifact():
    content=FILE.read_text()
    upload=content.split("- name: Upload ONLY source-free advisory PR summary for operator",1)[1]
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in upload
    assert "daddy-pilot-public/summary.json" in upload
    assert "private" not in upload
    assert ".git" not in upload
    assert "review.json" not in upload
    assert "retention-days: 7" in upload
    assert "summary['" not in upload
