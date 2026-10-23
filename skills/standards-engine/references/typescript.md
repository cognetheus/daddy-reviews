# TypeScript / JavaScript / Frontend Engineering Standards

## Version prerequisites
Identify TypeScript compiler, Node runtime, TSConfig target/lib/module settings, package manager, React/Next/Vue/Angular versions, JSX transform, server/browser boundary and lint settings before proposing syntax or configuration. Consult https://www.typescriptlang.org/tsconfig/strict and current framework documentation. Strict mode increases checks, but enabling it on a large legacy repo requires a migration plan and does not itself prove a defect.

## Type safety and contract integrity
- Check unsafe any, unchecked assertions, double casts, optional/null handling, unknown input data and exhaustive discriminated unions; distinguish code with runtime validation vs compile-time types only.
- Check array/dictionary indexing, key assumptions, type guards and boundary conversions; noUncheckedIndexedAccess is an option, not a blanket demand.
- Treat public DTOs, generated clients and wire serialization as contracts. Compare field names, optionality, dates, amounts, enum values, error shapes and versioning.
- Ensure server validation and object/tenant authorization; frontend type checking is not an access-control boundary.

## Modules and dependencies
- Confirm ESM/CommonJS/NodeNext resolution and actual bundler behavior. Check side-effect imports, import cycles, barrel-export effects, duplicated modules and conditionally loaded code.
- Dynamic/lazy import is useful for isolated expensive paths or bundle splits when supported; compare bundle/first-use latency and initialization behavior. Do not convert all imports.
- Look for existing fetch wrappers, retry/timeout handling, interceptors, query clients, API typings and shared utilities before adding libraries.
- Confirm direct/peer/dev dependency declarations, lockfile compatibility, package duplication and runtime bundle weight.

## React / Next.js and UI
- Distinguish local UI, form, URL, server cache, global client state and persisted state. Derived values normally should be computed rather than synchronized via effects.
- Review effects for external synchronization, cleanup, dependency correctness, request cancellation, stale closures and race conditions; not every computation belongs in an effect. Source: https://react.dev/learn/you-might-not-need-an-effect .
- Review custom hook responsibilities, mutable refs, stable identity, unnecessary memoization and duplicate fetching. Measure re-render cost before optimizing.
- Validate server/client boundaries, server rendering, hydration, route loading and caching against the exact framework version.
- Split oversized components by cohesive responsibility, reuse or test seam—not line count; avoid context-prop drilling without demonstrating real maintenance issues.
- Inspect accessibility, keyboard focus, semantic markup, contrast, responsive states, empty/loading/error/offline states, validation feedback and reduced motion.
- Review Core Web Vitals, code splitting, unnecessary fetch waterfalls, image/font loading, virtualization and render profiling; test on real workloads.

## Backend TypeScript
- For NestJS verify module providers/imports, guard order, pipes and runtime validation, interceptor behavior, dependency lifetimes and exception filters. Avoid business logic in controllers; distinguish application services from reusable domain services.
- For Fastify/Express verify plugin/middleware order, auth scopes, timeouts, handlers and error propagation, shutdown and resource cleanup, rate limits and payload limits.
- For events and queues first detect existing workers/brokers. Validate delivery semantics, retry/replay, idempotency, tenancy and transaction/outbox boundaries. A queue is not automatically superior to a direct function call.

## Verification
Typecheck actual projects; run existing ESLint/formatters and tests; inspect API schemas, bundles and traces. Confirm module resolution and runtime imports. Label source-only guesses explicitly. Avoid redundant comments already reliably caught by enforced tooling.

## Finding and decision contract

For any suspected defect, name the installed/runtime version, source or documentation version, reachable behavior, affected consumers, observed evidence, mitigation, and a concrete test. Separate confirmed defects from optional enhancements and unverified concerns. Before suggesting a new helper, abstraction, framework, state store, queue or SDK, locate existing equivalent capability. No arbitrary length/style thresholds and no finding quota.
