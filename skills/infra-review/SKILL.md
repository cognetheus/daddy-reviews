---
name: infra-review
description: Docker, DevOps and Operational Reliability Review. Evidence-first, calibrated review that considers existing repository capabilities.
---

# Docker, DevOps and Operational Reliability Review

## Activation and responsibility

Inspect Docker multi-stage build, pinning, health/readiness, signals, graceful shutdown, non-root runtime, runtime env, network/isolation, volumes/data durability, orchestration dependency startup, workers, migrations, build layers, reproducibility, CI tests, rollback, IaC, logs/metrics/traces and backup restore. Run runtime checks only in an approved sandbox with safe resource limits.

## Non-negotiable engineering nuance

Reading Compose does not establish that containerization works. Test boot, ready, restart, dependency outages, state retention and migration when authorized. Reuse existing processes and infrastructure; do not impose Kubernetes or new monitoring services without objective triggers.

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
