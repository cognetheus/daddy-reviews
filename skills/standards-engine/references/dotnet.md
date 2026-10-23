# C# / ASP.NET Core / EF Core Engineering Standards

## Version prerequisites
Determine installed SDK, TargetFramework(s), nullable settings, language version, ASP.NET hosting model, EF Core package versions and central NuGet package management. Do not assume runtime features from the project XML alone. Prefer current official Microsoft docs and real build output.

## Language and lifecycle
- Inspect async/await propagation, fire-and-forget exceptions, Task cancellation, CancellationToken forwarding, resource disposal/IAsyncDisposable and concurrent dictionary/thread safety.
- Check DI lifetimes: singleton must not capture scoped services; distinguish transient/scoped/singleton ownership, hosted-service scopes and DbContext lifetime.
- Ensure nullable/reference contracts reflect validated domain behavior; avoid suppression operators that conceal missing validation.
- Keep controllers/minimal API handlers focused on transport/auth/validation; respect domain boundaries and avoid unnecessary generic repositories over ORM capabilities.

## ASP.NET Core APIs and resilience
- Middleware ordering, authentication vs authorization, object-level tenant checks, model binding, ProblemDetails/error shaping, antiforgery/CORS policy and consistent rate limiting.
- Validate outbound HttpClientFactory usage, timeouts, cancellation, retry policies, handler lifetimes and circuit breaker justification; do not create parallel HTTP clients if application already has one.
- Verify app shutdown/startup, worker cancellation, hosted services and container health endpoints. A request-triggered background Task without durable ownership can lose work.

## EF Core and Dapper
- EF Core tracking/no-tracking is situational. Tracking may preserve identity resolution and support updates; AsNoTracking can reduce overhead on read-only paths. Source: https://learn.microsoft.com/ef/core/querying/tracking .
- Review query projections, database constraints, generated SQL, eager/split-query tradeoffs, lazy-load N+1, cartesian expansion, pagination, optimistic concurrency, SaveChanges atomicity and transaction scopes. Source: https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying .
- AsSplitQuery can reduce cartesian explosion but may add round trips and cross-query consistency concerns; do not prescribe globally.
- Assess EF migrations as deployed contracts: expand/backfill/contract, rollback and mixed-version compatibility.
- Dapper relies on explicit SQL and mapping: inspect parameter binding, missing aliases/columns, nullability, multi-mapping, transactions and injection boundaries.

## Security, testing and performance
- Test cross-tenant reads/writes with negative cases, including background jobs. Verify authorization beyond endpoint-level policy.
- Benchmark representative EF queries via captured SQL and explain plans; use profiling before changing allocations or pooling.
- Run dotnet build, analyzers, tests and container smoke tests when authorized. Do not claim clean behavior from a style report alone.

## Finding and decision contract

For any suspected defect, name the installed/runtime version, source or documentation version, reachable behavior, affected consumers, observed evidence, mitigation, and a concrete test. Separate confirmed defects from optional enhancements and unverified concerns. Before suggesting a new helper, abstraction, framework, state store, queue or SDK, locate existing equivalent capability. No arbitrary length/style thresholds and no finding quota.
