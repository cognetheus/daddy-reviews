# Graph acceptance gates and remaining milestones

The graph is an evidence source, not a verdict engine. Before relying on a dependency for consequential design/security claims, confirm compiler/import resolution, reachable consumers, build target, runtime behavior and any API or persistence contracts.

## Initial acceptance scenarios

1. Python package relative and absolute imports with direct/two-hop reverse impact.
2. JS/TS relative imports, static re-export chains and literal require.
3. Comments and unrelated name mentions do not introduce false graph edges.
4. Ambiguous Python modules result in abstention.
5. Cycle detection and bounded traversal terminate on cyclic graphs.
6. Small indexing budgets produce warnings rather than a fabricated complete graph.
7. Capability name query returns candidates without claiming domain equivalence.
8. Clean PR packet can legitimately contain no actionable findings.

## Subsequent development

- Versioned LSP/SCIP source symbol graph and compiler-aware TS/Java/.NET adapters.
- Incremental persistent indexing keyed by actual source SHA, Git revision and build configuration.
- Property-level end-to-end tracing across UI, API, DTO, ORM and database.
- Semantic reuse assessment with human-evaluated positive and negative examples.
- Graph-driven scope routing, reproducible runtime verification and human-adjudicated severity calibration.

## Snapshot comparison regression gates (v0.8.0)

Validate raw/enveloped graph JSON, SHA-256, bounded sizes, unsafe paths, duplicates, edge endpoints and symlinks. Compare unchanged and changed hashes, added/removed imports, line-only shifts, deleted-module before-impact, warning propagation, explicit detail truncation, and CLI round trips. Python `from pkg import a, b` must create separate indexed submodule edges. These are static candidate tests, not defect-detection precision measurements.
