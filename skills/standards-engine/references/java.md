# Java / Spring Boot / JPA / Hibernate Engineering Standards

## Version prerequisites
Inspect Java language/runtime target, Spring Boot BOM and starters, Hibernate/Jakarta Persistence versions, Maven/Gradle configuration and effective dependency tree. Managed dependency declarations without explicit version are not unversioned installed packages. Check release notes before recommending language APIs or migrations.

## Language and boundaries
- Keep controllers transport-focused, application services cohesive and domain rules in appropriate aggregates/domain services. Do not force DDD scaffolding into straightforward CRUD.
- Check immutability where helpful, validated constructors, null contracts, defensive copies, exception taxonomy, resource closure and concurrency assumptions.
- Modern syntax and virtual threads depend on runtime/tooling support and workload. Do not recommend virtual threads indiscriminately, especially with pinning/blocking or library compatibility uncertainties.

## Spring contracts
- Investigate dependency injection, bean initialization and scope, validation groups, configuration binding, method security, transaction management, exception handlers, async execution and orderly shutdown.
- Spring proxy semantics matter: internal self-invocation may bypass advice such as transactional boundaries. Verify the actual proxy and test before reporting.
- Confirm response DTO field mappings, serialization policy, filter/security chain placement, pagination and client API compatibility.
- Event publication requires explicit transaction/rollback semantics; distinguish local Spring application events from durable integration events.
- Existing Kafka/Rabbit/stream/worker components must be checked before recommending a new messaging library or service.

## Hibernate/JPA
- Inspect persistence context lifetime, dirty checking, lazy proxies, N+1 queries, JOIN FETCH vs batching/entity graphs, collection pagination, duplicate rows and flush/transaction semantics.
- Analyze database query plans and representative cardinalities; do not universally eager-fetch associations.
- Verify tenant filters, entity identity, optimistic locking, schema migration, orphan removal and cascade behavior under failures.
- For Spring Data repositories, distinguish derived query semantics, custom SQL/JPQL, DTO projections, query specifications and stream resource closure.

## Gradle/Maven dependencies and verification
- Determine effective graph (including BOM/dependencyManagement and transitive versions), scope, vulnerable reachability, dependency convergence and supported Java baseline.
- Build and test on specified JDK versions; run Spring integration and database tests for transactions, repositories, auth and event delivery.
- Findings require reachable failure and source evidence; separate speculative style guidance from demonstrated regressions.

## Finding and decision contract

For any suspected defect, name the installed/runtime version, source or documentation version, reachable behavior, affected consumers, observed evidence, mitigation, and a concrete test. Separate confirmed defects from optional enhancements and unverified concerns. Before suggesting a new helper, abstraction, framework, state store, queue or SDK, locate existing equivalent capability. No arbitrary length/style thresholds and no finding quota.
