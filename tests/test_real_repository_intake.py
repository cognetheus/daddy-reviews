"""R8.04h actual local Git-object sampling; tests never invent real defect labels."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from daddy_reviews import cli
from daddy_reviews.real_repository_intake import (
    RealIntakeError, build_real_repository_intake, write_real_intake_files,
)


def run(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True)
    return result.stdout.strip()


def git_source(tmp_path):
    root = tmp_path / "actual-repo"
    root.mkdir()
    run(root, "init", "-q")
    (root / "src").mkdir()
    path = root / "src" / "check.py"
    path.write_text("def allow(user):\n    return user is not None\n", encoding="utf-8")
    run(root, "add", "src/check.py")
    run(root, "-c", "user.name=Real Intake Test",
        "-c", "user.email=sample@example.invalid",
        "commit", "-qm", "baseline from genuine git objects")
    base = run(root, "rev-parse", "HEAD")
    path.write_text(
        "def allow(user):\n"
        "    if user is None:\n"
        "        return False\n"
        "    if user == 'admin':\n"
        "        return True\n"
        "    return bool(user)\n",
        encoding="utf-8")
    run(root, "add", "src/check.py")
    run(root, "-c", "user.name=Real Intake Test",
        "-c", "user.email=sample@example.invalid",
        "commit", "-qm", "introduce additional changed source lines")
    head = run(root, "rev-parse", "HEAD")
    return root, base, head


def build(root, base, head, **options):
    return build_real_repository_intake(
        root,repository="example/real-repo",repository_id=912345,
        base_commit=base,head_commit=head,seed="independent-lab-seed-2026",
        max_cases=5,**options)


def model_report(root, base, head):
    patch = subprocess.run(
        ["git", "-C", str(root), "diff", "--no-ext-diff", "--no-textconv",
         "--unified=0", base, head, "--"], capture_output=True, check=True).stdout
    digest = hashlib.sha256((root / "src/check.py").read_bytes()).hexdigest()
    # The report is a structurally valid *model hypothesis*, NOT ground truth.
    finding = {
        "path": "src/check.py", "line": 3, "rule": "SAMPLE-RULE",
        "reviewer": "security", "claim": "Hypothesis at a changed line",
        "evidence": "Review needed", "severity": "medium",
        "verification": "unverified", "changed": True,
        "source_evidence": [
            {"id": "E1", "source": {
                "snapshot_id": "test-source-snapshot",
                "path": "src/check.py", "start_line": 3, "end_line": 3,
                "source_sha256": digest}}
        ],
        "citations": ["E1"],
    }
    return {
        "format": "daddy-reviews-agent-investigation-v1",
        "status": "complete", "snapshot_id": "test-source-snapshot",
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "reviewer_runs": [{"reviewer": "security", "status": "completed"}],
        "model_findings": [finding],
    }


def test_real_git_objects_are_sampled_deterministically_with_unflagged_reserve(tmp_path):
    root, base, head = git_source(tmp_path)
    report = model_report(root, base, head)
    first = build(root, base, head, report=report)
    second = build(root, base, head, report=report)
    assert first == second
    assert first["status"] == "real_source_intake_not_ground_truth"
    assert first["source_provenance"].startswith("pinned_local_git_objects")
    assert first["labels_authenticated"] is False
    assert first["empirical_accuracy_claim"] is False
    assert first["promotion_eligible"] is False
    blind = first["blind_packet"]
    ledger = first["private_ledger"]
    assert len(blind["cases"]) == ledger["population"]["sampled"]
    assert ledger["population"]["sampled_unflagged"] >= 1
    assert ledger["population"]["sampled_flagged"] >= 1
    assert ledger["prediction_mode"] == "completed_model_report"
    assert blind["model_predictions_included"] is False
    assert "model_rules" not in json.dumps(blind)
    assert "SAMPLE-RULE" not in json.dumps(blind)
    assert any(item["model_flagged"] for item in ledger["cases"])
    assert any(not item["model_flagged"] for item in ledger["cases"])
    assert all(item["label"] is None for item in blind["cases"])
    assert blind["head_commit"] == head


def test_missing_model_output_cannot_claim_clean_or_detected_accuracy(tmp_path):
    root, base, head = git_source(tmp_path)
    result = build(root, base, head)
    ledger = result["private_ledger"]
    assert ledger["prediction_mode"] == "no_model_report"
    assert ledger["population"]["sampled_flagged"] == 0
    assert ledger["population"]["sampled_unflagged"] > 0
    assert result["empirical_accuracy_claim"] is False
    assert not ledger["score_release_authorized"]


def test_pinned_git_source_mutations_and_invalid_predictions_fail_closed(tmp_path):
    root, base, head = git_source(tmp_path)
    with pytest.raises(RealIntakeError):
        build(root, base, "a" * 40)
    with pytest.raises(RealIntakeError):
        build(root, head, base)
    report = model_report(root, base, head)
    report["patch_sha256"] = "a" * 64
    with pytest.raises(RealIntakeError):
        build(root, base, head, report=report)
    report = model_report(root, base, head)
    report["model_findings"][0]["line"] = 999
    with pytest.raises(RealIntakeError):
        build(root, base, head, report=report)


def test_ledger_and_blind_outputs_are_separate_owner_only_and_no_overwrite(tmp_path):
    root, base, head = git_source(tmp_path)
    intake = build(root, base, head, report=model_report(root, base, head))
    folder = tmp_path / "private-outputs"
    folder.mkdir(mode=0o700)
    blind = folder / "blind.json"
    ledger = folder / "model-ledger.json"
    summary = write_real_intake_files(intake, blind, ledger)
    assert summary["status"] == "operator_case_packets_created"
    assert summary["population"]["sampled_unflagged"] >= 1
    assert not summary["accuracy_measured"]
    assert summary["github_publication"] == summary["merge_action"] == "none"
    assert not blind.stat().st_mode & 0o077
    assert not ledger.stat().st_mode & 0o077
    assert "model_rules" not in blind.read_text()
    assert "model_rules" in ledger.read_text()
    with pytest.raises(RealIntakeError):
        write_real_intake_files(intake, blind, ledger)
    with pytest.raises(RealIntakeError):
        write_real_intake_files(intake, folder / "same.json", folder / "same.json")


def test_symlinked_output_directory_fails_closed(tmp_path):
    root, base, head = git_source(tmp_path)
    intake = build(root, base, head)
    folder = tmp_path / "private"
    folder.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(RealIntakeError):
        write_real_intake_files(intake, link / "blind.json", folder / "ledger.json")


def test_operator_cli_writes_real_cases_and_only_summary_to_stdout(tmp_path, capsys):
    root, base, head = git_source(tmp_path)
    output = tmp_path / "intake"
    output.mkdir(mode=0o700)
    cli.main([
        "real-sample", "--root", str(root), "--base", base, "--head", head,
        "--attestation-repo", "example/real-repo",
        "--attestation-repo-id", "912345",
        "--real-sample-seed", "independent-lab-seed-2026",
        "--real-sample-max-cases", "5",
        "--real-blind-output", str(output / "blind.json"),
        "--real-private-output", str(output / "private.json"),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "operator_case_packets_created"
    assert not summary["accuracy_measured"]
    assert "source_line_untrusted" not in json.dumps(summary)
    assert "source_line_untrusted" in (output / "blind.json").read_text()
    assert "model_flagged" in (output / "private.json").read_text()


def test_changed_worktree_cannot_silently_replace_pinned_git_object(tmp_path):
    root, base, head = git_source(tmp_path)
    changed = root / "src/check.py"
    changed.write_text("MALICIOUS WORKTREE (not committed)\n")
    sampled = build(root, base, head)
    assert all("MALICIOUS" not in c["source_line_untrusted"]
               for c in sampled["blind_packet"]["cases"])
    assert sampled["blind_packet"]["head_commit"] == head
