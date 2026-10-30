# R6 — Review quality, cost telemetry and shadow comparisons

R6 evaluates **independently labeled review findings**, model execution measurements and offline candidate-vs-baseline comparisons. It does not assert production review accuracy from synthetic fixtures.

## Human-labeled review dataset

Dataset format: `daddy-reviews-quality-v1`. Each case has a unique ID, a tier (`trivial`, `lite`, `full`), `label_status: human_verified`, and two arrays: `expected` (independently validated defects) and `observed` (reviewer predictions). Finding identity uses exact `path`, `line`, `rule`; severity is compared separately.

Labels must be validated by engineers outside the candidate model. Do not mark AI-generated labels as human verified. Include clean PRs, introduced bugs, refactors, sensitive trust-boundary changes, pre-existing problems, and disagreements. Sample and adjudicate cases across your actual stacks. For a real study, document repository/version, anonymization, label authority, inter-reviewer agreement, sample selection, and time period.

## Quality scoring

```bash
daddy-reviews quality-eval --dataset evals/quality_synthetic.json
```

Outputs per-tier and overall TP, FP, FN, precision, recall, F1, accuracy of severity **on matched findings**, and clean-case false-positive rate. Missing denominators return `null`, not misleading 100% confidence. The included synthetic fixture only verifies scoring logic and is not a real-world benchmark.

## Model telemetry

Opt-in `ai-review` records per-reviewer wall-clock duration. If the local Ollama response exposes real `prompt_eval_count` and `eval_count`, those become input and output token counts. Missing usage remains unknown. To summarize saved JSON results:

```bash
daddy-reviews telemetry --report-file reviewed-run.json \
  --input-usd-per-million 0 --output-usd-per-million 0
```

Provide actual applicable prices if calculating cloud/managed cost. Zero pricing is acceptable for measuring reported local tokens, **not** proof that machine time, power, GPUs or support are free. Outputs p50/p95 latency, failure counts, missing-usage count, tokens and estimated cost only when all token counts and both caller-supplied rates are present.

## Shadow/canary comparison (offline, non-deploying)

```bash
daddy-reviews quality-compare \
  --baseline-dataset evals/quality_synthetic.json \
  --candidate-dataset evals/quality_synthetic.json
```

Both candidate files must have exactly the same case IDs, tiers and human ground truth. The result reports precision/recall/clean-case false-positive deltas and regression alerts. Fewer than 20 cases, or missing denominators, produce an inconclusive verdict unless measurable regressions already exist. This is **not** live shadow traffic, deployment, or automatic model rollout.

## Release acceptance for a real pilot

Collect human-verified examples across multiple repositories and language stacks. Compare on identical samples and avoid tuning solely to the golden set. Track missed high-risk defects, false alarms per clean PR, reviewer disagreement, rerun duplicates, p95 latency and token/cost by tier. Keep all PR publication human-approved while measuring reviewer trust and error rates. Publish a release decision only with evidence and documented uncertainty.
