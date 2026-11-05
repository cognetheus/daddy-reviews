# R8.04a — Human verification queue (first increment)

R8.04a adds a deterministic **read-only verification queue** to every opt-in `ai-investigate` report. This is an intermediate R8.04 increment, **not** full self-check, reproduction or automated repair. All candidate defects remain unverified.

## Output contract

`verification_queue` uses `daddy-reviews-verification-queue-v1` and contains:

- Stable snapshot/patch-bound candidate IDs grouped by exact path, added line and rule.
- Reviewer identity, number of candidate assertions, claimed severities, and bounded source spans.
- `needs_independent_verification` for provenance-consistent hypotheses.
- `escalate_human` for contradictory severity or invalid evidence provenance.
- `human_escalation_required` for any incomplete specialist investigation, including a run returning no findings.
- Three suggested human checks: reproduce, attempt to refute, and record a human-reviewed outcome.

Host-issued source spans establish what lines were read, **not** whether the hypothesis is correct. A queue-only consumer cannot re-attest source hashes without the original snapshot; the queue is an advisory review plan. A model-supplied `verification: confirmed` field is explicitly demoted to an invalid-provenance escalation. `confirmed_findings` is always zero, and both `merge_action` and `github_publication` are `none`.

## Safety boundaries

No shell execution, sandbox execution, test invocation, file writes, pull-request posting, remote network traffic or autonomous merge action is added. Queue creation is bounded to 48 findings, six reviewer runs, limited text lengths, and bounded source evidence per finding. Queue input is the existing R8.02 report, not a direct model verdict.

A malformed report raises a validation error rather than treating missing data as evidence of a clean review. Incomplete investigations cannot be labeled clean. This queue does not count as an independent review, proven defect, or reproducibility artifact.

## Verification

`tests/test_verification_queue.py` exercises actual R8.02 tool-driven findings through the queue, empty/incomplete reviews, suggestion severity, source tampering, self-confirmation attempts, duplicate reviewer runs, and stable IDs.

## Remaining R8.04 work

1. Bounded *independent* specialist counterexample/refutation turns with explicit tool-budget accounting and separately scoped host citations.
2. An opt-in human-authored verification artifact format with source/snapshot linkage, reproducible test identity and explicit trust boundaries.
3. Conflict handling between original claim, counterexample and human results, including escalation before any publishing decision.
4. Held-out human-labeled evaluation of the self-check's ability to reduce false positives without hiding genuine defects.

None of these remaining capabilities is claimed delivered by R8.04a.
