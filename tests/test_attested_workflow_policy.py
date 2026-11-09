"""R8.04f: signing permissions never coexist with repository test execution.

A static regression guard supplements the real multi-job GitHub Actions test.
This does not replace workflow protection or immutable action SHA pinning.
"""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/attested-test-execution.yml")


def _section(content, name, next_name=None):
    header = "  " + name + ":\n"
    assert header in content
    block = content.split(header, 1)[1]
    if next_name:
        block = block.split("  " + next_name + ":\n", 1)[0]
    return block


def test_oidc_signer_job_has_no_repository_checkout_shell_install_or_python():
    text = WORKFLOW.read_text(encoding="utf-8")
    sign = _section(text, "sign-only", "verify-attested")
    assert "id-token: write" in sign
    assert "attestations: write" in sign
    assert "actions/download-artifact@v4" in sign
    assert "actions/attest@v4" in sign
    assert "actions/checkout" not in sign
    assert "actions/setup-python" not in sign
    assert "python" not in sign.lower()
    assert "run:" not in sign  # No shell commands in OIDC-capable job


def test_test_and_verify_jobs_have_no_oidc_or_write_permissions():
    text = WORKFLOW.read_text(encoding="utf-8")
    tests = _section(text, "run-fixed-suite", "sign-only")
    verify = _section(text, "verify-attested")
    assert "id-token:" not in tests
    assert "id-token:" not in verify
    assert "attestations: write" not in tests
    assert "attestations: write" not in verify
    assert "permissions:\n      contents: read" in tests
    assert "permissions:\n      contents: read" in verify
    assert "persist-credentials: false" in tests
    assert "persist-credentials: false" in verify
    assert "capture_fixed_ci_test" in tests
    assert "capture_fixed_ci_test" not in verify
    assert "verify_execution_with_github_attestation" in verify


def test_sign_and_verify_require_prior_completed_job_artifacts():
    text = WORKFLOW.read_text(encoding="utf-8")
    sign = _section(text, "sign-only", "verify-attested")
    verify = _section(text, "verify-attested")
    assert "needs: run-fixed-suite" in sign
    assert "needs: sign-only" in verify
    assert "name: daddy-supervised-record" in sign
    assert "name: daddy-supervised-record" in verify
    assert "Modified execution record must fail closed" in verify
