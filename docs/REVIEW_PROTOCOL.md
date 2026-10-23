# Phase 1 review protocol

## Why diff-first

A PR review is not a full repository audit. Establish intended behavior and affected hunks before expanding. File paths may signal risk but never prove that a bug exists. Every candidate passes independent confirmation before being called a defect.

## Input and trust boundaries

- Local Git mode: \`daddy-reviews review --root . --base origin/main --head HEAD\`; uses \`git rev-parse\` and three-dot diff (merge base to head). Requires refs to be available locally; no implicit \`git fetch\` or network. Safe subprocess argv, no shell.
- Patch mode: \`daddy-reviews review --root . --diff-file /path/to/pr.patch\`; useful with externally acquired PR data. Never assume the supplied patch matches the working-tree source. Prefer a detached checkout of the PR head for consistency.
- Reviewer reads source only; symlinks are skipped for repository scanning, paths are resolved inside the provided workspace, and overlarge patches are rejected. Execute tests only in a trusted, isolated checkout.

## Review passes

1. **Intent:** PR description, tickets, requirements, acceptance criteria, base/head, prior comments, intended deployment environment.
2. **Change correctness:** inspect actual additions/removals, edge cases, behavior, error handling, authorization, and tests. Explicitly separate line changes and surrounding unchanged context.
3. **Consumer analysis:** discover definitions/imports/callers, database/API/event contracts and infra references. Confirm suspected blast radius; a text match is not a call graph.
4. **Existing capabilities:** before proposing a new class/helper/queue, search for equivalents. A matching AST is a candidate, not proof that consolidation is desirable.
5. **Targeted specialist escalation:** security, ORM/contracts, frontend/state, infrastructure, and runtime according to reachable change consequences. Do not run everything by default.
6. **Verification:** disprove each issue if possible; check existing mitigations, reachable paths, types, migrations, feature flags and execution results. Label uncertainty explicitly.
7. **Disposition:** confirmed introduced blocker, important fix, follow-up, accepted tradeoff, unverified hypothesis, or invalid suggestion. Legitimate outcome: zero actionable findings.
8. **Publication:** draft review first; human approval before GitHub posting or code modifications.

## Implemented in v0.2.0

The read-only CLI produces an **evidence packet**: file/hunk lines, conservative route, Python changed symbols, textual reference candidates, existing matching test file names, structurally identical Python function body candidates, and a restricted empty-except heuristic. These are investigative inputs and not an independent full semantic PR review.

## Not yet implemented

Actual GitHub PR transport; PR descriptions/issue fetching; precise symbol resolution via LSP/SCIP; cross-language AST adapters; requirements/specification reasoning; tested security analysis; data-lineage/ORM tracing; isolated runtime verification; automated PR comments; a learned severity calibrator. The limitations field in every packet is intentionally explicit.

## Reporting rules

Never declare a review “approved”, “safe”, or “all tests passing” solely because the output contains no findings. “No verified blockers found within inspected scope” does not mean “the PR is ready to merge”. Do not treat tests named in \`existing_test_candidates\` as executed or valid coverage. No severity inflation or quota; unverified findings are hypotheses.
