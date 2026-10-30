# Daddy Reviews

**Evidence-first engineering intelligence for PRs and repository review.**

![CI](https://github.com/cognetheus/daddy-reviews/actions/workflows/ci.yml/badge.svg)

v1.7.0 now includes **adaptive review tiers, repository-owned standards applicability, and conservative cross-reviewer adjudication**, alongside the existing read-only diff evidence engine. The new features are deterministic planning and evidence safeguards, **not** autonomous model reviewers or automatic merge approvals.\n\nPreviously, v0.9.0 added a working **read-only Git diff evidence collector**, conservative Python AST symbol and reuse reconnaissance, risk-aware task routing, and a structured findings contract. This is not yet a full autonomous PR reviewer or a verified multi-language analysis platform.

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
