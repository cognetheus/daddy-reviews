# Daddy Reviews

**Evidence-first engineering intelligence for PRs and repository review.**

![CI](https://github.com/cognetheus/daddy-reviews/actions/workflows/ci.yml/badge.svg)

The current v1.16.0 baseline includes read-only semantic analysis, bounded model-driven investigation, replay/calibration, and explicit human approval boundaries. R8.04a–c additionally provide an advisory evidence queue, independent counterexample challenges, and signed human-attestation adjudication as opt-in Python APIs. **No model decision can independently authorize a merge or automatic PR comment.**\n\nPreviously, v0.9.0 added a working **read-only Git diff evidence collector**, conservative Python AST symbol and reuse reconnaissance, risk-aware task routing, and a structured findings contract. This is not yet a full autonomous PR reviewer or a verified multi-language analysis platform.

## Cloudflare-inspired review phases (v1.7.0)

Implemented in [R1–R4 research and implementation](docs/CLOUDFLARE_REVIEW_RND.md):

- **Risk-tier routing:** `trivial`, `lite`, `full` with explicit escalation for security, schema migrations, and operational changes.
- **Noise classification:** lockfiles and generated/vendor files are marked as context-only suggestions **without removing evidence from review**.
- **Engineering standards:** an opt-in `.daddy-reviews/standards.json` catalog with rule IDs, MUST/SHOULD levels, state, source and path applicability; rules do not automatically block.
- **Finding adjudication:** deduplication, contradictions, verification-artifact requirements and human-review candidates; no unauthorized approvals or GitHub comments.
- **Opt-in local specialist agents:** parallel, bounded reviewer sessions powered by a local Ollama model. No hosted inference, implicit code execution, or automatic GitHub writes.

```bash
daddy-reviews review --root . --base origin/main --head HEAD
daddy-reviews standards --root . --changed src/auth/login.py
daddy-reviews adjudicate --root . --report-file review.json
# OPTIONAL: requires a running local Ollama server and installed model.
# This explicitly sends diff context to a LOCAL model process.
daddy-reviews ai-review --root . --base origin/main --head HEAD --model YOUR_LOCAL_MODEL
```

The `review` report includes `review_tier`, `standards` and `adjudication`. The `ai-review` command explicitly runs local specialist model requests. Model-generated findings remain unverified; agent failure yields a nonzero CLI exit status. No GitHub PR posting or merge enforcement exists.

## R5–R6: PR publishing and review calibration (v1.7.0)

**R5** adds opt-in, human-approved GitHub inline PR comments with stale-head protection, exact changed-line verification, comment fingerprint deduplication, and local incremental re-review checkpoints. A plain review never posts to GitHub.

**R6** adds independently human-labeled quality metrics (precision, recall, F1, severity agreement, false alarms on clean PRs), observed Ollama token/latency metrics, and offline shadow/canary regression comparison.

```bash
# No network: preview approved inline PR findings
daddy-reviews pr-publish --repo OWNER/REPO --pr 123 --report-file approved.json
# GitHub write requires --apply, human-approved verified findings, token and pinned PR HEAD
daddy-reviews pr-publish --repo OWNER/REPO --pr 123 --report-file approved.json \
  --expected-head-sha 0123456789abcdef0123456789abcdef01234567 --apply

# Rerun diff selection and explicit state checkpoint
daddy-reviews rerun --root . --base origin/main --head "$(git rev-parse HEAD)" \
  --state-file .daddy-rerun.json --save-state

# Human-labeled quality and cost/performance evaluation
daddy-reviews quality-eval --dataset evals/quality_synthetic.json
daddy-reviews quality-compare --baseline-dataset evals/quality_synthetic.json \
  --candidate-dataset evals/quality_synthetic.json
daddy-reviews telemetry --report-file reviewed-run.json
```

See [R5 safe publishing](docs/R5_GITHUB_PUBLISHING.md) and [R6 quality/calibration](docs/R6_CALIBRATION.md). The provided labeled dataset is **synthetic**, not evidence of model accuracy in real PRs. All GitHub writes remain explicitly authorized; model findings remain unverified.

## R8.04a–g — Evidence-driven human verification and independent provenance

R8.04 adds a source-bound verification queue, read-only independent counterexample challenge, and an **Ed25519-signed human attestation** workflow. Two separately trusted human identities must attest a decision, and their signatures bind the exact model claim, changed-source hash, patch, and observed test-log digest. Opposing AI challenges require explicit signed human acknowledgement. Incomplete reviewers or stale evidence **escalate rather than prove clean code**.

```bash
# Required for signed human verification APIs and the human-verify CLI
python -m pip install -e '.[verification]'
```

Use the developer APIs in `daddy_reviews.verification_queue`, `daddy_reviews.independent_challenge` and `daddy_reviews.human_resolution`. These do not run repository test commands, create signatures, publish GitHub reviews, or block merges. The separate operator CLIs described below are now available. Signatures establish key-controlled human authorization; raw logs alone cannot prove execution. A verified GitHub artifact attestation establishes artifact provenance, not execution truth.

**R8.04d.01–d.02 delivered:** the offline `human-verify` CLI safely ingests explicit human attestation files and optionally checks independently enrolled CI-runner Ed25519 signatures bound to the same source and test-log bytes. Runner signatures are **not GitHub OIDC verification or proof a workflow executed**. Use `daddy-reviews human-verify --help` for required flags.

**R8.04d.03 delivered:** offline `human-resolution-eval` and `human-resolution-compare` CLIs report false alarms, confirmed misses, unresolved defects, and human/model conflicts. The bundled ten-case corpus is synthetic and cannot support empirical accuracy claims.

**R8.04e delivered:** `github-attestation-verify` uses a pinned GitHub CLI binary, offline Sigstore trusted roots and cryptographic OIDC verification for an exact artifact. Policy pins the signer workflow, source commit, immutable numeric repository ID and artifact SHA-256. `human-verify` can also link that authenticated artifact to independently signed human-test receipts. A dedicated GitHub Actions workflow successfully tested **real** OIDC/Sigstore signing, offline verification and tamper rejection. This authenticates artifact origin, **not** whether a test actually ran or passed.

**R8.04f delivered:** an opt-in fixed-suite pytest supervisor and `attested-test-verify` CLI. A genuine three-job GitHub Actions integration executes the suite without OIDC permissions, signs the bounded execution artifact in an **action-only signing job**, then authenticates signature, suite hash, run identity and exit-code record in a separate non-OIDC job. Process evidence and artifact origin are cryptographically linked, but the reported outcome remains an attested workflow claim—not proof that arbitrary repository code is correct.

**R8.04g delivered:** `github-jobs-verify` queries GitHub's authenticated completed-run and job APIs to independently cross-check the source SHA, attempt, workflow, job identities and critical step success. The separate post-completion verification workflow passed on a genuine attested test run. `attested-test-verify --check-live-github-jobs` optionally requires both live job status and a cryptographically verified artifact. `human-label-audit` verifies two separately authorized Ed25519 ground-truth label signatures per case, binding them to source identity and independently supplied evidence bytes. No real-world human-labeled study has been claimed.

See [R8.04a queue](docs/R8_VERIFICATION_QUEUE.md), [R8.04b challenge](docs/R8_INDEPENDENT_CHALLENGE.md), [R8.04c human attestation](docs/R8_HUMAN_VERIFICATION.md), [R8.04d operator workflow](docs/R8_OPERATOR_WORKFLOW.md), [R8.04d evaluation](docs/R8_HUMAN_QUALITY.md), [R8.04e GitHub/Sigstore verification](docs/R8_GITHUB_ATTESTATION.md), [R8.04f supervised test execution](docs/R8_SUPERVISED_TEST_EXECUTION.md), and [R8.04g independent jobs and labels](docs/R8_GITHUB_JOBS_AND_LABELS.md). Authenticated job status and signatures do not prove defect truth; real independently sampled repository cases and controlled workflow protection remain open.

## R8.03 — Deterministic specialist replay & evaluation (v1.16.0)

**New:** run recorded *model decisions* through **real permissioned R8.01 tools** in isolated source fixtures, then score the R8.02 investigation harness for true positives, false positives, missed issues, incomplete sessions, and tool efficiency. Results include reproducible trace hashes and source-verified citation checks. A paired comparator flags deteriorating precision/recall or newly failed investigations.

```bash
# Purely synthetic examples, no model inference or network
daddy-reviews investigation-replay \
  --replay-dataset evals/investigation_replay_synthetic.json > /tmp/replay.json

# Compare two evaluations over exactly matching source and ground truth
daddy-reviews investigation-compare \
  --baseline-replay /tmp/replay.json --candidate-replay /tmp/replay.json
```

The included ten cases are deliberately **synthetic** and cannot establish actual model defect-detection quality or authorize rollout. Live `ai-investigate` can optionally add `--record-model-turns` to return the model's JSON actions for subsequent replay (never raw tool responses, and disabled by default). Only an independently adjudicated, adequately sized labeled corpus can support empirical model evaluation; even then, publication and merge gates require separate human approval.

See [R8.03 replay, scoring, regression and limits](docs/R8_INVESTIGATION_REPLAY.md).

## R8.02 — Tool-driven specialist investigation harness (v1.15.0)

**New:** opt-in, actually multi-turn specialist agents can now **request host-authorized R8.01 investigation tools**, inspect results, then return findings with **host-issued source evidence IDs**. The harness validates citations against the exact changed line and SHA-256 snapshot before accepting them. No autonomous writes, PR approvals, merge blocking or GitHub publication.

```bash
# Local Ollama-compatible model only; patch additions must match checked-out sources
daddy-reviews ai-investigate --root . --base origin/main --head HEAD \
  --model YOUR_LOCAL_MODEL \
  --allow-tool read_file --allow-tool find_references \
  --allow-tool query_dependencies --allow-tool find_tests \
  --investigation-reviewers 3 --investigation-rounds 4 \
  --investigation-tools 3 --agent-parallel 2
```

Failed/denied tools, invented citations, mismatched source lines and failed specialists yield **incomplete**, never a fabricated clean review. [R8.02 protocol, budgets and safeguards](docs/R8_SPECIALIST_INVESTIGATION.md).

## R8.01 — Permissioned engineering investigation tools (v1.14.0)

**Seven read-only tools** now expose R7 intelligence to a typed investigation interface: `read_file`, `find_symbol`, `find_references`, `query_dependencies`, `inspect_contract`, `find_tests`, `inspect_history`. Each tool enforces explicit capabilities, bounded outputs, SHA-256 snapshot consistency, and honest partial/unavailable results. **No LLM agent can call them automatically yet**; R8.02 will add permissioned specialist orchestration.

```bash
# Omission of --allow-tool returns a machine-readable denial
daddy-reviews investigate --root . --tool read_file \
  --allow-tool read_file --path src/auth.py --end-line 30

# Reference lookup using the relevant Python/TS/javac/Roslyn semantic adapter
daddy-reviews investigate --root . --tool find_references \
  --allow-tool find_references --path src/auth.py --symbol authorize
```

See [R8.01 investigation tool API, permissions, and limitations](docs/R8_INVESTIGATION_TOOLS.md).

## R7.06 — Ranked context retrieval & index lifecycle (v1.13.0)

**New:** an opt-in reviewer-facing `context` command that ranks relevant source excerpts using existing import and cross-layer evidence, optionally adds **real Python AST, TypeScript, javac or Roslyn symbol references**, and verifies every returned location against the current R7.01 source manifest.

```bash
# Read-only by default: ranked callers, service/ORM/event consumers and relevant tests
daddy-reviews context --root . --changed app/services.py

# Optional exact symbol resolution (language adapter chosen by file extension)
daddy-reviews context --root . --changed app/services.py --symbol get_user

# Opt-in graph metadata cache; snippets are never written to it
daddy-reviews context --root . --changed app/services.py \
  --context-cache /tmp/daddy-context-cache.json
```

Cache hits only reuse graphs for identical source hashes; changes conservatively invalidate known affected paths and rebuild the **whole graph**. Ranked excerpts remain untrusted source text, not instructions or confirmed runtime call paths. The `ai-review` command does not automatically consume this context yet; that belongs to R8 tool integration.

See [R7.06 design and acceptance criteria](docs/R7_CONTEXT_RETRIEVAL.md).

## R7.05 — Cross-layer dependency intelligence (v1.12.0)

**New:** a snapshot-bound, **read-only candidate graph** across literal JS/TS HTTP calls → unique FastAPI endpoints → imported Python service functions → ORM model/table declarations and published event topics → subscribed consumers, plus Pydantic request/response DTO declarations and Alembic table-migration references. All edges cite exact source-file hashes and lines. Unsupported dynamic routes/imports/queries abstain rather than creating false certainty.

```bash
# Return bounded source-linked graph and inbound/outbound impact paths
daddy-reviews cross-layer --root . --changed app/services.py --max-depth 5
```

This first vertical slice supports exact literal HTTP routes, simple module import bindings, SQLAlchemy-like model uses, and literal event topics. It **does not** integrate full NestJS/Express, Spring, ASP.NET, DTO serialization, generated schemas, or automatic verified runtime traces yet. [R7.05 scope and evidence rules](docs/R7_CROSS_LAYER.md).

## R7.04 — Java and C#/.NET compiler semantic analysis (v1.11.0)

**New:** opt-in Java (`javac` Trees) and C#/.NET (Roslyn SDK) semantic adapters with **compiler-resolved method, constructor, and type-reference identity**. Each output is bounded and bound to an R7.01 source snapshot; unresolved external dependencies produce partial coverage rather than a fabricated clean result.

```bash
# Java needs JDK 17+; JDK 21 used in CI
daddy-reviews java-semantic --root . --changed src/main/java/app/UserService.java --symbol UserService.authorize

# C# needs the pinned .NET 8 SDK and a one-time build of the trusted helper
(cd tooling/dotnet && dotnet build -c Release)
daddy-reviews cs-semantic --root . --changed src/Services/UserService.cs --symbol UserService.Authorize
```

The adapters do not run reviewed code, build systems or dependency resolution. Java uses JDK compiler APIs **instead of JDT LS**; Roslyn uses standalone compilation **instead of MSBuildWorkspace**. Full multi-module project loading and cross-layer impact retrieval remain R7.05–R7.06 work.

See [R7.04 compiler contracts and limitations](docs/R7_COMPILED_LANGUAGES.md).

## R7.03 — Python semantic analysis (v1.10.0)

**New:** snapshot-bound Python AST semantic reference candidates, covering unambiguous import bindings, relative modules, aliases, re-export chains, constructors, async functions, decorators, class inheritance, and method calls on conservatively inferred typed receivers. Dynamic, shadowed or competing bindings abstain rather than generating unsupported references.

```bash
daddy-reviews py-semantic --root . --changed src/auth.py --symbol authorize
daddy-reviews py-semantic --root . --changed src/services.py --symbol Client.submit
```

All results have source hashes and locations through the R7.01 context contracts, and remain **AST candidates, not runtime-proven calls or LSP results**. No Python packages or project execution are required.

See [R7.03 technical details](docs/R7_PYTHON_SEMANTICS.md).

## R7.02 — Compiler-backed TypeScript/JavaScript analysis (v1.9.0)

**New:** read-only TypeScript **6.0.3 compiler API** semantic references with verified snapshot provenance. Resolves named imports, aliases, barrel re-exports, class constructors/methods, interfaces, type annotations and inheritance without relying on identifier spelling alone. The existing lexical indexing remains available separately.

```bash
# Optional dependency; base Python CLI does not require Node
npm install --prefix tooling/typescript --ignore-scripts --no-audit --no-fund
daddy-reviews ts-semantic --root . --changed src/auth.ts --symbol authorize
```

The compiler adapter never executes project code. Unsupported tsconfig `extends`/project references, missing dependencies and incomplete snapshots are reported instead of fabricated links. It is a **single-symbol query adapter**, not yet the full R7.06 contextual index.

See [R7.02 design, setup and acceptance](docs/R7_TYPESCRIPT_COMPILER.md).

## R7.01 — Semantic source contracts (v1.8.0)

First implementation of the deeper repository-intelligence roadmap: **bounded, SHA-256 source manifests and provenance-bound semantic symbol/reference/context contracts**. This is not yet a full language-server index or compiler-backed call graph.

```bash
# Read-only worktree snapshot
daddy-reviews snapshot --root . > /tmp/daddy-reviews-source.json
# Fails with exit 2 if files changed, appeared, disappeared or scan is incomplete
daddy-reviews snapshot-verify --root . --snapshot-file /tmp/daddy-reviews-source.json
```

Includes strict path/symlink/size validation, stale context rejection and synthetic cross-language fixture scenarios. See [R7 semantic contracts and acceptance criteria](docs/R7_SEMANTIC_CONTRACTS.md). R7.02 will add TypeScript compiler-backed symbol resolution using these evidence contracts.

## Install and test

\`\`\`bash
python -m pip install -e . pytest
pytest -q
\`\`\`

## Usage

\`\`\`bash
# Diff-first evidence packet for a local PR branch (base ref must exist locally)
daddy-reviews review --root . --base origin/main --head HEAD

# Offline review using an existing Git unified patch
daddy-reviews review --root . --diff-file /tmp/change.patch

# Earlier commands remain available
daddy-reviews plan --task 'Review PR' --changed src/auth/tenant.py
daddy-reviews inventory --root .
daddy-reviews stack --root .
daddy-reviews audit --root . --changed src/daddy_reviews/core.py
\`\`\`

Commands return JSON and perform no GitHub posting. By default they are read-only; **only an explicitly provided `--cache-file`** writes a local graph-cache JSON file. An evidence packet contains changed hunks/line numbers, initial risk routing, Python changed symbols, textual possible references and Python import-linked call candidates, potential structurally duplicated Python function bodies, matching test-file paths, and preliminary swallowed-exception candidates restricted to changed lines.

**Evidence limitations matter:** textual matches are not an accurate call graph; function-body similarity does not justify automatic consolidation; a test filename is not verified test coverage; a zero-finding result is not a merge approval. All heuristic findings remain unverified until confirmed using appropriate code/context/runtime evidence.

## Skills and roadmap

- [skills/SKILL.md](skills/SKILL.md) — skill router and evidence policy
- [skills/pr-review/SKILL.md](skills/pr-review/SKILL.md) — diff-first and bigger-picture PR review protocol
- [docs/REVIEW_PROTOCOL.md](docs/REVIEW_PROTOCOL.md) — operational methodology and limitations
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — implemented architecture and trust boundaries
- [docs/ROADMAP.md](docs/ROADMAP.md) — staged cross-language implementation roadmap

The rest of \`skills/\` contains specialist guides for frontend, backend, security, ORM, dependencies, infrastructure, architectural review, finding verification, and repository intelligence.

## Engineering principles

1. Understand intent and existing code before recommending new work.
2. PR-first, then meaningful consumer and architectural impact analysis.
3. Evidence before severity; no quotas for findings or critical bugs.
4. Version-aware guidance, authoritative standards and clear uncertainty.
5. No source changes or GitHub review publication without explicit authorization.

## Attribution

Published exclusively under the connected \`cognetheus\` account without co-author trailers.

## v0.4.0 — syntax-linked JS/TS and OpenAPI review

The read-only `review` packet now includes `changed_js_ts_symbols` and `js_ts_import_linked_calls`, for common relative named/namespace imports. This partial lexical analysis is **not** full TS language-server resolution (dynamic imports, re-exports, path aliases and shadowing are not reliably handled).

Compare explicit OpenAPI 3.x **JSON** snapshots:

```bash
daddy-reviews contracts --base-contract old-openapi.json --head-contract new-openapi.json
```

It identifies operation removal, request/response object-property removal, newly required request fields, and primitive field type changes. These are **schema-change candidates**, not verified runtime bugs or complete cross-layer DTO/ORM mappings. Nested/composed schemas and multiple status responses require later adapters. Do not assign critical severity from these candidates alone.

## v0.4.1 — evidence replay

Run `daddy-reviews verify --root . --report-file review.json` to recheck supported patterns against the current source snapshot. Currently only `PY-SILENT-EXCEPT` can be replayed. A reproduced pattern is **not proof of a defect or its severity**; unsupported rules remain explicitly unresolved. The report contains a SHA-256 of examined file bytes, not a trusted Git commit identity.

## v0.5.0 — review calibration regression fixtures

`daddy-reviews evaluate --dataset evals/baseline.json` executes isolated read-only source fixtures. Metrics include syntax-*candidate* precision and recall, clean-case false-alarm rate, and count of unjustified blocking dispositions. **These are not software-defect detection accuracy metrics.** The baseline contains normal cases, a changed exception handler, a pre-existing exception handler unrelated to the diff, and a sensitive filename requiring deeper inspection but not automatic critical severity. Human-labeled real defect corpora, severity calibration and semantic verification remain future work.

## v0.6.0 — bounded dependency graph and capability catalog

The read-only `graph` CLI now indexes local Python and JS/TS module imports, provides direct/transitive reverse dependency paths, records source SHA-256, and identifies import-cycle candidates. The `capabilities` CLI searches Python functions/classes/methods and selected JS/TS exports by name/path tokens. A lexical match **never** proves functionality should be reused or classes merged.

```bash
daddy-reviews graph --root . --changed src/domain/orders.py --max-depth 3
daddy-reviews graph --root . > graph.json
daddy-reviews capabilities --root . --query 'send notification'
daddy-reviews review --root . --base main --head HEAD
```

PR packets include bounded module-level impact and changed-module import-cycle candidates. Imported modules are **not a verified symbol-call graph**, and unresolved/ambiguous imports, aliases, dynamic behavior, or build-time resolution can create missing edges. No review severity is assigned by the graph. See [graph design and limitations](docs/GRAPH.md).

## v0.7.0 — conservative TypeScript/JavaScript alias edges

The module graph now recognizes **local `tsconfig.json` / `jsconfig.json` `compilerOptions.paths` and `baseUrl` mappings**, including one-star aliases, JSONC comments/trailing commas, and nearest-config selection in a monorepo. Resolved edges are labeled `js_tsconfig_alias_*`, so they can be distinguished from ordinary relative imports. Alias results participate in reverse dependency impact analysis and PR evidence packets.

This is **not compiler-aware symbol resolution**. Config `extends` and project references cause explicit abstention/warnings; multiple possible indexed targets are not guessed. Package exports, module-resolution modes, project inclusion, inherited aliases, and actual runtime calls remain unverified. See [graph design](docs/GRAPH.md).

## v0.8.0 — snapshot graph delta and Python multi-import correctness

Compare **explicitly exported** graph snapshots without executing source code or writing repository files:

```bash
# Run each command in its corresponding checked-out revision/worktree.
daddy-reviews graph --root /path/to/before > before-graph.json
daddy-reviews graph --root /path/to/after > after-graph.json

# Compare indexed source hashes, import edges and bounded reverse consumer candidates.
daddy-reviews graph-diff --before-graph before-graph.json --after-graph after-graph.json
```

The new graph-diff reader validates snapshot format, SHA-256, paths, edge endpoints, duplicates, and size budgets; line-only movement does not count as an import-edge change. Changed TypeScript alias resolution may produce an edge delta even when indexed source hashes are unchanged. Python `from pkg import a, b` now indexes multiple resolvable submodule targets rather than only the first. No commit provenance is inferred from a snapshot, and this is **not** an incremental parser/cache or verified runtime call graph. See [graph documentation](docs/GRAPH.md).


## v0.9.0 — opt-in persistent graph cache (whole-tree invalidation)

Graph and capability commands now support an **explicit** persistent cache file. Unchanged source/configuration fingerprints reuse a validated module graph without re-parsing imports. The cache is a local performance optimization; it is **not incremental per-file parsing**. Any source or tsconfig/jsconfig change rebuilds the whole graph.

```bash
daddy-reviews graph --root . --cache-file /tmp/daddy-graph-cache.json --changed src/domain/orders.py
daddy-reviews graph --root . --cache-file /tmp/daddy-graph-cache.json
daddy-reviews capabilities --root . --cache-file /tmp/daddy-graph-cache.json --query 'notification'
```

Output includes `cache.status`: `stored`, `hit`, `bypassed`, `volatile`, or `write_failed`. Source and config files are hashed on every invocation; no source is executed. Cache entries are schema-validated and reject symlink destinations. Cache writes are atomic. Incomplete scans or a changing repository disable persistence. Keep the cache outside the repository (or gitignore it); it is not a trusted Git revision identity. The default commands do not write files. See [graph documentation](docs/GRAPH.md).

## v1.0.0 — incremental module-edge indexing

With `--cache-file`, unchanged source modules reuse their previously resolved import edges after a source-only change. New/removed paths or changed tsconfig/jsconfig files force full re-resolution. Cache metadata now includes `parsed_files` and `reused_files` counts. This is a conservative static import-edge optimization, **not** full AST/symbol indexing or verified runtime reachability. See [graph limitations](docs/GRAPH.md).


## v1.1.0 — bounded Python symbol-level call candidates

A new read-only `symbol-impact` command identifies **syntactic import-bound calls** to a selected top-level Python function or class. It resolves unambiguous local absolute/relative module imports, aliases, and module-qualified expressions; it abstains on ambiguous module paths, rebinding and lexical shadowing. This is narrower than module-level impact, but **not** a full symbol resolver or runtime call graph.

```bash
daddy-reviews symbol-impact --root . --changed src/pkg/service.py --symbol calculate
```

Results include source paths, lines, expressions, shadowed-call abstentions, warnings and explicit limitations. Nested imports, star imports, reexports, dynamic behavior, and comprehension calls are not exhaustively resolved. Missing candidates **never** prove no consumers. No automatic findings or severity assignments are generated.

## v1.2.0 — bounded Python reexport provenance

`symbol-impact` now traces uniquely resolved, unconditional top-level Python `from` reexports, including aliased package barrels, and attaches `provenance_modules` to each call candidate. Cyclic, conditional, duplicate, shadowed and dynamically constructed exports are conservatively omitted. This is a static AST provenance hypothesis, not verified runtime symbol identity or call reachability. See [graph limitations](docs/GRAPH.md).

## v1.3.0 — conservative function-local Python import candidates

`symbol-impact` now identifies calls following **unconditional direct function-body imports** (including aliased, module-qualified, relative, and proven reexport bindings). This intentionally narrow extension requires a unique import binding with no competing local assignments, parameters, deletions, or conditional imports. Calls before the import, within nested closures, or in comprehensions are not promoted. Static candidates do not establish runtime invocation; absent candidates do not prove isolation.

## v1.4.0 — JS/TS direct named-import call candidates

`symbol-impact` now accepts JS/TS target files with top-level named exports, in addition to Python. It resolves direct named imports and standalone tsconfig/jsconfig aliases where unambiguous, then reports syntactic call candidates while abstaining on possible consumer-file shadowing. No compiler, runtime, package installation, or repository code execution is involved.

```bash
daddy-reviews symbol-impact --root . --changed src/lib/math.ts --symbol calculate
```

This is **not** TypeScript compiler-aware symbol resolution. Reexports, default/namespace imports, type-only imports, complex scopes and runtime dispatch remain unsupported; no candidate becomes an automatic finding. See [graph limitations](docs/GRAPH.md).
