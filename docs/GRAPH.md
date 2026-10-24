# Repository module graph and capability discovery (v0.6.0)

## What is implemented

The read-only graph builder indexes bounded Python and JavaScript/TypeScript source trees. Each node records its repository-relative path, language family, and local source SHA-256. Each edge records the importing and imported module, source line, import kind, and an explicitly limited **static import candidate** classification.

Python imports are parsed with stdlib AST, supporting relative and package imports when the target is unambiguous. JS/TS edges cover common relative import/export statements, literal require, and literal dynamic import. Full re-export resolution, dependency-injection wiring, and compiler symbol identity are *not* resolved.

## Commands

~~~bash
# Full bounded graph, candidate cycles and optional reverse impact
daddy-reviews graph --root . --changed src/domain/orders.py --max-depth 3

# An explicit reusable JSON snapshot using normal shell redirection
daddy-reviews graph --root . > graph.json

# Names and locations of initial existing-capability candidates
daddy-reviews capabilities --root . --query 'send notification'

# Include bounded direct/transitive module impact in PR review packets
daddy-reviews review --root . --base main --head HEAD
~~~

## Interpreting results

- \`direct_consumers\`: a file has a static import edge to the changed file.
- \`transitive_consumers\`: a file imports another file along a chain toward the changed module.
- \`via\`: shortest discovered import path, **not** a verified runtime call trace.
- \`unindexed_changed\`: file missing from the index, including deleted, generated, skipped, unsupported or inaccessible files.
- \`cycles\`: syntax-derived import cycles; these are not automatically defects.
- \`truncated\`: a traversal budget was reached or the underlying graph has scan warnings.
- \`symbols\`: Python declarations or selected JS/TS exports. Search hits indicate potentially relevant names, **not** semantically equivalent functions/classes.

Do not recommend consolidation solely because a name, token, import cycle or code body looks similar. Determine bounded contexts, authority, transaction scopes, side effects, failure behavior, consumers and release cadence first.

## Budget, trust, and safety

Maximum 4,000 files, 350 KB per file, and 24 MB total source, with explicit scan warnings. Common vendor/generated directories and symlinked sources are skipped. The CLI reads source but never imports, executes, installs dependencies, or writes to GitHub. Depth is capped at 8; PR packets cap reverse consumer count at 100. Ambiguous import targets abstain instead of guessing.

Graph source hashes are local content identities, not authenticated Git commit SHAs. A user-created JSON snapshot via redirection requires explicit commit/version provenance in any later security or deployment assessment.

## Non-goals and limitations

This first graph does not establish graph completeness, runtime reachability, actual function invocation, domain/business behavior, dynamic imports, DI container binding, emitted events, or cross-layer API/ORM effects. Missing edges are not evidence of isolation. More reliable semantic impact requires LSP/SCIP or native compiler adapters, build configuration, API schemas and targeted integration tests.

Review confidence and severity are independent of graph depth. A variable rename involving a serialized field can have greater blast radius than a long isolated refactor, and an import cycle may be benign in context.

## Regression requirements

Test positive edges, transitive consumers, relative Python imports, TS re-export chains, JS require, cycle handling, comment-only false positives, path ambiguity abstention, source budget exhaustion, capability search, and zero-finding PR behavior. Do not claim tests are executed or real defects detected when only these deterministic candidates are indexed.

## v0.7.0: local tsconfig/jsconfig alias candidates

Non-relative JS/TS imports may now resolve to indexed local files when a nearest standalone `tsconfig.json` or `jsconfig.json` declares `compilerOptions.paths` or `baseUrl`. Exact aliases, single-star aliases, JSONC comments/trailing commas, and bounded target lists are supported. The resolver never executes TypeScript, Node, package scripts, or repository code.

The resolver **abstains** on config inheritance (`extends`), project references, invalid/oversized/symlinked config, ambiguous indexed targets, unsupported wildcard patterns, or targets outside the repository. Config warnings appear in the graph and review packet. It cannot determine whether the importing file is included in the tsconfig project, nor honor Node/package export maps, condition selection, bundler aliases, or compiler module resolution modes. A positive edge is a **configuration-based candidate**, not proof of a compiled import or reachable call. The existing direct JS/TS symbol-call heuristic remains relative-import-only.

## v0.8.0: comparing two graph snapshots

The `graph-diff` command accepts two explicit JSON exports from `daddy-reviews graph`. It validates the graph version, paths, SHA-256 values, unique nodes/edges, edge endpoints and size limits before computing changes. It never invokes Git or project code.

```bash
daddy-reviews graph --root /path/to/before > before.json
daddy-reviews graph --root /path/to/after > after.json
daddy-reviews graph-diff --before-graph before.json --after-graph after.json --max-depth 3
```

The report distinguishes added, removed, and source-hash-modified modules; import-edge changes (identity: source, target, kind; line movement alone ignored); and bounded before/after reverse-import candidates. Configuration-only changes can alter alias edges without modifying indexed source files. Invalid or oversized snapshots fail closed. File changes are based on source hashes **only**; there is no proof the snapshots belong to a specific commit, no incremental parser, no verified runtime call graph, and no semantic defect inference. Warnings and output truncation are explicit.


## Opt-in persistent cache (v0.9.0)

`daddy-reviews graph --root . --cache-file /tmp/daddy-graph-cache.json` stores a schema-validated graph snapshot in a user-chosen local JSON file. A cache hit requires a fresh SHA-256 fingerprint of every indexed source file and every tsconfig/jsconfig file under the scan root, plus root identity and Python interpreter version. Changes to file paths, file contents, or alias configurations force a full rebuild. Graph warnings, indexing-budget exhaustion, and source changes during the build prevent cache persistence. Corrupt or oversized snapshots are ignored and rebuilt. Cache destinations must be non-symlink `.json` paths in existing directories, excluding tsconfig/jsconfig filenames.

**Performance boundary:** cache hits skip Python AST/JS lexical import parsing, but still enumerate and hash source/config files. A single edit triggers a full rebuild, not incremental per-file parsing. Cache snapshots are not authenticated to Git commits, cannot prove runtime calls, and must not be used as evidence of repository provenance. Cache writes occur **only** with `--cache-file`; ordinary graph, capability, review and diff commands remain read-only. Prefer cache locations outside the repository.

## v1.0.0: per-file incremental import-edge reuse

An opt-in cache now stores a v2 schema-validated graph with a separate **resolution-context fingerprint**. The context covers indexed module paths, repository root, Python interpreter version, and bounded tsconfig/jsconfig contents. On a source-only edit, unchanged files reuse their previously resolved outgoing static-import edges; changed files are reparsed, and the entire graph is reassembled deterministically. This is an **incremental module-edge index**, not incremental compiler analysis or a persistent AST/symbol database.

When indexed files are added/removed, or a TS/JS configuration changes, the resolver conservatively reparses **all** files because previously resolved targets may change. A corrupt or legacy cache also triggers a full rebuild. Cache metadata reports `parsed_files` and `reused_files` for each store/hit. Graph warnings, concurrent source changes, and unsafe cache destinations continue to prevent cache persistence. All edges remain static import candidates, not proven runtime calls or semantic dependencies.
