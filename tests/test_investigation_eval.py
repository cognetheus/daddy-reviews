"""R8.03: replay real investigation tools from scripted model decisions."""
import copy
import json
from pathlib import Path

import pytest

from daddy_reviews.investigation_eval import (
    FORMAT, RESULT_FORMAT, ReplayError, compare_replay, evaluate_replay,
    read_replay_dataset, validate_replay_dataset,
)

SYNTHETIC = Path(__file__).resolve().parents[1] / "evals/investigation_replay_synthetic.json"


def load():
    return read_replay_dataset(SYNTHETIC)


def small(case_id="synthetic-matched-defect"):
    data = load()
    data["cases"] = [next(c for c in data["cases"] if c["id"] == case_id)]
    return data


def test_synthetic_replay_runs_real_tools_and_scores_failure_modes():
    result = evaluate_replay(load())
    assert result["format"] == RESULT_FORMAT
    assert result["dataset_kind"] == "synthetic"
    assert result["case_count"] == 10
    assert result["status"] == "evaluated"
    assert result["cases_with_unexpected_execution"] == 0
    metrics = result["metrics_by_tier"]["all"]
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (2, 2, 1)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.6667
    assert metrics["incomplete"] == 4
    assert metrics["clean_flagged"] == 1
    assert result["production_model_quality_claim"] is False
    assert result["performance"]["reported_input_tokens"] is None
    assert result["performance"]["estimated_cost_usd"] is None


def test_replay_is_reproducible_for_a_fixed_fixture():
    data = small()
    first = evaluate_replay(data)
    second = evaluate_replay(data)
    assert first["fixture_set_sha256"] == second["fixture_set_sha256"]
    assert first["cases"][0]["trace_sha256"] == second["cases"][0]["trace_sha256"]
    assert first["cases"][0]["replayed_tool_results"] == second["cases"][0]["replayed_tool_results"]
    assert first["cases"][0]["tp"] == 1
    assert first["cases"][0]["script_fully_consumed"] is True
    assert len(first["cases"][0]["replayed_tool_results"]["security"]) == 1
    result = first["cases"][0]["replayed_tool_results"]["security"][0]
    assert result["issued_evidence_count"] == 1
    assert len(result["response_sha256"]) == 64


def test_duplicate_agent_findings_do_not_disappear_from_fp_count():
    result = evaluate_replay(small("synthetic-parallel-duplicate"))
    case = result["cases"][0]
    assert case["tp"] == 1
    assert case["fp"] == 1
    assert case["observed_count"] == 2
    assert result["metrics_by_tier"]["all"]["precision"] == 0.5


def test_failed_tool_call_is_not_scored_as_false_clean_review():
    result = evaluate_replay(small("synthetic-permission-denial"))
    case = result["cases"][0]
    assert case["status"] == "incomplete"
    assert case["expectation_met"] is True
    assert case["tool_failures"] == 1
    assert case["script_fully_consumed"] is True
    assert result["metrics_by_tier"]["all"]["incomplete_rate"] == 1


def test_missing_defect_is_fn_and_synthetic_fp_is_exposed():
    missed = evaluate_replay(small("synthetic-missed-defect"))
    assert missed["cases"][0]["fn"] == 1
    assert missed["cases"][0]["tp"] == 0
    false_positive = evaluate_replay(small("synthetic-false-positive"))
    assert false_positive["cases"][0]["fp"] == 1
    assert false_positive["metrics_by_tier"]["all"]["clean_case_false_positive_rate"] == 1


def test_transport_error_and_citation_forgery_remain_explicit_incomplete():
    for case in ("synthetic-provider-timeout", "synthetic-invalid-citation",
                 "synthetic-tool-missing-file"):
        result = evaluate_replay(small(case))
        assert result["status"] == "evaluated"
        assert result["cases"][0]["status"] == "incomplete"
        assert result["cases"][0]["observed_count"] == 0


def test_invalid_model_turn_consumption_is_contract_failure_not_success():
    data = small()
    data["cases"][0]["reviewers"][0]["turns"].append(
        {"kind": "final", "findings": []}
    )
    report = evaluate_replay(data)
    assert report["status"] == "contract_failed"
    assert report["cases_with_unexpected_execution"] == 1


def test_replay_rejects_source_traversal_and_untracked_diff():
    data = small()
    data["cases"][0]["files"]["../private.py"] = "danger = 1\n"
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)
    data = small()
    data["cases"][0]["files"].pop("src/auth.py")
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)


def test_duplicate_expected_labels_and_unsupported_ground_truth_are_invalid():
    data = small()
    data["cases"][0]["expected"].append(data["cases"][0]["expected"][0].copy())
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)
    data = small()
    data["cases"][0]["expected"][0]["line"] = 250
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)


def test_fake_human_verified_labels_rejected_without_review_provenance():
    data = small()
    data["dataset_kind"] = "human_labeled"
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)
    data["cases"][0]["label_status"] = "human_verified"
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)
    data["cases"][0]["label_metadata"] = {
        "reviewer_id": "reviewer-23", "reviewed_at": "2026-11-04",
        "protocol": "human-adjudicated-v1",
    }
    validate_replay_dataset(data)
    # Provenance is self-declared. The harness never independently authenticates the reviewer.


