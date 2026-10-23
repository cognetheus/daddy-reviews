# Python / FastAPI / Django Engineering Standards

## Version and interpreter accuracy
Check Python interpreter versions from pyproject, deployment images and actual execution; also identify FastAPI/Pydantic, Django/DRF, SQLAlchemy, Python typing checker and formatter versions. Use https://docs.python.org/3/ , accepted PEPs and framework documentation. Do not recommend unsupported syntax because it is newer.

## Imports and lazy imports
- Conventional imports belong at module level unless import cycle, optional dependency, expensive startup, feature gating or runtime behavior justify otherwise.
- PEP 810 defines explicit lazy imports for Python 3.15. Verify the actual interpreter before recommending lazy syntax; it is not automatically compatible with Python 3.10–3.14. Official source: https://peps.python.org/pep-0810/ .
- A lazy import shifts import-time exceptions and side effects to first access and can affect plugin registration, app startup and diagnostic clarity. Profile first-use overhead and initialization before changing behavior.
- Distinguish module import cache, package import side effects and circular-import symptoms from actual performance bottlenecks.

## Types, validation and data mapping
- Apply modern typing idioms supported by target Python, including Optional/union, generics and typed protocols where useful; do not turn internal style preferences into blockers.
- Parse external inputs with runtime validation; annotations alone provide no runtime guarantee. Keep domain models, persistence models and response DTOs distinct when responsibilities differ.
- Trace aliasing, field inclusion/exclusion, Pydantic model configuration, omitted fields, Enum serialization, UTC/timezone conversion and decimal currency arithmetic.

## Async and concurrency
- Look for blocking I/O inside async handlers, synchronous drivers in event-loop paths, unbounded gather or concurrency, missing cancellation/timeouts and background task lifecycle.
- Async does not make CPU-heavy work nonblocking. Use existing workers/jobs or a thread/process strategy based on requirements and failure guarantees.
- For FastAPI investigate lifespan and dependency scopes, security dependencies, exception handlers, middleware ordering and request-bound session lifetimes.
- For Django investigate queryset evaluation, select_related/prefetch_related, async safety, transactions, DRF serializer writes and querysets tenant scoping.

## Error handling and correctness
- Bare except/pass around mission-critical persistence is suspicious, but best-effort optional tasks might intentionally discard errors. Determine desired failure semantics before reporting.
- Inspect exception chaining and translation boundaries, structured logs, correlation IDs, safe HTTP errors, cleanup, context managers and rollback.
- Scope DB sessions and transactions to correct atomic boundaries. Verify retries are idempotent; avoid retrying all exceptions.

## SQLAlchemy / Celery
- SQLAlchemy 2.x Session identity map, autoflush, relationship loaders, eager loading/selectinload and transaction behavior require version-specific checking. Source: https://docs.sqlalchemy.org/en/21/orm/queryguide/relationships.html .
- For N+1 issues show actual query count, cardinality and proposed load strategy; joinedload vs selectinload has tradeoffs.
- Celery or equivalent workers need durable result semantics, idempotency, visibility into retries, poison handling, and clear distinction between broker acknowledgement and business commit.

## Verification
Run project-specific Ruff/Black/mypy/pyright/pytest if configured, integration tests with real ORM/session behavior, import profiling when proposed, and query instrumentation. Never assume tests ran because a test file exists.

## Finding and decision contract

For any suspected defect, name the installed/runtime version, source or documentation version, reachable behavior, affected consumers, observed evidence, mitigation, and a concrete test. Separate confirmed defects from optional enhancements and unverified concerns. Before suggesting a new helper, abstraction, framework, state store, queue or SDK, locate existing equivalent capability. No arbitrary length/style thresholds and no finding quota.
