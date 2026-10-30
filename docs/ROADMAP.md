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

### v0.5.0 — implemented review-fixture harness

Deterministic candidate regression tests now use JSON-labelled fixtures, isolated temporary snapshots, clean changes and high-risk filename scenarios. This is the foundation for more ambitious scoring; currently it assesses syntactic detection only. Next: confirmed human-labelled PR defects, independent reviewer verification, calibration studies and persistent finding identities.

### Phase 2 initial delivery (v0.6.0)

Shipped deterministic Python/JS/TS import-graph reconnaissance, bounded reverse impact, import-cycle candidates, source hashes, queryable lexical capability discovery, and PR packet integration. Still needed: TS compiler/SCIP/LSP resolution, incremental per-commit persistent indexing, semantic equivalence evaluation, downstream API/DTO/ORM mapping, external dependency edges, full monorepo alias resolution, and runtime reachability checks.

### Phase 2 alias-resolution increment (v0.7.0)

Added bounded JSONC-aware local `tsconfig.json`/`jsconfig.json` `paths` and `baseUrl` candidates to module dependency impact. Nearest standalone configs are recognized; inherited configs, project references and ambiguous target mappings abstain with warnings. Next: native compiler/SCIP adapters, persisted incremental graph snapshots, contract-level tracing, and human-verified symbol references.

### Phase 2 snapshot comparison increment (v0.8.0)

Added bounded read-only graph snapshot comparison, source-hash and import-edge deltas, and before/after reverse consumer candidates. Snapshots must be captured explicitly from the intended revisions; no Git commit identity is claimed. Also fixed Python multi-member from-import indexing. Remaining: **actual** incremental persistent indexing/cache, compiler/SCIP symbol adapters, cross-layer contract tracing, and independently verified call reachability.


### Phase 2 persistent graph-cache increment (v0.9.0)

Added opt-in, validated, source-hash-based persistent module-graph reuse for `graph` and `capabilities`. Unchanged trees avoid graph parsing; source additions/removals/edits and tsconfig/jsconfig changes invalidate the entire graph. No cache is used on incomplete scans, concurrent source mutations, or invalid snapshots. This is **whole-tree cache invalidation**, not incremental per-file indexing. Next: per-file parse artifacts and dependency-aware invalidation, native compiler/SCIP adapters, and verified symbol references.

### Phase 2 incremental edge-index increment (v1.0.0)

Opt-in persistent cache now reuses per-file resolved import edges when source hashes match and the indexed path/configuration resolution context is unchanged. Changed files alone are reparsed; file additions/removals and TS/JS config edits trigger conservative full re-resolution. Reports expose parsed/reused counts, with corrupt/legacy caches rebuilt and concurrent mutations guarded by a second fingerprint. Next: true per-file syntax artifact storage for path/config-change reuse, compiler/SCIP symbol indexing, and contract-level data-flow tracing.


### Phase 2 Python symbol-reference candidate increment (v1.1.0)

Added opt-in read-only `symbol-impact` for top-level Python function/class call candidates, using AST import binding and unique local module resolution. Supports aliased imports, module-qualified calls, and relative imports. Conservative lexical shadowing and ambiguous module names abstain. This is **not** compiler/LSP symbol identity, actual runtime invocation, or complete symbol reachability. Next: import-binding provenance under nested scopes, verified reexport handling, compiler-backed TypeScript symbols, and human-evaluated call-reference precision.

### Phase 2 bounded Python reexport provenance (v1.2.0)

`symbol-impact` now follows unambiguous unconditional top-level `from` reexports across up to eight module hops, including aliased package exports, and includes `provenance_modules` for each reported call candidate. It abstains on cycles, ambiguous paths, conditional imports, duplicate exports and module-level rebinding. Target definitions with conflicting module-level bindings are rejected. Remaining: nested-scope import provenance, compiler-backed TS symbol identity, verified runtime reachability and real-repository precision calibration.

### Phase 2 function-local Python import candidates (v1.3.0)

Added conservative function-local import provenance for direct unconditional function-body imports and calls on subsequent source lines. Shared import resolution ensures the same ambiguity and reexport abstentions as module-level references. Conditional imports, lexical conflicts, closures, class-local imports and comprehensions remain unverified. Next: compiler-backed TypeScript references, human-labelled precision calibration and cross-layer contract tracing.

### Phase 2 JS/TS named-import symbol candidates (v1.4.0)

`symbol-impact` now dispatches to a bounded JS/TS lexical adapter for selected top-level named exports. It recognizes direct named import aliases and standalone tsconfig/jsconfig path candidates, and conservatively abstains on possible lexical rebinding, duplicate import bindings, type-only imports, reexports, default/namespace imports, and unsupported targets. Results are **syntactic investigation leads**, not TypeScript compiler symbols, verified calls, or defect findings. Next: opt-in TypeScript compiler/SCIP integration with build-context provenance, cross-layer contract tracing, and human-labeled precision evaluation.

## Cloudflare-informed review evolution — v1.5.0

See [source-backed design and tradeoffs](CLOUDFLARE_REVIEW_RND.md).

- **R0 (research) delivered:** Cloudflare review orchestration, risk tiers, Engineering Codex rules, re-review behavior and October 2026 inference optimization were evaluated against this repository's actual baseline.
- **R1 (adaptive scope) delivered:** read-only deterministic `review_tier` calculation, file/line thresholds, sensitive-boundary escalation, context-only noise hints, and migration/generated-code exception fixtures.
- **R2 (policy source) delivered:** opt-in `standards.json` catalog with owner-authored IDs, MUST/SHOULD level, advisory/enforced lifecycle, relative glob matching, safe validation and mandatory abstention for unverified compliance.
- **R3 (evidence consolidation) delivered:** same-finding coalescing, reviewer contradictions, explicit verification-artifact checking, human block-review candidates, and no merge writes.
- **R4 delivered (local):** explicit opt-in localhost Ollama provider, parallel specialist calls, bounded inputs, validation and incomplete-run reporting. Fake/local HTTP tests only; real-model quality not evaluated.
- **R5–R6 pending:** hosted providers and circuit breakers, PR posting, rerun state, calibrated evaluations and cost telemetry.

**Release invariant:** avoid promoting static candidates to proven defects, or route hints to performed reviews. No unsolicited autonomous review comments and no automated merge blocking.
