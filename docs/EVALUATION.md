# Evaluation protocol — v0.5.0

## How to run

python -m daddy_reviews.cli evaluate --dataset evals/baseline.json

The JSON dataset must declare format daddy-reviews-eval-v1 and contain bounded cases, each with unique id, source files, a Git unified diff, and golden expected_candidates entries (rule, path, line). No runtime code is imported or executed from fixtures. Temporary fixture trees are discarded after each case.

## What is scored

- Candidate precision = expected matched reported syntactic findings / all reported candidate findings.
- Candidate recall = expected matched reported syntactic findings / all expected candidates.
- Clean-case false alarm = fraction of cases annotated with zero expected syntax candidates that nonetheless produce a candidate.
- Blocking dispositions = number of blocker claims emitted by this rule engine. Current unverified rules must not block.

A case annotated with an expected empty-except syntax candidate is **not** an assertion that an empty handler is a real bug. These metrics should NEVER be advertised as real PR review correctness, vulnerability discovery, severity calibration or human reviewer agreement.

## Test quality rules

1. Each new rule requires at least one correct positive example, one clean counterexample, and a stale/unrelated-diff case where appropriate.
2. Add bypass and false-positive traps: comments, strings, aliases, external contracts, existing mitigations, not every long function is defective.
3. Preserve separate annotations for genuine human-adjudicated bugs in a future dataset; do not confuse them with syntactic pattern labels.
4. Fix or explain regressions before promoting a new rule; zero bug findings is valid.
5. Evaluate across representative languages, frameworks, ORMs and PR sizes before claiming multi-language quality.
6. Track model versions and prompts if semantic reviewer stages are introduced, and compare against deterministic baselines.
7. Human review is required to decide whether a pattern is harmful, reachable and worth blocking.

## Known limitations

Fixtures currently test only the Python PY-SILENT-EXCEPT pattern and deterministic route selection. Other reviewer functions have unit tests but not full end-to-end evaluation annotations. Most real bugs require contracts, data flow, execution, domain understanding and separate evaluation. Scores from five synthetic cases are for regression control, not predictive production performance.
