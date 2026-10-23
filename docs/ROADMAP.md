# Evidence-first delivery plan

## Phase 0: foundations (initial delivery)
Define finding schemas, severity vs confidence vs disposition, clean-fixture acceptance tests, scope selection, and official-source requirements. Never assume a finding quota. Initial implementation uses Python stdlib and pytest only.

## Phase 1: credible PR review (in progress)
Accept local diffs and GitHub metadata (read-only); parse changed hunks; map findings to changed lines; collect specs; verify against tests; separate pre-existing debt. Publish only after explicit user approval. Distinguish a failing test from a hypothesis.

## Phase 2: repository capability index
Add language server/SCIP adapters, import/call graph, symbol references, semantic candidates, and domain ownership. Compare behavior and contracts before suggesting reuse. Support cache invalidation and bounded indexing.

## Phase 3: adaptive scope
Implement a measurable state machine for local -> dependency -> system-level review with stopping criteria. Small variable rename touching serialized API contract may trigger broad review; big test-only changes need not.

## Phase 4: language and library standards
Official version-specific guidance for TS/JS, Python, C#/.NET, Java and their ORM ecosystems; lockfile/SBOM/SCA reconciliation; avoid upgrades solely for recency. Expand languages through separate adapters.

## Phase 5: cross-layer and architecture
Trace UI -> DTO -> API -> domain -> ORM -> database -> response; events, queues, jobs, contracts, state management, hooks, caching, error policies, DDD and boundaries. Verify via tests or mark unverified.

## Phase 6: runtime assurance
Opt-in sandboxed Docker/Compose readiness, migration tests, queries, load, observability, auth/tenant-negative tests, secret-safe logs. Never execute untrusted project hooks implicitly.

## Phase 7: integrations
GitHub PR review draft/approval/posting, SARIF where applicable, source-to-finding line mapping, CI and agent integrations with least privilege.

## Phase 8: calibration lifecycle
Research update registry, regression evaluations, clean PR false-positive rate, precision/recall, severity accuracy, repeatable findings, accepted risks, human feedback and cost metrics.

### Evidence gates
Every blocker must have a documented impact, reachable failure path, exact location, and confirmed evidence. Unverified critical *hypotheses* may demand urgent investigation but are not mislabeled as proven. Full repository scans are explicitly requested or triggered by high-impact evidence, not the default.

### v0.4.0 delivered incremental capability

Initial relative-import JS/TS consumer candidates and bounded OpenAPI JSON compatibility deltas. Full multi-language symbol resolution, DTO-to-ORM mapping, robust verification engine and contract-version rollout tests remain planned.
