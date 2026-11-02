# R7.05 — Source-backed cross-layer dependency intelligence

**Status:** implemented bounded static **candidate** paths across HTTP clients, API handlers, Python services, ORM model declarations, database-table names and event topics. This is a vertical slice; it does not claim enterprise-wide, framework-agnostic static analysis.

## CLI

```bash
# Entire graph (read-only; no external dependencies or code execution)
daddy-reviews cross-layer --root .

# Inbound consumers and outbound dependencies of a changed service
daddy-reviews cross-layer --root . --changed app/services.py --max-depth 5

# Optionally bind to a previously captured snapshot
daddy-reviews snapshot --root . > /tmp/review-snapshot.json
daddy-reviews cross-layer --root . --snapshot-file /tmp/review-snapshot.json \
  --changed app/services.py
```

## Supported source-to-source connections

| Source | Target | Evidence and resolution |
| --- | --- | --- |
| Browser `fetch('/literal')` or `axios.get('/literal')` | Unique FastAPI `@app.get('/literal')` | Exact literal HTTP method/path; matching is a static candidate, **not** observed network traffic |
| FastAPI route declaration | Top-level decorated handler function | Function/decorator source location from Python AST |
| Python route/service function | Unambiguously imported local function | Direct `from module import name` or safely aliased module call; lexical shadowing and duplicate bindings invalidate resolution |
| Python service function | Imported/local class with a static `__tablename__` | `session.query(Model)`, `session.add(Model(...))`, and static `select(Model)` candidates; ORM execution is **not** proven |
| Model declaration | Declared database table | Exact `__tablename__` string; no migration, schema or live database verification |
| Function `broker.publish('literal')` | Topic `literal` | Lexically recognized publish/emit/send with a string topic; no broker identity or actual delivery verified |
| Topic `literal` | Handler `@broker.subscribe('literal')` | Matching topic string in decorator; not evidence the consumer is registered or running |

All nodes and edges link to R7.01 `SourceSpan` values containing **snapshot ID, source-file SHA-256, path, line, origin, and candidate certainty**. No model-generated edge is admitted without source evidence. The implementation reads a bounded repository snapshot twice (before/after) and refuses stale input rather than issuing ungrounded results.

## Impact semantics

`impact.inbound_dependents` walks the reverse graph from changed-file nodes to HTTP handlers and calling clients. `impact.outbound_dependencies` walks dependencies from a service to its model/table and published event topic/subscriber. Both return bounded shortest candidate paths (`via`), the source path, the distance and a static-candidate classification.

`graph.status: complete` means the *supported static scan* finished, **not** that all repository dependencies were discovered. Invalid Python syntax is `partial`. A stale/incomplete source snapshot returns no graph edges and a nonzero CLI exit. Dynamic inputs, duplicate routes, unsupported prefixes, missing imports, ambiguous declarations and unresolved ORM entities are recorded as `abstentions`. Successful scans do not imply a bug or authorize CI merge blocking.

## Security and boundedness

- No code execution, live HTTP requests, database connections, imports of target code, container startup, or GitHub writes.
- Capture <=4,000 source/config files through R7.01; R7.05 scans <=800 Python and <=800 JS/TS files with <=8 MB combined source, <=3,000 nodes, <=4,000 edges and <=200 recorded abstentions.
- Source symlinks, changed hashes and invalid/symlinked manifests fail closed.
- Request paths are **exact relative literals only**, excluding query strings, templates and dynamic expressions. Missing/unmatched API route evidence is not invented.
- Global method/path uniqueness is required for client-to-route edges; duplicate endpoints abstain.
- Depth-bounded impact (1–6 hops) and output ceilings prevent unbounded graph traversal.

## Explicit limitations

FastAPI application factories, router prefixes, included routers, parameterized endpoints, DTO serialization, authentication checks, request lifecycles, exception propagation, NestJS/Express, Spring MVC, ASP.NET controllers, indirect dependency injection, SQLAlchemy relationship resolution, ORM queries beyond the supported static patterns, migration/schema truth, event broker configuration, consumer registration and actual runtime dispatch remain unresolved.

TypeScript compiler-backed references (R7.02), Python AST candidates (R7.03), and javac/Roslyn adapters (R7.04) remain separate tools; this phase **does not yet merge their full semantic graphs**. R7.06 is responsible for project-aware graph integration, ranked context retrieval, caches and invalidation. A matching literal API and URL is not proof that two independently deployed services communicate.

## Regression gate

`tests/test_cross_layer.py` covers a fully chained TypeScript-to-FastAPI-to-service-to-ORM-and-event scenario, source hash evidence, reverse/forward impact, duplicate/missing routes, dynamic URLs/topics, shadowed Python imports, duplicate functions, missing model declarations, method mismatches, query strings, corrupted source and stale snapshots. Full CI must remain green across Python 3.10, 3.12 and 3.13.
