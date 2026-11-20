# R8.05d — Operational readiness, resilience and incident runbook

**Delivery status:** Implemented and tested as read-only local operations and a GitHub Actions preview. **No production go-live authority is conferred by this phase.** The release is explicitly blocked until externally authenticated GitHub protection, independently validated real-human defect accuracy and the authorized R8.06 pilot.

## Entry points

Run inside an actual Daddy Reviews Git checkout after `python -m pip install --constraint ci/requirements-constraints.txt -e '.[verification]' pytest`:

```bash
# Actual diff, two read-only review iterations, candidate budgets
daddy-reviews ops-preflight --root . --base HEAD~1 --head HEAD \
  --ops-samples 2 --ops-p95-ms 60000 --ops-peak-kib 262144 \
  > ./ops-summary.json

# Separate static, read-only workflow/dependency inspection
daddy-reviews ops-security --root .

# Recheck signed-looking/untrusted local evidence; ALWAYS exits 2,
# even on a local passing candidate, because release is blocked
daddy-reviews ops-readiness --root . --ops-evidence-file ./ops-summary.json

# If needed, collect only closed-schema event records from a trusted
# operator's extracted benchmark.events + fault_injection.events array
daddy-reviews ops-telemetry --root . --ops-evidence-file ./ops-events.json
```

`ops-preflight` succeeds (exit 0) only when its **local checks** pass. `ops-readiness` always emits `production_ready=false`, `release_authorized=false`, `human_signoff_required=true`, `github_publication=none` and `merge_action=none`, then exits **2**. A local passing JSON report is self-reported, not externally signed, and cannot override the release decision.

## R8.05d.01 — Performance benchmarks and limits

The real review engine is invoked against the operator-selected Git patch. The program refuses patches over **512 KiB**, changes involving more than **200 files**, zero source changes, and sample count outside **1–6**. Default candidate budget: **60,000 ms p95**, **262,144 KiB (256 MiB)** of peak Python `tracemalloc` allocations. The p95 estimator is nearest-rank for a *small sample*; it is not statistically validated at two samples. CI runs two iterations; a real release should measure hundreds/thousands of representative PRs across target repositories.

`tracemalloc` measures Python allocations, **not process RSS** or native/compiler subprocess use. The benchmark executes in-process with no enforced OS-level deadline. Limits are post-measurement thresholds; an infinite review could still hang the worker until a CI job timeout. No nonzero test outcome or absence of findings implies code correctness.

### Candidate thresholds (local CI only)

| Signal | Preview threshold | Escalation |
|---|---:|---|
| Small/medium patch size | Up to 512 KiB | Stop local preview; split scope or increase budget only after review |
| Review p95 | At most 60 seconds | Investigate graph/semantic indexing bottlenecks before pilot |
| Peak traced Python allocations | At most 256 MiB | Profile memory and native RSS independently |
| Unexpected review probe failures | 0 | Block local gate; preserve sanitized diagnostic evidence |
| Fault/recovery probe failures | 0 of 5 | Block; run timeout/overflow/retry negative tests |
| Operator telemetry | All expected event types present; zero failures | Surface candidate alert in failed GitHub Action |

These figures are **engineering smoke-test budgets, not observed customer SLOs** and should be adjusted only with benchmark evidence and business acceptance.

## R8.05d.02 — Failure injection, retries and recovery

`probe_supervisor_faults()` exercises real sandbox-free **trusted fixed** Python commands through `run_bounded`: a healthy response, a deliberate nonzero exit, an oversized stdout stream, a sleeping subprocess terminated at deadline, and a transient read-only failure followed by recovery. Each case checks the expected control, never emits subprocess stdout/stderr, and creates an anonymized event.

`retry_classified_read_only()` is a narrowly scoped primitive: at most three attempts, exponential bounded backoff, a bounded **between-attempt** total budget, and stop-on-permanent or unexpected exceptions. **Only a trusted idempotent adapter may call it.** It is not yet integrated into every GitHub API/LLM provider call. Callback runtimes must have their own hard timeout: the retry helper alone cannot interrupt a blocked callback. Never apply automatic retries to publishing PR reviews, merges, writes or non-idempotent requests.

These tests check failure-handling contracts. They do **not** constitute kernel sandboxing or a guarantee that a descendant process could not escape to a new process group.

## R8.05d.03 — Observability, redaction and alerting

