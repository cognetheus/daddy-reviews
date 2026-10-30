# Cloudflare reviewer research and phased Daddy Reviews upgrades

**Reviewed:** Cloudflare public engineering write-ups (April, August and October 2026).
**Scope:** Publicly documented architecture and practices, **not** Cloudflare's proprietary reviewer source.

## Primary sources

- [Orchestrating AI Code Review at scale](https://blog.cloudflare.com/ai-code-review/) — coordinator, specialist agents, risk tiers, routing, output contracts, retry/failback, CI/local parity, human override.
- [How Cloudflare enforces engineering standards using AI](https://blog.cloudflare.com/engineering-standards-enforcement) — RFC owners, MUST/SHOULD levels, approved vs enforced lifecycle, progressive disclosure.
- [Cutting our inference bill by 68%](https://blog.cloudflare.com/obsessive-inference-optimization) — cost attribution, shared cached prefixes, fewer sequential tool calls, reviewer skipping on reruns, canary/shadow testing.
- [Internal AI engineering stack](https://blog.cloudflare.com/internal-ai-engineering-stack/) — GitLab CI/OpenCode coordinator, Engineering Codex and per-repository agent guidance.

Cloudflare's system is not published here, and Daddy Reviews does not claim compatibility with its internal infrastructure.

## What we learned

### 1. Risk-aware routing is a useful *budget* decision
Cloudflare routes small changes to fewer reviewer sessions; high-risk code and larger diffs receive expanded coverage. Routing is a resource decision, **not** proof that small PRs are safe. Our deterministic tiering selects `trivial`, `lite` or `full` and reports why.

### 2. Diff noise is not a reason to ignore trust boundaries
Lockfiles, vendored code, sourcemaps and generated files inflate context. Cloudflare's pipeline reduces noise, while exempting schema migrations. Daddy Reviews classifies files as context-only hints **without removing them** from deterministic review or evidence output. Migrated and security-sensitive changes always stay in the required set. Dependency lock changes still deserve SCA/dependency checks in a later adapter.

### 3. Standards need traceable applicability and approval lifecycle
Cloudflare's Engineering Codex uses RFC-style ownership, MUST/SHOULD requirements and an approved/enforced transition. Daddy Reviews now supports an opt-in repository-owned JSON standards catalog with unique IDs, levels, lifecycle states, file-glob applicability, source citations and rationale. Applicability is not compliance. Merely setting `state=enforced` cannot block a merge.

### 4. A judge should reduce false positives rather than inflate severity
Cloudflare uses a coordinator to deduplicate, recategorize and reject speculative specialist findings. Daddy Reviews includes a deterministic, nonblocking adjudicator. It merges identical assertions, surfaces contradictions, and requires an explicit verification artifact before escalating a claimed confirmed severe candidate to **human block review**. No automated approval or GitHub write is performed.

### 5. Agent execution belongs behind verification and budgets
Cloudflare uses separate OpenCode sessions, retryable-error classification, timeouts, circuit breakers, remote configuration and usage tracking. A **local-only opt-in reviewer runtime** is now available via `ai-review`. It uses actual parallel specialist model requests via the local Ollama HTTP API, never exposes tools to model sessions, validates changed-line citations, and treats all model claims as unverified. A plain `review` remains deterministic and makes no model calls. Hosted execution, cost tracking, circuit breakers and total orchestration deadlines are not implemented.

### 6. Evals and cost are production features
Cloudflare's October optimization write-up notes prompt-cache prefix placement, model/effort experiments, concurrency and shadow mode. Before introducing an LLM executor, measure reviewer agreement on labeled PRs, true defect precision/recall, false-alarm rate, review p95 latency, token/cost by tier, provider failure behavior and reviewer usefulness.

## Phases in this repository

| Phase | Deliverable | Verification / constraint |
| --- | --- | --- |
| **R0 — research and architecture** | Source-backed engineering comparison, acceptance gates | This document; public sources |
| **R1 — adaptive scope** | `triage.assess_review_tier()`: tier, reviewers, file-context hints, guardrails | Tests: security tiny change → full; migration never hidden; empty diff abstains |
| **R2 — governed rules** | `standards.evaluate_standards()`: schema validation, explicit applicability and governance metadata | No implicit violation or merge block; unsafe catalogs abstain |
| **R3 — evidence coordinator** | `adjudication.adjudicate()`: deterministic deduplication, disagreement, proof gate | No autonomous comments, approvals or merge blocking |
| **R4 — local agent runtime** | **Implemented:** explicit CLI opt-in, localhost Ollama provider, concurrent specialist calls, output budgets, source-line validation and fail-closed reports | Fake-provider and local HTTP transport tests; live model quality not measured |
| **R5 — CI posting and reruns** | *Not implemented*: GitHub checks/comments, stable finding identities, re-review tracking | Explicit user opt-in, least privilege, idempotency, human override |
| **R6 — quality and cost calibration** | *Not implemented*: labeled real-world PR corpus, canary/shadow A/B, cost/latency dashboards | Measured false-positive and severity reliability |

## Local specialist execution (R4)

```bash
# Start Ollama separately, ensure the chosen model is installed.
# Invoke explicitly; default review remains offline and deterministic.
daddy-reviews ai-review --root . --base origin/main --head HEAD --model YOUR_LOCAL_MODEL
```

The adapter accepts only loopback HTTP origins (default `127.0.0.1:11434`), refuses redirects, caps input/output sizes, restricts locations to added changed lines, limits concurrency to three and requires per-request timeouts. It sends the patch to the local Ollama process, so the caller must ensure that process and machine are trusted. Any failed specialist marks the overall result incomplete, and the CLI exits nonzero. Local mocked transport and fake providers are CI-tested; no real-model accuracy or token cost has been measured.

## CLI examples

```bash
# Review retains existing evidence and adds review_tier, standards and adjudication.
daddy-reviews review --root . --base origin/main --head HEAD

# Optional organization policy. Place your reviewed file in:
#   .daddy-reviews/standards.json
# Or start from examples/standards.json, adjusting source references to REAL documents.
daddy-reviews standards --root . --changed src/auth/session.py

# These commands are read-only. An empty report is not human approval.
```

## Policy example and trust model

For each rule, supply `id`, `title`, `level` (`MUST` or `SHOULD`), `state` (`advisory` or `enforced`), `paths`, `source`, and `rationale`. Rules are not executable code. The example's citation paths are **illustrative**; users must point them to actual authoritative rules in their repository before relying on them.

No automatic `state=enforced` blocking exists. That will require independent confirmation of a reachable failure, trusted provenance, human override, and a separately authorized CI integration.

## Non-goals and honest limitations

- This release does **not** reproduce Cloudflare's proprietary reviewer infrastructure or measured production metrics.
- Real *local model* requests are opt-in; Cloudflare's hosted OpenCode sessions, provider failover, GitHub comments, and merge controls are not implemented.
- A path-based tier is only a routing hint; subtle logic or supply-chain risks require deeper review.
- A filename-glob policy match does not imply a violated standard.
- Replaying a syntax pattern is not evidence of exploitability or business consequence.
- Internal Cloudflare standards and code are not copied.

The priority remains **evidence over volume**: a single reproducible important finding beats ten speculative comments.
