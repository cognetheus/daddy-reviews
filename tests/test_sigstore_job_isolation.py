"""R8.05b: prevent privilege regression in both genuine Sigstore workflows."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / ".github/workflows/attestation-integration.yml"


def _job(text, name, until=None):
    header = f"  {name}:\n"
    assert header in text
    block = text.split(header, 1)[1]
    if until:
        block = block.split(f"  {until}:\n", 1)[0]
    return block


def test_sigstore_fixture_job_cannot_request_oidc_or_write_access():
    workflow = LEGACY.read_text(encoding="utf-8")
    prepare = _job(workflow, "prepare-artifact", "sign-only")
    assert "runs-on: ubuntu-latest" in prepare
    assert "permissions:\n      contents: read" in prepare
    assert "id-token: write" not in prepare
    assert "attestations: write" not in prepare
    assert "persist-credentials: false" in prepare
    assert "Run local policy contract tests without signing access" in prepare
    assert "Upload bounded unprivileged provenance fixture" in prepare
    assert "actions/upload-artifact@" in prepare


def test_sigstore_oidc_job_executes_only_pinned_download_and_attest_actions():
    workflow = LEGACY.read_text(encoding="utf-8")
    sign = _job(workflow, "sign-only", "verify-genuine-github-attestation")
    assert "needs: prepare-artifact" in sign
    assert "runs-on: ubuntu-latest" in sign
    assert "id-token: write" in sign and "attestations: write" in sign
    active = "\n".join(x for x in sign.splitlines()
                       if not x.strip().startswith("#"))
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in active
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in active
    assert "actions/checkout@" not in active
    assert "actions/setup-python@" not in active
    assert re.search(r"^\s+run:", active, re.MULTILINE) is None
    assert re.search(r"^\s+env:", active, re.MULTILINE) is None
    assert "subject-path: /tmp/daddy-sigstore/fixture.log" in active


def test_sigstore_verify_job_can_read_attestations_but_never_sign():
    workflow = LEGACY.read_text(encoding="utf-8")
    verify = _job(workflow, "verify-genuine-github-attestation")
    assert "needs: sign-only" in verify
    assert "permissions:\n      contents: read\n      attestations: read" in verify
    assert "id-token: write" not in verify
    assert "attestations: write" not in verify
    assert "persist-credentials: false" in verify
    assert "Download signed source fixture" in verify
    assert "Download signed bundle and TUF trusted root" in verify
    assert "Verify real signed bundle offline through Daddy Reviews" in verify
    assert "Prove tampered artifact fails verification" in verify
    assert "test -z" in verify


def test_signing_permissions_occur_only_in_isolated_signer_job():
    workflow = LEGACY.read_text(encoding="utf-8")
    assert workflow.count("id-token: write") == 1
    assert workflow.count("attestations: write") == 1
    assert "pull_request_target" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "name: daddy-sigstore-fixture" in workflow
    assert workflow.count("name: daddy-sigstore-fixture") == 3
    assert "retention-days: 1" in workflow
