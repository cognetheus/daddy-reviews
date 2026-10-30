# R7.03 — Python AST semantic intelligence

**Scope:** snapshot-bound, read-only, local Python symbol/reference *candidates*. This builds on R7.01 provenance contracts and complements the earlier `symbol-impact` analyzer without changing its behavior.

## Run

```bash
daddy-reviews py-semantic --root . --changed src/auth.py --symbol authorize
daddy-reviews py-semantic --root . --changed services/client.py --symbol Client.submit

# Optional: bind against a previously captured manifest; stale snapshots abort.
daddy-reviews snapshot --root . > /tmp/daddy-source.json
daddy-reviews py-semantic --root . --changed src/auth.py --symbol authorize \
  --snapshot-file /tmp/daddy-source.json
```

No new Python dependencies, shell execution, Python imports from the reviewed repository, network calls, or model invocations are needed. Source is parsed using Python's standard `ast` module; **project code is never executed**.

## Implemented

- Resolve unambiguous direct and relative `from` imports, renamed aliases, `import module as alias`, and bounded unconditional module-level barrel re-exports.
- Locate calls of imported functions, async functions, constructors, decorators, class heritage references, and methods of conservatively inferred receivers.
- Infer a receiver only from a single direct constructor assignment or an explicit imported-class argument annotation. Conditional or repeated stores invalidate inferred type identity.
- Scope-aware rejection of local parameters, closures with conflicting bindings, duplicate imports, missing imports, use-before-import, and ambiguous target names.
- Every candidate carries snapshot ID, exact Python file SHA-256, path and line provenance. Relationships remain `ast/candidate` rather than compiler-resolved or runtime-verified.
- Complete snapshot verification before and after parsing; fail closed when source changes, a symlink appears, or the bounded source budget is exhausted.
- Explicit `status` outcomes: `complete`, `partial`, `stale`, `ambiguous`, `unresolved`, and `incomplete`. A non-complete CLI result exits with status 2.

### Supported relationships

| Relationship | Supported static evidence |
| --- | --- |
| `direct_call_candidate` | Direct import-bound function or async function invocation |
| `constructor_candidate` | Constructor of statically imported target class |
| `member_call_candidate` | Method call on an unambiguously imported constructor-assigned or typed receiver |
| `decorator_reference` | Imported decorator applied to another function |
| `heritage_reference` | Imported base class referenced in class declaration |

## Precision boundaries and abstentions

Python is dynamic: a syntactic association cannot prove that a call executes, dispatches to a particular implementation, or introduces a defect. Mutable objects, runtime imports, monkey patches, `getattr`, star imports, dynamic dependency injection, protocol dispatch, late-bound annotations, arbitrary decorators, complex nested module namespaces, and metaprogramming require further investigation.

R7.03 does **not** implement a Python language-server integration or full type inference. This is AST-level import/lexical scope reasoning with explicit `candidate` certainty. A later optional LSP/Pyright/Jedi-backed adapter should be implemented separately and sandboxed, with benchmark-driven correctness. Unlike TypeScript R7.02, Python R7.03 does not claim compiler symbol identity.

Indexing is bounded at 800 Python source files, 5 MB total parsed Python bytes, 200 candidate references, and 40 recorded abstentions per query. Results are static analysis metadata, not findings suitable for automatic GitHub merge blocking.

## Validation

CI on Python 3.10, 3.12 and 3.13 exercises real AST parsing and tests: async imports, relative/module imports, reexports, shadowed bindings, typed receivers, constructors, decorators, heritage, conditional reassignment, import ordering, malformed Python, stale snapshots, ambiguity and CLI output.

**Next:** R7.04 language adapters for Java/JDT and C#/.NET/Roslyn, using the same source snapshot contracts; R7.06 later implements persisted cross-language semantic graph and context ranking.
