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
- **R5 delivered (safe/opt-in):** human-approved, confirmed-finding PR inline comments with pinned SHA, changed-line validation, existing fingerprint checks and no approvals/merge blocking. Deterministic diff-level incremental rerun planning and opt-in local checkpoint persistence.
- **R6 delivered (offline evaluation):** human-labeled precision/recall/F1, per-tier false alarms and severity agreement, local Ollama latency/token reports, optional cost rates and identical-case shadow/canary comparisons.
- **Out of scope for v1.7.0:** autonomous GitHub merge enforcement, production hosted model/failover, live shadow traffic, production-quality labeled accuracy estimates and guaranteed exactly-once publication under concurrent writers.

**Release invariant:** avoid promoting static candidates to proven defects, or route hints to performed reviews. No unsolicited autonomous review comments and no automated merge blocking.

## R7 — Semantic intelligence implementation

### R7.01 — Source snapshot, evidence contracts and baseline fixtures (delivered in v1.8.0)

- Implemented bounded, content-hashed, deterministic worktree snapshot manifests (`semantic_contracts.py`) with explicit incompleteness, symlink skipping and source scan budgets.
- Versioned typed evidence records: `SourceSpan`, `SemanticSymbol`, `SemanticReference`, `ContextExcerpt`, `context_bundle`. Records are anchored to file bytes and a snapshot ID; unverified runtime call claims remain forbidden.
- Added read-only `snapshot` and `snapshot-verify` commands with nonzero stale-snapshot exit and CI coverage on Python 3.10, 3.12 and 3.13.
- Added four synthetic scenario specifications for Python auth consumers, TypeScript barrel re-export, lexical shadowing and clean changes. These are **not** human-labeled real defect accuracy benchmarks.
- See [R7 contracts](R7_SEMANTIC_CONTRACTS.md).

### R7.02 — TypeScript 6 compiler-backed semantic references (v1.9.0)

- Implemented a bounded virtual TypeScript CompilerHost and TypeChecker adapter for TS/TSX/JS/JSX sources, compiled from the R7.01 verified content snapshot. No project code is executed.
- Tracks compiler identity for imported/aliased names and barrel reexports, constructor and member calls, interfaces, type annotations, and inheritance.
- Exposes `ts-semantic --root . --changed PATH --symbol NAME` without replacing `symbol-impact` or changing the default diff-review behavior.
- Fails closed on compiler version mismatch, source drift, unsupported extended/project-reference tsconfigs, missing target symbols and budget violations. Unresolved imports yield partial coverage warnings.
- Real pinned TypeScript 6.0.3 compiler execution is exercised in CI on Python 3.10, 3.12 and 3.13, alongside the pre-existing suite.
- Remaining gaps: multi-project TypeScript monorepo resolution, persistent symbol index, semantic-context ranking, full JS/TS structural call graph, dynamic consumers, and external packages. See [R7.02 technical documentation](R7_TYPESCRIPT_COMPILER.md).

### R7.03 — Python scope-aware AST semantic indexing (v1.10.0)

- Delivered opt-in `py-semantic` for target `Symbol` or `Class.method` queries, with strictly snapshot-bound source spans and candidate-only call classification.
- Supports unambiguous relative/direct module imports, import aliases, unconditional re-export provenance, async functions, class constructors, decorators, base-class relationships, and conservative typed receiver method inference.
- Blocks unsupported or ambiguous bindings, lexical shadowing, rebinding, use-before-local-import, incomplete scans, invalid target symbols and stale sources.
- Uses only Python's standard `ast` module and source-hash contracts; **no language server or whole-program type inference** is claimed. LSP integration remains an optional later adapter.
- Added CI fixtures for positive and negative import/method cases, symlink/incomplete/ambiguous source behavior, and CLI provenance checks. See [R7.03 design](R7_PYTHON_SEMANTICS.md).

