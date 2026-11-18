"""R8.05b: basic cross-workflow runner and checkout credential policy.

This is static least-privilege analysis, not proof of GitHub org-level default
permissions or hosted-runner isolation. The live API governance audit remains
a separate release gate.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def test_every_workflow_has_explicit_minimum_top_level_token_permissions():
    workflows = sorted(WORKFLOWS.glob("*.yml"))
    assert len(workflows) >= 8
    for file in workflows:
        body = file.read_text(encoding="utf-8")
        assert "permissions:\n" in body, file
        # The workflow_run observer additionally needs read-only Actions API.
        assert re.search(r"^permissions:\n(?:  [a-z-]+: (?:read|none)\n)+",
                         body, re.MULTILINE), file
        assert "permissions: write-all" not in body
        assert "pull_request_target" not in body
        assert "secrets." not in body
        assert re.search(r"^  contents: read$", body, re.MULTILINE), file


def test_every_job_runs_on_github_hosted_runner_not_self_hosted():
    for file in WORKFLOWS.glob("*.yml"):
        body = file.read_text(encoding="utf-8")
        runners = re.findall(r"^\s+runs-on:\s*(\S+)", body, re.MULTILINE)
        assert runners, file
        assert all(value == "ubuntu-latest" for value in runners), file
        assert "self-hosted" not in body, file


def test_every_checkout_refuses_persisted_credentials():
    for file in WORKFLOWS.glob("*.yml"):
        body = file.read_text(encoding="utf-8")
        count = len(re.findall(r"uses:\s+actions/checkout@[a-f0-9]{40}", body))
        disabled = len(re.findall(r"^\s+persist-credentials: false$",
                                  body, re.MULTILINE))
        assert disabled == count, (file, count, disabled)
        assert "persist-credentials: true" not in body, file


def test_main_ci_has_read_only_token_and_no_checkout_auth_header():
    body = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in body
    assert "persist-credentials: false" in body
    assert "test (3.10)" not in body  # Job names are generated from fixed matrix
    assert "matrix:\n        python-version: ['3.10', '3.12', '3.13']" in body


def test_code_owners_reserve_workflow_and_release_policy_changes():
    owners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert "* @cognetheus" in owners
    assert "/.github/workflows/ @cognetheus" in owners
    assert "/src/daddy_reviews/release_governance.py @cognetheus" in owners
    assert "/pyproject.toml @cognetheus" in owners
