---
name: orm-review
description: ORM, Database and Contract Integrity Review. Evidence-first, calibrated review that considers existing repository capabilities.
---

# ORM, Database and Contract Integrity Review

## Activation and responsibility

Identify actual ORM and version: Prisma, Drizzle, TypeORM, MikroORM, Sequelize, SQLAlchemy, Django ORM, EF Core, JPA/Hibernate or Spring Data. Trace UI fields through DTO and serialization into model, migrations, stored rows, response and UI. Verify missing mappings, null/default conversions, auth on writable fields, schema compatibility, transactions, locking, pagination, N+1, eager/lazy loads, indexes, bulk operations and connection pools.

## Non-negotiable engineering nuance

Do not prescribe eager loading or a new index without workload evidence; query plans and representative load are stronger than code style. Respect transaction isolation and safe expand/backfill/contract migrations. Field renames can have high blast radius through external contracts.

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
