---
name: pr-review
description: Diff-first, risk-proportionate pull request engineering review; produces evidence-backed findings without inventing blockers.
---

# Pull Request Review

## Activation

When asked to review a pull request, changed commits, or a proposed patch. This is **not** a general repository audit unless explicitly requested.

## Intake

Confirm base/head commit, target branch, stated purpose, linked issue/spec, acceptance criteria, changed paths, tests and existing PR comments. If no spec exists, extract observable intended behavior and mark unknowns rather than invent requirements. Check whether the patch is complete; binary/generated changes require separate handling. Never run untrusted project code outside appropriate isolation.

## Pass 1: PR-local correctness

Inspect every materially changed hunk with enough context to establish semantics. Trace normal/error paths, validation, types, error propagation, failure cleanup, availability, tests and backwards compatibility. Look for missing inputs/outputs and field mappings, broken null handling, swallowing exceptions, missing awaits, concurrency, and unsafe defaults. Apply actual installed language/framework conventions and review against implemented requirements. A suspicious pattern is a candidate until verified.

## Pass 2: system integration and blast radius

Determine which changed symbols, exported contracts, data fields, shared hooks, environment keys, migrations, events and consumers are affected. Follow the relevant call graph, API/DTO/ORM contracts, security boundaries and deployment dependencies. A one-line field rename may break many services; a hundred-line isolated UI change may not. Escalate to full domain/system review only for demonstrated reachability, actual cross-cutting changes, or credible unresolved high-impact uncertainty. Keep pre-existing unrelated debt separate from PR regressions.

## Reuse-before-creation

Check existing classes/services/helpers/components/hooks/integrations/brokers/queues for overlapping capability. Compare domain authority, side effects, guarantees, data contracts, consumers and change cadence. Similar names or identical ASTs cannot establish that two modules should be unified. Preserve bounded-context separation and valid local/offline duplicates.

## Pass 3: independent verification and decisions

For each candidate, attempt refutation: inspect guardrails, feature flags, consumers, tests, constraints and counterexamples. Run appropriate tests if safe and available; record what was actually run. Severity is based on demonstrated failure, reachability, impact and mitigation, not review pressure. Distinguish confirmed introduced defects, pre-existing issues, hypotheses and optional style suggestions. Group multiple symptoms by root cause. **Zero actionable findings is a valid result**.

## Output contract

Produce: purpose and commits; reviewed scope and expansion rationale; confirmed actionable findings with precise changed-line refs; unverified material risks with required validation; pre-existing follow-up items; reuse opportunities only when justified; tests run/not run; PR recommendation with explicit caveats. Never call a review approved solely because heuristic analysis found no findings. Draft GitHub comments, preview them, and obtain explicit authorization before posting.

## CLI evidence tool (v0.2.0)

\`daddy-reviews review --root . --base origin/main --head HEAD\` yields a read-only candidate evidence packet; \`--diff-file\` accepts an existing Git patch. This tool currently only supports Python AST symbol analysis and limited heuristics, plus general patch parsing. Reference candidates are not proven call sites, test candidates are not evidence of test execution, and static findings are not independently verified. Load other relevant specialist skills as needed.
