# R8.03 — Deterministic investigation replay, evaluation and regression gates

R8.03 adds **offline model-turn replay over real read-only R8.01 tools** and quality measurement for the R8.02 specialist investigation harness. Each case materializes a bounded source fixture in an isolated temporary directory. Only the *model's JSON decisions* are scripted: tool calls still run through `InvestigationSession` and must pass source snapshots, permission checks and host-issued citation verification. **No model inference, source execution, GitHub publication, or external API is performed by replay.**

## Run

```bash
# Evaluate 10 deliberately synthetic scenarios (not real model accuracy)
daddy-reviews investigation-replay \
  --replay-dataset evals/investigation_replay_synthetic.json \
  > /tmp/r8-baseline.json

# Re-run identical fixtures; stable trace digests provide reproducibility evidence
daddy-reviews investigation-replay \
  --replay-dataset evals/investigation_replay_synthetic.json \
  > /tmp/r8-candidate.json

# Paired regression comparison; fails with exit 2 on a detected regression
daddy-reviews investigation-compare \
  --baseline-replay /tmp/r8-baseline.json \
  --candidate-replay /tmp/r8-candidate.json \
  --min-replay-cases 20
```

### Versioned input contract

Dataset `format: daddy-reviews-investigation-replay-v1`, with `dataset_kind: synthetic` or `human_labeled`, and 1–200 unique `cases`. Every case defines an ID, declared review tier, bounded repository-relative `files` mapping, actual unified `patch`, explicit `expected` defect labels (`path`, changed `line`, `rule`, `severity`), an `expected_status`, an explicit `allowed_tools` list and 1–6 scripted specialists.

Specialist `turns` contain the **same JSON model actions** accepted by R8.02: `kind: tool` with one typed `call`, or `kind: final` with findings and host-issued citations. A third test-only `kind: transport_error` simulates `TimeoutError`, `ConnectionError` or `OSError` without using network traffic. R8.01 responses are never loaded from fixture JSON or blindly trusted. Each replay source tree is thrown away after the case.

Human-label inputs also require per-case `label_metadata` (`reviewer_id`, ISO `reviewed_at` date, `protocol: human-adjudicated-v1`). **This metadata is self-declared, not cryptographically authenticated.** The included ten cases have `dataset_kind: synthetic` and `label_status: synthetic` and cannot support an assertion of human-verified real-world accuracy.

## Scoring

| Measure | Semantics |
| --- | --- |
| TP / FP / FN | Exact changed-file path + added line + defect rule identity |
| Precision, recall, F1 | Aggregated over case predictions; undefined denominators reported as `null` |
| Severity accuracy | Exact severity agreement on matched findings |
| Clean-case false-positive rate | Clean labeled cases with one or more false alarms / all clean labeled cases |
| Incomplete rate | Cases with a failed/denied tool, bad citation, provider error or uncompleted turns / all cases |
| Tool and model efficiency | Actual harness tool calls, scripted model turns, averages per case |
| Investigation latency | Locally measured time for fixture tool execution; **no actual model inference latency** |
| Token/cost metrics | `null` in synthetic replay; never assume a missing measurement equals zero |

Multiple identical predicted issues count as **one TP plus duplicate FPs** rather than disappearing through deduplication. A failed investigation that misses a known defect contributes an FN to coverage-adjusted recall, while incompleteness is separately reported. A completed empty review is not declared defect-free; source citations establish provenance, not truth of a causal claim.

### Deterministic replay evidence

Each case includes `trace_sha256` computed over stable snapshot identity, patch hash, specialist status/reason, tool request audit, host source citations, findings and replayed tool-response hashes. Volatile runtime latency is excluded so equivalent replays have matching trace digests. Full reviewer source text and model prompts are **not persisted in the result**. This digest detects mismatch, but is neither a cryptographic signature nor a trusted attestation of model quality.

### Comparative regression policy

`investigation-compare` requires the same fixture-set hash, case IDs, dataset kind and source/label definition. It recomputes and validates aggregate metrics from case outcomes rather than trusting an edited scorecard. It flags a precision drop greater than 0.02, recall drop greater than 0.02, incomplete-rate increase greater than 0.02, newly incomplete cases, or an unexpectedly failed replay contract. Regression => `status: regression`, exit 2.

Stable synthetic fixtures always yield `status: insufficient_evidence` with `promotion_eligible: false`, **even with perfect-looking scores**. Human-labeled corpora need at least 20 cases (configurable via `--min-replay-cases`) and no observed regressions before *eligible for further human quality review*. That status does not authorize automated merge blocking, GitHub publication, or model rollout.

## Security and failure cases

- Strict 2 MB dataset limit, 200 cases, 20 source files per case, 200 KB source per fixture, 24 KB patch, 5 turns and limited tool grants. Invalid or escaping paths are rejected before materializing files.
- Symlinked dataset/report paths are rejected. No `.git`, build scripts or executable fixture files are accepted as direct source paths; reviewed source is data, never imported/executed.
- Replay uses actual R8.02 worktree/added-line consistency checks, R8.01 tool capability allowlists and host source-span validation, not canned trust in model output.
- Explicit scenarios include true defect hypotheses, clean code, false positives, missed defects, denied tools, unavailable files, unknown citations, model timeout, malicious source text and duplicate reviewer findings.
- A model transcript that does not match the actual tool message sequence fails closed. Unconsumed model turns or unexpected completion yield `status: contract_failed` rather than a clean benchmark.
- Baseline/candidate report comparison is schema and count-checked but self-reported fixture source and human metadata are not independently authenticated. Do not compare unrelated corpora.

## Verification and next milestone

`tests/test_investigation_eval.py` covers deterministic repeated traces, real-tool evidence responses, TP/FP/FN including duplicates, failure coverage, malicious fixtures, malformed and symlinked inputs, comparison of unchanged fixtures, new incomplete investigations, real precision regression and tampered report detection. The CI matrix runs the suite on Python 3.10, 3.12 and 3.13 plus explicit CLI smoke tests.

**Remaining work for credible empirical accuracy:** assemble an independently adjudicated human-labeled corpus from real repositories, record actual-model transcripts and measured tokens/latencies, calibrate severity, and run paired blind evaluation. R8.03 implements the execution/evaluation system; it does **not** pretend that synthetic fixtures are that real corpus.
