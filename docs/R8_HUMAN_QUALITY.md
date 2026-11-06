# R8.04d.03 — Offline human resolution evaluation and regression gates

This phase scores **human-attested resolution outcomes** against a separately labeled dataset. It distinguishes confirmed false alarms, confirmed missed defects, true positives, true negatives, unresolved cases, and human/AI conflicts. An unresolved known defect is counted separately from a confirmed miss, while coverage-adjusted recall uses *all* labeled defects in the denominator.

## Run

```bash
daddy-reviews human-resolution-eval \
  --resolution-dataset evals/human_resolution_synthetic.json > /tmp/human-score.json

daddy-reviews human-resolution-compare \
  --baseline-dataset evals/human_resolution_synthetic.json \
  --candidate-dataset evals/human_resolution_synthetic.json > /tmp/comparison.json
```

A paired comparison returns exit 2 when precision falls by more than 0.02, coverage-adjusted recall falls by more than 0.02, resolved coverage falls by more than 0.02, clean false-alarm rate increases by more than 0.02, confirmed miss rate increases by more than 0.02, or a new known defect becomes unresolved. Comparison requires an identical source/label corpus hash: unrelated cases cannot be compared meaningfully.

## Input contract

The dataset has `format: daddy-reviews-human-resolution-eval-v1`, `dataset_kind: synthetic|human_labeled`, and 1–200 bounded cases. Each case includes a unique ID, `candidate_id`, review tier, known label `defect|clean`, `snapshot_id`, `patch_sha256`, `label_metadata`, and the corresponding R8.04c `resolution` JSON object.

The evaluator requires a unique matching candidate in the human-resolution report, a matching source snapshot and patch hash, and for purportedly resolved candidates at least two distinct named human reviewers and two verified receipt counts. **These fields are replayed JSON and are not re-cryptographically verified in the evaluator.** For authenticity, use the R8.04c `human-verify` operator workflow on original signatures and test logs before preparing an evaluation corpus.

Label metadata includes `reviewer_id`, date, `protocol: independent-human-label-v1`, and `label_kind` matching the dataset kind. It is **self-declared**. The evaluator cannot prove independent human labels were collected or attest the source repository's real-world prevalence of bugs. No secure production rollout or PR block follows from these metrics.

## Metrics

- `precision`: confirmed true positives / all confirmed positive outcomes
- `resolved_recall`: confirmed true positives / (true positives + confirmed misses); intentionally excludes unresolved defects
- `coverage_adjusted_recall`: confirmed true positives / all labeled defects, including unresolved
- `clean_false_alarm_rate`: confirmed false positives / all labeled clean cases
- `confirmed_miss_rate`: confirmed missed defects / all labeled defects
- `resolution_coverage`: human-attested confirmed/rejected outcomes / all cases
- `unresolved_defects`, `human_conflicts`, `model_conflicts`, and counts by review tier

All denominators of zero yield JSON `null`, never fake 0% accuracy. Results always include `promotion_eligible: false`, `real_world_accuracy_claim: false`, `merge_action: none`, `github_publication: none`.

The included ten-case `evals/human_resolution_synthetic.json` corpus is intentionally synthetic, with three TPs, one FP, one confirmed miss, two TNs, and three unresolved cases. It establishes regression behavior only, not user-model accuracy.

## Required remaining real-world evidence

To evaluate empirical quality, construct a blinded, independently adjudicated corpus from genuine repositories and revisions; retain authenticated label reviewers and the original signed R8.04c artifacts; isolate any model used to make labels from the evaluated reviewer; compare equivalent held-out cases and review false-negative severity. Before claiming CI execution authenticity, implement GitHub artifact attestation / OIDC verification and chain-validation independently of the internal runner key. Neither is provided by this release.
