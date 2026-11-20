"""R8.05d.04: local static release preflight never claims GitHub protections."""
from pathlib import Path

from daddy_reviews.ops_security import static_security_preflight

ROOT = Path(__file__).resolve().parents[1]


def test_current_repository_static_controls_pass_but_not_release_authority():
    report = static_security_preflight(ROOT)
    assert report["status"] == "local_static_security_checks_passed", report
    assert all(report["checks"].values())
    assert report["workflow_count"] >= 8
    assert report["live_github_branch_protection_verified"] is False
    assert report["upstream_action_identity_independently_verified"] is False
    assert report["runtime_secret_absence_proven"] is False
    assert report["release_authorized"] is False
    assert report["github_publication"] == report["merge_action"] == "none"


def test_missing_security_files_do_not_imply_approval(tmp_path):
    result = static_security_preflight(tmp_path)
    assert result["status"] == "local_static_security_checks_failed"
    assert result["failed_checks"]
    assert result["release_authorized"] is False


def test_mutable_action_and_signer_shell_detected(tmp_path):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    for index in range(8):
        body = (
            "name: source\non:\n  push:\n"
            "permissions:\n  contents: read\n"
            "jobs:\n  test:\n    runs-on: ubuntu-latest\n"
        )
        if index == 0:
            body += (
                "    permissions:\n      id-token: write\n"
                "      contents: read\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - run: echo 'unsafe'\n"
            )
        (workflows / f"run{index}.yml").write_text(body)
    report = static_security_preflight(tmp_path)
    assert report["checks"]["sha_pinned_official_actions"] is False
    assert report["checks"]["oidc_signers_contain_only_actions"] is False
    assert report["status"] == "local_static_security_checks_failed"
    assert report["release_authorized"] is False


def test_symlinked_input_cannot_be_used_as_static_policy(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/CODEOWNERS").symlink_to(ROOT / ".github/CODEOWNERS")
    report = static_security_preflight(tmp_path)
    assert report["checks"]["codeowners_declared"] is False
    assert not report["release_authorized"]
