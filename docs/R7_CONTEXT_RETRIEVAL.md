# R7.06 — Ranked context retrieval and graph-index lifecycle

R7.06 completes the initial R7 **source-backed repository intelligence** milestone. It fuses a versioned cross-layer graph, the existing import dependency graph, and an **optional single-symbol semantic query** into an evidence-ranked context bundle. No reviewed source is executed and no model/PR publication is invoked.

## Reviewer-facing workflow

```bash
# Retrieve read-only context around a changed service and its possible consumers
daddy-reviews context --root . --changed app/services.py

# Bind an actual single-symbol semantic adapter; optional Node/.NET/JDK as needed
daddy-reviews context --root . --changed app/services.py --symbol get_user

# Keep only 8 small excerpts, with two lines around each selected anchor
daddy-reviews context --root . --changed app/services.py \
  --context-limit 8 --context-radius 2

# Explicit opt-in: cache graph metadata, NEVER the source excerpts
daddy-reviews context --root . --changed app/services.py \
  --context-cache /tmp/daddy-review-context-cache.json

# An existing R7.01 manifest can pin source evidence
daddy-reviews snapshot --root . > /tmp/daddy-manifest.json
daddy-reviews context --root . --snapshot-file /tmp/daddy-manifest.json \
  --changed app/services.py --symbol get_user
```

The CLI produces `daddy-reviews-ranked-context-v1` with `status`, `snapshot_id`, `ranked_context`, a validated `daddy-reviews-context-bundle-v1`, bounded `graph_edges`, `cache` invalidation information, `coverage`, and explicit limitations. **Exit 0** means the supported scan and requested selection completed. **Exit 2** means partial, missing/unresolvable semantic coverage, stale source, truncated context selection, or another incomplete input. Neither implies defect-free code.

## Provenance and graph fusion

1. R7.01 creates/validates a SHA-256 manifest of the working tree. Incomplete or stale snapshots abstain before retrieving source.
2. R7.05 supplies HTTP/handler/service/DTO/ORM/migration/event graph edges. The pre-existing module graph supplies source-import candidate edges, including potentially relevant test importers.
3. When `--symbol` is provided, the selected **actual adapter** is called: Python AST (candidate), pinned TypeScript compiler (resolved when supported), JDK javac (resolved), or SDK Roslyn (resolved). The adapter must return locations bound to the **same** snapshot. Absent toolchain, unresolved symbol, unsupported project or partial compiler diagnostics are explicitly reported.
4. The graph edges are normalized to path-level `source`, `target`, `relationship`, `origin`, `certainty`, and source-linked evidence. A compiler-resolved **static binding is not runtime invocation proof**.
5. Ranking follows bounded inbound consumers and outbound dependencies (up to four hops), favoring explicit semantic callers, the changed file, direct graph dependents, and source-imported tests. `ranked_context` includes score, candidate signals, selected source span, a line-numbered excerpt, and `trust: untrusted_repository_source`.
6. Source bytes are re-hashed before excerpt generation and the whole snapshot is checked again before returning. Source-window text is untrusted data and must not be interpreted as agent instructions.

### Ranking / resource budgets

| Field | Bound |
| --- | --- |
| Changed paths | 1–20 safe relative paths |
| Returned excerpts | 1–24 (`--context-limit`; 12 default) |
| Context window | 0–8 lines either side (`--context-radius`; 3 default) |
| Excerpt content | 6 KB maximum per selected snippet |
| Impact traversal | Four hops, cycle-safe |
| Displayed normalized edges | 250; ranker can use additional bounded graph edges |
| Import/cross graph scan | Existing R7.01/R7.05 budgets and source limits |

Ranking is deterministic and designed for **context usefulness**, not a learned confidence probability. The returned score is *not* a prediction of defect probability. Token budgets will be enforced by the R8 agent tooling layer before supplying context to an LLM.

## Safe cache and invalidation

- **Default:** no persistent cache, no disk write.
- `--context-cache` stores the **complete source manifest and static graph metadata only**, never full source bytes, prompt text, reviewer findings, GitHub tokens or selected excerpts.
- On identical snapshot ID and identical repository root, a validated cache is a graph hit and skips both graph builds. Source excerpts are **always freshly read and SHA-256 verified**.
- On added, removed, modified source/config or a different workspace root, the graph is rebuilt in full. Previous import and cross-layer edges are used only to list **known affected dependents**, not to claim complete impact over dynamic dependencies.
- Cache output is atomically replaced with restrictive file mode; symlinked targets and malformed JSON are rejected/bypassed. The payload has a consistency digest, **not a keyed MAC or independent proof of authenticity**; writable local cache metadata remains untrusted by other security boundaries.
- Incomplete/partial graph results are not persisted. Cache storage errors are reported without hiding valid live analysis.

## Precision and operational boundaries

R7.06 does not yet provide persistent compiler symbol databases, incremental TypeScript/Javac/Roslyn parsing, workspace-aware JDT LS/MSBuild, complete NestJS/Spring/.NET request mapping, runtime tracing, automatically executed tests, or source execution. Exact-cache reuse and conservative full-rebuild invalidation are implemented; **partial source recompilation is not**.

An absent reference does not establish that there is no consumer. Static evidence is *candidate evidence*, and compiler identity is not validation of the business impact or security of a change. The new `context` command is **opt-in** and does not silently feed source material to the R1–R6 local `ai-review` command. R8 will introduce bounded, permissioned agent investigation tools and explicit context budgets.

## Acceptance proof

`tests/test_context_engine.py` covers a multi-layer path including an import-linked test, actual Python semantic result fusion, stale/partial input, unknown symbols, cache hit and invalidation on changed/new consumers, tampered cache, cross-root cache rejection, symlink attack, selection truncation, CLI exit contract, and malicious repository text. Existing compiler and cross-layer tests remain in CI on Python 3.10, 3.12 and 3.13.
