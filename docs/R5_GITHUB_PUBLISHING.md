# R5 — Controlled GitHub PR publication and incremental reruns

**No autonomous PR comments, approvals, or merge blocking.** All publication is explicitly opt-in.

## Publication contract

Generate a deterministic review packet or opt-in local AI review first. A human must independently verify each material defect, approve the exact proposed comment and prepare a curated JSON report. A publishable finding requires: `rule`, `path`, `line`, `severity`, `changed: true`, `claim`, `evidence`, `verification: confirmed`, `verification_artifact`, and `human_approved: true`.

Example report (illustrative, not a proven defect):

```json
{
  "findings": [{
    "rule": "AUTH_001", "path": "src/auth/login.py", "line": 47,
    "severity": "high", "changed": true,
    "claim": "Missing tenant authorization on updated path",
    "evidence": "A negative-role test returned another tenant’s data",
    "verification": "confirmed",
    "verification_artifact": "tests/test_tenant_auth.py::test_cross_tenant_access",
    "human_approved": true
  }]
}
```

## Offline preview (no network calls)

```bash
daddy-reviews pr-publish --repo OWNER/REPO --pr 123 --report-file approved-findings.json
```

## Explicit publish (network and GitHub write)

```bash
export GITHUB_TOKEN="YOUR_MINIMUM_PERMISSION_TOKEN"
daddy-reviews pr-publish --repo OWNER/REPO --pr 123 \
  --report-file approved-findings.json \
  --expected-head-sha 0123456789abcdef0123456789abcdef01234567 --apply
```

Use a fine-grained token with pull-request review-comment permission only on the target repository. The tool checks that the PR is open, HEAD matches the expected SHA and every proposed comment is anchored to an actual added line. It checks existing review comments for a stable marker before each batch. The tool never submits an APPROVE or REQUEST_CHANGES review.

**Best-effort idempotency:** two concurrent publishers could race. Avoid parallel writes to the same PR. A network interruption after posting may have an ambiguous outcome; inspect existing markers and rerun after verifying the PR state. Invalid or oversized inputs, inaccessible comments and pagination limits fail closed. A multi-comment publication is not transactional.

## Incremental PR rerun state (opt-in disk write)

```bash
HEAD_SHA=$(git rev-parse HEAD)
daddy-reviews rerun --root . --base origin/main --head "$HEAD_SHA" \
  --state-file .daddy-rerun.json
# Only when you explicitly want a persisted checkpoint:
daddy-reviews rerun --root . --base origin/main --head "$HEAD_SHA" \
  --state-file .daddy-rerun.json --save-state
```

Rerun planning hashes the complete PR patch and compares per-file patch fingerprints with an explicitly saved prior checkpoint. It reports changed, removed, unchanged and re-review candidates, but does not automatically reuse old findings as verified or run model reviewers. State writes are atomic and opt-in; keep checkpoint files outside source control.

See the R5 regression tests for stale SHA, human approval, line mapping, duplicate markers, malformed inputs and state corruption.
