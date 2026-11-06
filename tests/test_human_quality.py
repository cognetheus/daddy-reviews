"""R8.04d.03 offline human-resolution scoring and paired regression gates."""
import copy
import json
from pathlib import Path

import pytest

from daddy_reviews.cli import main
from daddy_reviews.human_quality import (
    HumanQualityError, compare_human_resolutions, evaluate_human_resolutions,
    read_resolution_dataset, validate_resolution_dataset,
)

CORPUS = Path(__file__).resolve().parents[1] / "evals/human_resolution_synthetic.json"


def sample():
    return read_resolution_dataset(CORPUS)


def test_synthetic_corpus_scores_all_outcomes_without_promoting():
    score = evaluate_human_resolutions(sample())
    assert score["dataset_kind"] == "synthetic"
    assert score["case_count"] == 10
    metrics = score["metrics"]
    assert {k: metrics[k] for k in ("tp","fp","fn","tn","abstained")} == {
        "tp": 3, "fp": 1, "fn": 1, "tn": 2, "abstained": 3}
    assert metrics["human_conflicts"] == metrics["model_conflicts"] == 1
    assert metrics["unresolved_defects"] == 2
    assert metrics["coverage_adjusted_recall"] == 0.5
    assert metrics["clean_false_alarm_rate"] == 0.25
    assert metrics["resolution_coverage"] == 0.7
    assert score["promotion_eligible"] is False
    assert score["real_world_accuracy_claim"] is False
    assert score["github_publication"] == score["merge_action"] == "none"


def test_stable_scoring_and_equal_corpora_never_claim_quality_gate():
    corpus = sample()
    a = evaluate_human_resolutions(corpus)
    b = evaluate_human_resolutions(copy.deepcopy(corpus))
    assert a == b
    comparison = compare_human_resolutions(corpus, corpus)
    assert comparison["status"] == "insufficient_evidence"
    assert comparison["promotion_eligible"] is False
    assert comparison["corpus_sha256"] == a["corpus_sha256"]


def test_new_false_alarm_is_a_regression():
    baseline = sample()
    candidate = copy.deepcopy(baseline)
    case = next(c for c in candidate["cases"] if c["id"] == "s05-correct-rejection")
    case["resolution"]["decisions"][0]["status"] = "human_attested_confirmed"
    result = compare_human_resolutions(baseline, candidate)
    assert result["status"] == "regression"
    assert result["changes"]["clean_false_alarm_rate"] == 0.25
    assert result["changes"]["precision"] < 0


def test_new_unresolved_defect_is_a_regression():
    baseline = sample()
    candidate = copy.deepcopy(baseline)
    case = next(c for c in candidate["cases"] if c["id"] == "s01-confirmed-defect")
    case["resolution"]["decisions"][0]["status"] = "awaiting_human_verification"
    result = compare_human_resolutions(baseline, candidate)
    assert result["status"] == "regression"
    assert result["new_unresolved_defects"] == 1
    assert result["changes"]["resolution_coverage"] < 0


def test_ground_truth_and_source_identity_mismatch_cannot_be_compared():
    original = sample()
    for key, value in (("label", "clean"), ("snapshot_id", "unrelated")):
        altered = copy.deepcopy(original)
        altered["cases"][0][key] = value
        if key == "snapshot_id":
            altered["cases"][0]["resolution"]["snapshot_id"] = value
        with pytest.raises(HumanQualityError):
            compare_human_resolutions(original, altered)


def test_inconsistent_case_or_invalid_trusted_claim_fails():
    original = sample()
    for update in (
        lambda c: c["cases"].append(copy.deepcopy(c["cases"][0])),
        lambda c: c["cases"][0].pop("label_metadata"),
        lambda c: c["cases"][0]["resolution"]["decisions"][0].update(
            verified_human_receipts=1),
        lambda c: c["cases"][0]["resolution"]["decisions"][0].update(
            status="model_authorized_merge"),
        lambda c: c["cases"][0]["resolution"].update(
            patch_sha256="0" * 64),
        lambda c: c["cases"][0]["label_metadata"].update(
            label_kind="unverified"),
    ):
        bad = copy.deepcopy(original)
        update(bad)
        with pytest.raises(HumanQualityError):
            validate_resolution_dataset(bad)


def test_human_labeled_self_declared_data_does_not_grant_promotion():
    dataset = sample()
    dataset["dataset_kind"] = "human_labeled"
    for item in dataset["cases"]:
        item["label_metadata"]["label_kind"] = "human_labeled"
    score = evaluate_human_resolutions(dataset)
    assert score["status"] == "evaluation_only"
    assert score["label_authentication"] == "self_declared_not_cryptographically_attested"
    assert not score["real_world_accuracy_claim"]
    comparison = compare_human_resolutions(dataset, dataset)
    assert comparison["status"] == "insufficient_evidence"
    assert not comparison["promotion_eligible"]


def test_cli_evaluate_compare_and_regression_exit(tmp_path, capsys):
    baseline = tmp_path / "base.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(sample()))
    candidate.write_text(json.dumps(sample()))
    main(["human-resolution-eval", "--resolution-dataset", str(baseline)])
    assert json.loads(capsys.readouterr().out)["metrics"]["tp"] == 3
    main(["human-resolution-compare", "--baseline-dataset", str(baseline),
          "--candidate-dataset", str(candidate)])
    assert json.loads(capsys.readouterr().out)["status"] == "insufficient_evidence"
    corrupted = sample()
    next(c for c in corrupted["cases"] if c["id"] == "s05-correct-rejection")[
        "resolution"]["decisions"][0]["status"] = "human_attested_confirmed"
    candidate.write_text(json.dumps(corrupted))
    with pytest.raises(SystemExit) as code:
        main(["human-resolution-compare", "--baseline-dataset", str(baseline),
              "--candidate-dataset", str(candidate)])
    assert code.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "regression"