Operational events are closed-schema `daddy-reviews-ops-event-v1` objects with only `operation`, `outcome`, `elapsed_ms`, and `peak_python_kib`. The validator rejects extra keys, arbitrary source/text fields, malformed types, over-budget numerical values and more than 128 events per batch. There is no free-form message, repository path, URL or token field.

Aggregated batch telemetry reports review p95, peak Python allocation, total/event error count, and bounded alert codes. The only implemented alert transport is **the GitHub Actions workflow's failed status/notifications**. There is no external monitoring service, webhook, live service dashboard, on-call escalation, evidence retention beyond the explicit artifact TTL, or production SLO proof.

The dedicated [Operational Readiness Preview](../.github/workflows/operational-readiness-preview.yml) workflow executes read-only checks on actual committed Git objects, tests the same source, and uploads only `summary.json` plus `acceptance.json` as `daddy-ops-local-readiness-preview` for **seven days**. It has contents:read, never obtains OIDC signing privileges, never uploads raw patch/source/models/evidence, and cannot approve, post, or merge.

## R8.05d.04 — Security verification

`ops-security` reads bounded local sources with no symlink traversal and reports the current static controls: CODEOWNERS, Python constraints, TypeScript SHA-512 lockfile, exact .NET SDK, GitHub Actions full-SHA references, read-only token declarations, checkout credential denial, and the OIDC signing job's lack of shell/checkout/code execution.

Static file inspection **cannot authenticate** upstream action identities, the running GitHub environment, an API token's actual permissions, the CI runner image's integrity or live branch-protection rules. For the actual GitHub policy, separately run `branch-governance-audit` with an appropriately scoped read-only token and pinned `gh` binary as documented in [R8.05b governance](R8_RELEASE_GOVERNANCE.md).

As of the last direct GitHub branch check, `cognetheus/daddy-reviews` `main` was unprotected (`protected:false`). Do not mark it protected without new authoritative live evidence.

## R8.05d.05 — Release and incident procedures

### Local acceptance is *not* production approval

1. Confirm reviewed code and docs correspond to the intended exact Git SHA. Ensure required CI matrix jobs and real-source/attestation workflows are green.
2. Inspect the source-free ops preview for budget alerts, scenario failures, missing telemetry, and positive-only claims. On any issue, **stop** rollout and retain bounded metadata, not full source/log dumps.
3. Require actual administrator-enforced protection of `main` (two approvals, CODEOWNERS, required up-to-date CI, no force pushes/deletion) and verify it with authenticated live GitHub branch evidence.
4. Complete R8.04k with **genuine, independent human research** on preregistered real-repository defect opportunities. Track agreement, unresolved cases and false positives; do not replace humans with synthetic signatures.
5. Complete per-platform hashed dependency runtime provenance, broader process isolation and a repeatable workload benchmark with agreed acceptance targets.
6. Run R8.06 **advisory-only** against real PRs. Define human decision owners, pilot sample size, stop/rollback triggers, latency/memory metrics, false-positive and missed-defect reviews, and explicit release authorization. Neither CI nor the LLM may authorize GitHub writes automatically.

### Incident response (manual)

- **Performance breach:** stop pilot expansion, archive only safe summary + CI run URLs, reproduce pinned source, profile hotspots, compare to prior accepted baseline. Do not silently raise budgets.
- **Evidence/integrity mismatch:** halt use of the affected artifacts, preserve trusted server-side run IDs and SHA-256 digests, rotate compromised access tokens, review workflow/action provenance. Treat label disputes as unresolved.
- **Unexpected PR comment or unauthorized merge:** revoke the writing credential, disable the publishing path, inspect GitHub audit log, review affected PRs with human owners. No automatic replay.
- **Rollback:** an authorized operator reverts the offending change through a **protected, reviewed PR** and verifies CI again. Because default branch protection is currently missing, first lock down direct writes; avoid treating a direct push/revert as an approved release procedure.
- **Recovery drill:** use fault-injection CI, explicitly record who approved remediation, what evidence matched the pinned SHA, when GitHub confirmed control recovery, and what changes prevented repetition.

## Remaining production gates

R8.05d provides genuine runnable **local engineering controls** and repeatable GitHub-hosted checks. It does not prove defect truth, a production SLO, full hermetic build, live alerting, external human independence or a protected branch. R8.06 is the next controlled pilot, not an automatic go-live. Existing publishing and merge authorization remain disabled by default.
