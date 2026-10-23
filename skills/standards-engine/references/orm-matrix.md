# ORM-Specific Review Decision Matrix

## Universal invariant: investigate generated operations, not only fluent API appearance
For every ORM first identify the precise installed version, driver, dialect, database version and migration tool. Inspect actual queries (SQL or document operations), indexes, row cardinality, transaction isolation, DB constraints and tenancy model. Trace UI input -> API validation -> DTO -> domain command -> ORM mapping -> stored representation -> query -> response -> UI.

## TypeScript ORM families
- Prisma: query projection (select/include), relation cardinality, generated client/schema alignment, connection pooling, nested writes, transactions, migration drift and API version. Know whether Prisma's chosen relation loading behavior is configured and supported in this release.
- Drizzle: SQL-first schema typing and actual SQL, joins, transactions, migrations, prepared statements, driver behavior and nullable field transforms. Avoid assuming generated compile-time types guarantee runtime validation.
- TypeORM: DataSource lifecycle, EntityManager/QueryRunner transactions, repository/entity boundaries, relations/load strategies, partial saves, lazy relationships, migration schema sync in production and connection ownership.
- MikroORM: Unit of Work identity map, request-scoped entity manager and forks, flush consistency, populate strategy, transactional boundaries, cascade behavior and migrations.
- Sequelize: model associations/aliases, scoped queries, paranoid soft-delete behavior, transactions/AsyncLocalStorage context, migrations, eager relation loading and native SQL injection risk.
- Mongoose (ODM): schema casting/defaults, lean query semantics, hooks/middleware behavior, discriminator/array updates, transaction support by MongoDB topology and document validation.

## Python ORM families
- SQLAlchemy: sessions/identity map, autoflush, async/sync driver correctness, selectinload/joinedload/raiseload, schema migrations through Alembic, row uniqueness and transaction scope. See https://docs.sqlalchemy.org/en/21/orm/queryguide/relationships.html .
- Django ORM: queryset evaluation, select_related/prefetch_related, iterator, bulk operations, transaction.atomic, migrations and DRF serializer writes. Queryset tenant scoping can be bypassed; test negatives.

## .NET / Java ORM families
- EF Core: tracking/identity resolution, split vs single queries, projection, Include semantics, optimistic concurrency, DbContext scopes, SaveChanges and migration compatibility. Sources: https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying and https://learn.microsoft.com/ef/core/querying/tracking .
- Dapper: explicit SQL parameterization, mapping from query aliases, missing/null columns and transaction handling; don't treat it as tracking ORM.
- Hibernate/JPA: session persistence context, flush mode, lazy proxies, entity graphs/joins, fetch depth/batching, cascade/orphan removal, dirty checking, optimistic locks, query projections, bulk mutation and schema management.
- Spring Data JPA: repository methods and query derivation, pageable/sorting constraints, entity graph usage and transaction proxies; it builds on a JPA provider, so check both layers.

## Critical cross-layer mapping scenarios
- DTO accepts a field but mapper drops it before insert/update.
- API uses optional field while DB forbids null, leading to silent default or failed transaction.
- Monetary minor units vs major units, timezone conversion, enum normalization, camelCase/snake_case.
- Update bypasses object-level authorization; mass assignment changes protected data.
- A migration renames a column/event property without updating consumers and rollback.
- Async worker persists side effect then retries and duplicates it without a business idempotency key.

## Verification
Inspect typed mapping, migration files, generated SQL, database constraints, explain plans and runtime instrumentation. Use transaction and tenant-negative integration tests. Distinguish a query-shape candidate from measured N+1 cost. Report only supported issues and design tradeoffs proportionate to workload.

## Finding and decision contract

For any suspected defect, name the installed/runtime version, source or documentation version, reachable behavior, affected consumers, observed evidence, mitigation, and a concrete test. Separate confirmed defects from optional enhancements and unverified concerns. Before suggesting a new helper, abstraction, framework, state store, queue or SDK, locate existing equivalent capability. No arbitrary length/style thresholds and no finding quota.