def test_comparison_abstains_from_quality_promotion_on_synthetic():
    baseline = evaluate_replay(load())
    compared = compare_replay(baseline, baseline)
    assert compared["format"] == "daddy-reviews-investigation-replay-compare-v1"
    assert compared["status"] == "insufficient_evidence"
    assert compared["promotion_eligible"] is False
    assert compared["regression_flags"] == []


def test_regression_comparison_flags_new_false_positive():
    baseline_dataset = small("synthetic-clean-skip-tools")
    candidate_dataset = copy.deepcopy(baseline_dataset)
    # Change only the model's observed decision, not the source or ground truth.
    final = candidate_dataset["cases"][0]["reviewers"][0]["turns"][0]
    final["findings"] = [{
        "rule": "FAKE", "path": "src/config.py", "line": 1,
        "claim": "A guess", "evidence": "No real evidence", "severity": "low",
        "citations": ["E1"],
    }]
    # Uncited finding correctly fails. Compare flags the new incomplete case.
    before = evaluate_replay(baseline_dataset)
    after = evaluate_replay(candidate_dataset)
    assert before["fixture_set_sha256"] == after["fixture_set_sha256"]
    assert after["cases"][0]["status"] == "incomplete"
    assert after["status"] == "contract_failed"
    result = compare_replay(before, after)
    assert result["status"] == "regression"
    assert "new_incomplete_cases" in result["regression_flags"]


def test_comparison_rejects_mismatched_ground_truth():
    baseline = evaluate_replay(small("synthetic-matched-defect"))
    other = evaluate_replay(small("synthetic-clean-skip-tools"))
    with pytest.raises(ReplayError):
        compare_replay(baseline, other)


def test_validate_dataset_requires_finite_bounded_json():
    data = small()
    data["cases"][0]["reviewers"][0]["turns"][0]["limit"] = float("nan")
    with pytest.raises(ValueError):
        validate_replay_dataset(data)
    data = small()
    data["cases"][0]["reviewers"][0]["turns"][0]["huge"] = "x" * 40_000
    with pytest.raises(ReplayError):
        validate_replay_dataset(data)


def test_replay_dataset_parser_blocks_symlinks_and_broken_json(tmp_path):
    data = tmp_path / "data.json"
    data.write_text("{oops", encoding="utf-8")
    with pytest.raises(ReplayError):
        read_replay_dataset(data)
    data.write_text(json.dumps(load()), encoding="utf-8")
    alias = tmp_path / "link.json"
    alias.symlink_to(data)
    with pytest.raises(ReplayError):
        read_replay_dataset(alias)


def test_unrecorded_model_call_is_fail_closed(tmp_path):
    dataset = small("synthetic-matched-defect")
    dataset["cases"][0]["reviewers"][0]["turns"] = [
        dataset["cases"][0]["reviewers"][0]["turns"][0]
    ]
    report = evaluate_replay(dataset)
    assert report["status"] == "contract_failed"
    assert report["cases"][0]["status"] == "incomplete"
    assert report["cases"][0]["fn"] == 1


def test_replay_source_is_data_and_cannot_trigger_shell_code():
    result = evaluate_replay(small("synthetic-untrusted-source"))
    assert result["status"] == "evaluated"
    assert result["cases"][0]["observed_count"] == 0
    assert result["cases"][0]["status"] == "complete"


def test_cli_replay_eval_and_comparison_smoke(capsys, tmp_path):
    from daddy_reviews.cli import main

    main(["investigation-replay", "--replay-dataset", str(SYNTHETIC)])
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "evaluated"
    assert report["case_count"] == 10
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(report))
    main(["investigation-compare", "--baseline-replay", str(baseline),
          "--candidate-replay", str(baseline)])
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["status"] == "insufficient_evidence"
    assert comparison["promotion_eligible"] is False


def test_cli_replay_regression_exits_nonzero_but_prints_json(tmp_path, capsys):
    from daddy_reviews.cli import main

    before = evaluate_replay(small("synthetic-clean-skip-tools"))
    candidate = small("synthetic-clean-skip-tools")
    candidate["cases"][0]["reviewers"][0]["turns"][0]["findings"] = [{
        "rule": "UNVERIFIED", "path": "src/config.py", "line": 1,
        "claim": "Speculation", "evidence": "No real tool evidence",
        "severity": "low", "citations": ["E1"],
    }]
    after = evaluate_replay(candidate)
    first, second = tmp_path / "before.json", tmp_path / "after.json"
    first.write_text(json.dumps(before))
    second.write_text(json.dumps(after))
    with pytest.raises(SystemExit) as e:
        main(["investigation-compare", "--baseline-replay", str(first),
              "--candidate-replay", str(second)])
    assert e.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "regression"


def test_cli_reports_missing_or_invalid_replay_file_as_usage_error(capsys, tmp_path):
    from daddy_reviews.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["investigation-replay", "--replay-dataset", str(tmp_path / "missing.json")])
    assert exc.value.code == 2