### R7.04 — Java and C# compiler-backed semantic references (v1.11.0)

- Implemented `java-semantic` via JDK javac `JavacTask` and `Trees` source/element identities. No JDT LS daemon or source execution.
- Implemented `cs-semantic` via local SDK-pinned Roslyn CSharpCompilation and semantic model, compiled from trusted helper source without NuGet packages or project MSBuild hooks.
- Both use copied SHA-256-validated worktree sources and R7.01 source spans, with explicit unresolved/partial/stale statuses and bounded execution.
- Compiler checks distinguish identical method spellings with different symbols; method calls, constructor calls and class/type references are supported.
- CI installs JDK 21 and .NET 8, builds the Roslyn helper and runs actual language compiler integration cases across the Python 3.10/3.12/3.13 matrix.
- Java project-aware JDT LS, Maven/Gradle classpaths and C# MSBuildWorkspace/solution resolution remain **separate, explicitly unmet** capabilities.
- See [Java and C# compiler integration design](R7_COMPILED_LANGUAGES.md).

### R7.05 — Source-linked cross-layer dependency intelligence (v1.12.0)

- Built versioned, read-only `cross-layer` graph and inbound/outbound impact CLI with R7.01 SHA-256 snapshot provenance and bounded depth.
- Supports a first real vertical slice: literal JS/TS HTTP calls, unique FastAPI decorator routes, imported Python handler/service calls, Pydantic request/response DTO declarations, static ORM class-to-table models, literal Alembic `create_table` migrations, and event publication/subscription topics.
- Records dynamic or ambiguous boundary abstentions rather than inventing a full consumer map; tests reject shadowed imports, duplicate functions/routes, unsourced models, unknown methods and stale snapshots.
- Important remaining gaps: parameterized URLs, API DTO/schema binding, NestJS/Express/Spring/ASP.NET, richer ORM and broker semantics, compiler graph fusion, monorepo configuration and runtime paths. These must not be portrayed as implemented.
- See [R7.05 cross-layer evidence and limitations](R7_CROSS_LAYER.md).

### R7.06 — Ranked source context, semantic overlay and graph lifecycle (v1.13.0)

- Delivered `context` CLI returning deterministic ranked source excerpts with line-numbered, manifest-hash-bound evidence, including test importers, inbound callers, outbound dependencies, and bounded graph paths.
- Fuses existing import and cross-layer graph edges with optional **one-symbol** adapters for Python (AST candidates), TS/JS (TypeScript compiler), Java (javac) and C# (Roslyn). Source trust is always `untrusted_repository_source`; semantic completeness is separately reported.
- Added opt-in cache for graph metadata and source manifest only, with exact SHA-256 snapshot hits, schema and source-span checks, restrictive atomic writes, explicit changed-path/known-dependent invalidation, and **full graph rebuilds on misses**. This is not incremental compiler parsing or an authenticated cache.
- Added 3-version Python CI gate with real all-language overlay tests, injection and tampered-cache cases, stale source, truncated context, symlink defense and deterministic ranking.
- Nonzero CLI exit on incomplete requested semantic coverage, truncated context or stale snapshots. Users can still inspect partial JSON evidence without treating it as complete.
- See [R7.06 ranked context and cache contracts](R7_CONTEXT_RETRIEVAL.md).

**R7 complete within its explicitly scoped v1 vertical slices (R7.01–R7.06).** Remaining R7 architecture limitations: persistent whole-repository language-server databases, complete monorepo/JDT LS/MSBuild workspace resolution, generalized cross-language bindings, runtime-verifiable call chains and automated model-tool access. These are deliberate future R8+ capabilities, not implied by the release.

## R8 — Permissioned agent investigation

### R8.01 — Deterministic read-only investigation tool contracts (v1.14.0)

- Implemented seven typed, explicitly capability-granted Python and CLI investigation tools: file inspection, symbol discovery, symbol references, dependency exploration, OpenAPI contract inspection, test candidates, and local Git history.
- All tools share R7.01 manifest consistency; source locations remain SHA-256-provenanced. No tool executes reviewed code, writes files, or performs outbound requests. Optional compiler-based symbol lookups reuse R7.02/R7.04 adapters with their explicit limitations.
- Introduced `InvestigationSession` with default-deny allowlist, 12-call and 128-KB response ceiling, per-result 32-KB ceiling, input/path validation, line budgets, and a machine-readable failure taxonomy.
- Added conventional OpenAPI JSON specs to the bounded R7.01 source manifest so contract tools cannot inspect untracked files. Git history is local, credential-free and HEAD-pinned.
- Added CI regression coverage for actual seven-tool behavior, permission denial/grant, stale source, missing symbols, truncated references, prompt injection, malformed contracts, unconnected test names and Git history.
- The `investigate` CLI does **not** automatically grant any capability; caller must include `--allow-tool` explicitly. The R8.01 API is deterministic, not model-orchestrated.
- See [R8.01 design, tools and safeguards](R8_INVESTIGATION_TOOLS.md).

### R8.02 — Bounded tool-driven specialist reviewer harness (v1.15.0)

- Delivered opt-in `ai-investigate` command and Python `investigate_with_specialists` orchestration; actual local model turns request one typed, granted read-only tool at a time, receive host-verified evidence, and finish with JSON candidate findings.
- Requires the patch's added line texts to exactly match the captured R7.01 working-tree source; incomplete/stale snapshots or unsupported binary/deleted-only diffs cannot produce a falsely grounded review.
- Specialists retain independent R8.01 tool sessions and evidence namespaces. Tool/call/round/model-payload/parallelism caps, per-call Ollama timeout, strict response schemas and failure isolation apply; malformed provider output is a failed reviewer, not a clean finding result.
- Host issues citations only for tools whose source spans independently pass snapshot-ID, source SHA-256 and line-range validation. Candidate findings must cite a host-issued span overlapping the exact changed added line; model assertions of `confirmed` or merge permission are rejected.
- Existing R6 `adjudicate` deduplicates candidates. The resulting report always uses `verification: unverified`, `merge_action: none`, `github_publication: none`; human verification is still required.
- CI regression tests cover actual local mock-Ollama multi-turn CLI traffic, permission denial, forged citations/locations/source hashes, independent reviewers, provider timeouts, unsafe action payloads, stale source, source mismatch and finite budgets.
- Docs and caveats: [R8.02 specialist investigation harness](R8_SPECIALIST_INVESTIGATION.md). No real-model accuracy benchmark is claimed by mock transport tests.

### R8.03 — Deterministic investigation replay and calibration (v1.16.0)

- Delivered offline `investigation-replay` over the **actual** R8.02 specialist orchestration and R8.01 source tools. Only model decisions are scripted; source snippets, permissions and evidence IDs are recalculated on isolated fixtures.
- Added a versioned fixture format separating `synthetic` from self-declared `human_labeled` data. The bundled ten scenarios cover true-positive, false-positive, false-negative, clean, permission-denied, forged citations, missing tools, provider timeout, injected source text and duplicate-reviewer findings.
- Scoring measures exact path/line/rule TP/FP/FN, precision/recall/F1, severity agreement, clean-case false-positive rate, incomplete coverage, model turns, tool calls and actual local replay latency. Missing inference tokens and cost remain unavailable (not zero).
- Added deterministic SHA-256 transcript digests excluding volatile local timings, strict replay-step completeness checks, and `investigation-compare` with matching-corpus verification, recalculated score integrity, new-incomplete-case detection and configured regression thresholds.
- Added default-off `ai-investigate --record-model-turns` to capture model JSON decisions (without raw tool responses or source snippets) for explicitly assembled future replay corpora; errors are recorded as safe transport-fault markers.
- **Promotion abstains** on synthetic or undersized corpora. Actual human-adjudicated repository cases and live-model outcome evaluation remain necessary before claiming real-world reviewer quality.
- Regression suite and CLI smoke cover the above in the Python 3.10/3.12/3.13 CI matrix. Details: [R8.03 replay and evaluation](R8_INVESTIGATION_REPLAY.md).

### R8.04a — Bounded human verification queue (delivered increment)

- Added deterministic `verification_queue` to R8.02 `ai-investigate` reports. Source-backed candidates become *pending independent verification*, not confirmed issues.
- Groups hypotheses by changed path, line and rule; records reviewer attribution, provenance-consistent source spans, severity conflicts and suggested reproduction/refutation checks.
- Missing/incomplete specialist runs and invalid evidence escalate to humans; no findings from a failed investigation are never called a clean result.
- Source citations are not independently tested defect claims. No model can self-verify or authorize PR publication or merge action.
- See [R8.04a human verification queue](R8_VERIFICATION_QUEUE.md).

### R8.04b — Independent challenge runner (delivered developer API)

- Added a source-snapshot and patch-bound, opt-in independent specialist challenge with fresh R8.01 read-only tool sessions and host-issued citation IDs.
- Challenger reviewer identity must differ from the author of each original candidate. It returns `supported`, `refuted` or `uncertain` only as **advisory** hypotheses; it cannot confirm, delete, publish or block a finding.
- Dedicated localhost Ollama challenge protocol with bounded inference turns/tools and no redirect; invalid/forged evidence or failed tools escalate to human review.
- CI fixtures include independent counterexample verdicts, denied/forged tool references, self-review prevention, stale sources and local Ollama protocol checks.
- See [R8.04b independent challenge](R8_INDEPENDENT_CHALLENGE.md). This is a Python developer API, not a CLI feature.

### R8.04c — Signed human evidence and conflict policy (delivered developer API)

- Implemented opt-in Ed25519 verification of human decision records against a separately supplied, enabled public-key registry. Missing keys, forged signatures, stale snapshot bindings and replayed records fail closed.
- Bound signed human claims to exact candidate, changed-source SHA-256, patch SHA-256, captured snapshot and supplied test-log byte digests. Test commands are **recorded, never executed**; logs are not independently attested as true CI runs.
- Requires two distinct registered human reviewer identities (configurable 2–4) for a human-attested confirmation or rejection; conflicting or incomplete evidence escalates. Challenger-vs-human contradictions require explicit signed acknowledgement.
- Produces deterministic audit receipts and a chained hash, with no raw test-log output, autonomous GitHub publication, merge action or assertion of objectively verified defects.
- Added adversarial signed-artifact tests and three-version Python CI gates; the `cryptography` dependency is optional via `.[verification]`.
- See [R8.04c signed human verification](R8_HUMAN_VERIFICATION.md). This is a Python developer API, not CLI or independently attested CI provenance.

### R8.04d.01–d.02 — Operator ingestion and independent runner signature checks (delivered incremental APIs)

- Added explicit `human-verify` CLI for offline human attestation verification: bounded regular-file inputs, symlink rejection, duplicate-key/NaN rejection, separately operator-owned trusted-key JSON, and SHA-256-named test logs. Exit 2 for unresolved or invalid cases.
- Added optional signed CI-runner receipts with a **separate enrolled Ed25519 runner key**, pinned repository/commit, source snapshot and patch digest, matching human-signed test ID/outcome/log bytes, and complete-coverage gate. Runner signatures never change merge/posting permissions.
- This verifies an enrolled runner key's signature, **not** GitHub OIDC/platform identity, CI workflow execution or transparency-log provenance. We must not call it a verified hosted CI run.
- Added hostile-path/forged-JSON tests, real signed end-to-end CLI and runner authenticity regressions, and three-version CI gate.
- See [R8.04d operator workflow and trust limits](R8_OPERATOR_WORKFLOW.md).

### R8.04d.03 — Bounded human-resolution evaluation and paired regression (delivered infrastructure)

- Added read-only `human-resolution-eval` and `human-resolution-compare` CLI commands for bounded, source-identity-paired datasets (up to 200 cases) and self-declared independently labeled outcomes.
- Tracks true positives, false alarms, confirmed missed defects, unresolved known defects, human/model conflicts, coverage-adjusted recall, per-tier metrics and regression thresholds; comparison refuses changed labels/source identities.
- Added ten deliberately synthetic scenarios and CI smoke/regression cases. Human-label metadata and copied resolution JSON are **not re-cryptographically authenticated** by this evaluator; the corpus cannot support production quality claims.
- No evaluation score permits GitHub publication, merge blocking or reviewer promotion.
- See [R8.04d.03 human resolution scoring](R8_HUMAN_QUALITY.md).

### R8.04e — Genuine GitHub/Sigstore artifact authentication (delivered increment)

- Added `github-attestation-verify` CLI: SHA-256-pinned official GitHub CLI binary, offline Sigstore bundle and independently supplied trusted root, GitHub Actions OIDC issuer, expected SLSA predicate, pinned signer workflow/source commit and immutable numeric GitHub repository ID.
- Revalidates verified certificate identity, timestamp presence and attested artifact digest after successful GitHub cryptographic verification. Forbids untrusted executable directories, path symlinks, unbounded output, arbitrary shell or automatic publication/merge actions.
- Extends `human-verify` to require a cryptographically platform-authenticated artifact digest to match human-signed test logs, with incomplete-coverage escalation.
- Added unit policy/adversarial tests in the Python 3.10/3.12/3.13 matrix and **a separate real GitHub Actions OIDC/Sigstore attestation integration workflow**. The real integration succeeded at commit `140bd2ba`, including an altered-artifact rejection.
- This validates **artifact origin and integrity**, NOT that a test ran truthfully or detected an actual defect. GitHub Actions user-controllable provenance predicates cannot be treated as independently verified test results.
- See [R8.04e offline GitHub provenance verification](R8_GITHUB_ATTESTATION.md).

### R8.04f — Supervised test execution and OIDC-isolated signing (delivered integration)

- Added a bounded, fixed-suite pytest supervisor that records a real process exit code, output digests, suite hash, source commit, run identity and UTC execution interval in `daddy-reviews-supervised-test-execution-v1` format.
- Added an offline `attested-test-verify` operator CLI that runs the pinned official GitHub/Sigstore verifier **and** binds the signed artifact to a strict, exact suite/run/source/exit-code contract. Forged or contradictory status, truncated logs and stale source evidence fail closed.
- Refactored real GitHub Actions integration into **three least-privilege jobs**: test (read-only, no OIDC), sign (only approved download/sign actions, OIDC-capable, no repository source execution), verify (read-only, no OIDC). Test capture itself refuses GitHub/OIDC token-bearing environments. This avoids giving reviewed tests signing credentials.
- The real three-job integration passed with tampering rejected at commit `26daee8b`; Python 3.10/3.12/3.13 CI includes actual subprocess and operator-CLI regressions. Static tests enforce OIDC job isolation.
- A GitHub artifact signature proves origin and integrity of the **supervisor's output**, not externally that all test assertions or source code were honest. Run ID, process timestamps and result bytes are self-reported by the restricted job. Protected workflows/branch, action SHA pinning, reproducible hermetic test dependencies and independent GitHub job/status checks remain necessary.
- See [R8.04f supervised test execution](R8_SUPERVISED_TEST_EXECUTION.md).

**Remaining release gates:** independently check GitHub Jobs API status and protected workflow identity, collect a blinded and independently adjudicated *real repository* defect corpus, and measure empirical false positives/misses. R8.04 is an engineering preview; production model correctness and automatic merge safety remain unestablished.
