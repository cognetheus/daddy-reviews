---
name: repository-intelligence
description: Repository Capability and Reuse Audit. Evidence-first, calibrated review that considers existing repository capabilities.
---

# Repository Capability and Reuse Audit

## Activation and responsibility

Inventory languages, versions, modules, symbols, constructors, exports, imports, helpers, shared hooks, services, clients, schemas, queue/exchange/job definitions, auth, cache, logging, error abstractions, tests and infrastructure. Build symbol, dependency and usage graph. Compare overlap candidates by contracts, callers, domain meaning, edge cases and change cadence.

## Non-negotiable engineering nuance

Code similarity does not prove redundant behavior. Consider domain separation, offline preview vs authoritative backend calculation, security boundaries, transaction context and local dependency cost before extracting or consolidating. Prefer composition and existing conventions to new frameworks.

## Mandatory evidence contract

For each candidate: record repository-relative location, observed behavior, reproducible evidence (or state unverified), reachable impact, existing mitigation, installed stack versions, introduced/pre-existing/unknown status, severity distinct from confidence, and disposition. Search relevant existing implementations before proposing a new one. A passing review with zero actionable findings is valid. Never invent a critical issue or claim tests ran when they did not.

## Review workflow

1. Establish user intent, requirements, and the changed scope. Distinguish a PR, bug, feature, incident, migration, and full audit.
2. Examine affected source and direct consumers. Use compiler, language-server, symbols, schemas, and existing tests before speculation.
3. Escalate to dependency or system review only for reachable high-impact paths, interface/contract change, cross-module behavior, or unresolved material risk.
4. Verify suspected findings independently: attempt disproof, check defenses, constraints, consumers, versions, and possible false positives.
5. Calibrate actual consequence; do not assign severity solely from a code smell, small textual diff, or theoretical extreme.
6. Deduplicate by root cause. Separate actionable introduced defects from pre-existing debt and optional improvements.
7. Return precise fixes and verifying tests. Do not change source or post GitHub comments without authorization.

## Stop conditions

Stop when the relevant behavior, contracts, and callers have been examined and additional exploration is unlikely to change the decision. Preserve material uncertainties as unverified; escalate severe uncertainties rather than pretending they were resolved. Avoid repeated recursive audit loops.

## Output format

Provide: scope reviewed; relevant installed versions and standards; verification performed and not performed; findings separated by verified status and PR attribution; exact references and underlying root cause; existing reuse opportunities; prioritized remedial actions and tests; conclusion including clean outcome if appropriate. State the evidence necessary to upgrade an uncertain candidate into a confirmed issue.

## Executable graph and capability discovery (v0.6.0)

Run `daddy-reviews graph --root . --changed PATH --max-depth 3` before evaluating import blast radius. Inspect `direct_consumers`, `transitive_consumers`, and each `via` path. If a high-impact contract crosses a missing dynamic, generated, or compiler-managed boundary, expand manually instead of assuming isolation. Run `daddy-reviews capabilities --root . --query 'business operation'` to find initial Python/JS/TS symbol candidates, then inspect inputs/outputs, side effects, transaction boundaries, actual consumers, and domain ownership before proposing reuse.

**Never** label import cycles, similarity hits, or transitive import paths automatically as bugs, blocked PRs, or redundant implementation. `graph` supports explicit JSON export via shell redirection; a saved snapshot is not authenticated to a commit unless the caller pins/verifies that revision. Boundaries: 4,000 files, 350 KB/file, 24 MB total indexed source, depth cap 8; report truncation rather than creating false completeness claims. See `docs/GRAPH.md`.

## Local TS/JS aliases (v0.7.0)

Module graph alias edges tagged `js_tsconfig_alias_*` reflect explicit local `paths`/`baseUrl` declarations only. Verify the actual project tsconfig inheritance, compiler/bundler resolution, source inclusion, and exports before relying on these edges. Unsupported configs and ambiguous targets produce warnings/abstention. Do not equate a resolved module with an invoked symbol or verified runtime dependency.

## Historical graph delta (v0.8.0)

Capture `daddy-reviews graph --root REVISION_WORKTREE > graph.json` separately for each revision and compare using `daddy-reviews graph-diff --before-graph BEFORE --after-graph AFTER`. Treat modified SHA-256 files, import-edge changes, and new/lost reverse consumer candidates as investigation leads only. Never infer commit provenance, actual runtime reachability, a regression, or a blocker from a snapshot delta. Graph-diff is read-only and is **not** an incremental cache; source must be rescanned for each snapshot.


## Cache-assisted graph inspection (v0.9.0)

For repeated inspections of an unchanged working tree, an explicitly requested local cache can avoid reparsing: `daddy-reviews graph --root . --cache-file /tmp/daddy-graph-cache.json`. Inspect the returned `cache.status`; `bypassed`, `volatile`, and `write_failed` are not cache hits. This is **whole-tree invalidation**: changed source/config always triggers a complete rebuild. Do not use cache presence, source hashes, or static edges as proof of Git revision authenticity, functional equivalence, or runtime reachability. Do not write caches unless the user/workflow permits local file writes.


## Python symbol-level reconnaissance (v1.1.0)

For a changed top-level Python function/class, run `daddy-reviews symbol-impact --root . --changed path/to/module.py --symbol function_name` after module graph inspection. Inspect each AST-linked call candidate in its enclosing scope and confirm import resolution, actual runtime binding, call behavior and tests before claiming impact. Rebinding, shadowing, nested imports, reexports and dynamic invocation can invalidate or hide matches. No positive or negative result is proof of runtime reachability; do not assign severity from these links alone.
