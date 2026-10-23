# Authoritative engineering standards sources

This catalog contains reference entry points, not immutable assertions about current recommended versions. Recheck release notes and applicable versions when auditing a repository.

Verified research date: 2026-10-23.

- TypeScript TSConfig strictness: https://www.typescriptlang.org/tsconfig/strict
- React effects and derived state: https://react.dev/learn/you-might-not-need-an-effect
- Python 3.15 explicit lazy imports (PEP 810): https://peps.python.org/pep-0810/
- SQLAlchemy relationship loading and N+1 tradeoffs: https://docs.sqlalchemy.org/en/21/orm/queryguide/relationships.html
- EF Core efficient querying and split-query tradeoffs: https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying
- EF Core change tracking: https://learn.microsoft.com/ef/core/querying/tracking
- OWASP Application Security Verification Standard: https://owasp.org/www-project-application-security-verification-standard/
- OWASP API Security Top 10: https://owasp.org/API-Security/
- Docker Compose startup order: https://docs.docker.com/compose/how-tos/startup-order/
- Google engineering code review principles: https://google.github.io/eng-practices/review/reviewer/looking-for.html
- Spring Boot current documentation and BOM dependency management: https://docs.spring.io/spring-boot/
- Hibernate documentation: https://hibernate.org/orm/documentation/

## Rules for sourced recommendations

1. Confirm actual installed runtime/library version or explicitly state it is unknown.
2. Distinguish accepted language features from experimental proposals.
3. Capture exact documentation URL and access date in each substantive modern-standards finding.
4. Source guidance must be filtered through project requirements and workload evidence.
5. A new technique or newer dependency is not automatically preferable to existing reliable code.
6. Cite validated runtime behavior when source guidance is insufficient to decide an optimization.
