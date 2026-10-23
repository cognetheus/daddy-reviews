---
name: daddy-reviews
description: Evidence-first engineering intelligence with adaptive review scope, repository reuse discovery and calibrated findings.
---

# Daddy Reviews

Choose task mode and scope with `review-orchestrator`. For a PR begin with `pr-review`, then select relevant specialists; do not run every specialist automatically. `repository-intelligence` is required before recommending new service/helper/module/dependency. Route every substantive candidate through `findings-verification`. Load technology or domain specialists progressively. Never manufacture findings; a clean conclusion is valid. Distinguish severity, evidence, confidence, actual blast radius and disposition. Do not claim runtime checks were performed unless executed. Do not publish or change code without user authorization.

## Skills

- `review-orchestrator`: task routing and scope boundaries
- `pr-review`: changed code first and wider blast-radius checks where relevant
- `repository-intelligence`: capability index and anti-reinvention
- `findings-verification`: independent disproof, severity, deduplication and stopping
- `architecture-review`: DDD, events, queues, consistency and architecture fitness
- `frontend-review`: hooks, state, UI, UX, accessibility, frontend performance
- `backend-review`: services, APIs, error handling, integrations and resilience
- `orm-review`: persistence, ORM practices, field mapping and migrations
- `dependency-audit`: versions, libraries, duplicates, vulnerabilities and upgrade safety
- `security-review`: authorization, tenancy, API and supply chain security
- `standards-engine`: detect manifest-declared stack, load version-aware TS/Python/.NET/Java and ORM references (not automatically confirmed installed versions)
- `infra-review`: Docker, CI/CD, observability, runtime and recovery

See `docs/ROADMAP.md`. CLI coverage is deliberately smaller than the skill playbooks; do not confuse guidance with implemented automatic analyses.

## v0.4.0 tools

`daddy-reviews review` now includes partial JS/TS import-linked call candidates alongside Python AST analysis. `daddy-reviews contracts --base-contract OLD --head-contract NEW` compares OpenAPI 3 JSON snapshots. Treat both as hypotheses requiring independent verification; neither supports an automatic PR approval or critical finding.

## Calibration regression fixtures (v0.5.0)

Use `daddy-reviews evaluate --dataset evals/baseline.json` to test deterministic rule candidate behavior. The CLI measures syntax candidate accuracy against handcrafted labels and clean-fixture false-alarm rate; it does **not** establish correctness of actual bug detection, severity, or architecture decisions. Any new reviewer rule must add clean and positive fixtures and be checked for impact on false positives before promotion.

## Module graph (v0.6.0)

`daddy-reviews graph` and `daddy-reviews capabilities` provide bounded, read-only static candidate indexes to guide repository-wide reuse and blast-radius investigation. Review packets include direct/transitive module impact, but import edges are not validated runtime calls. Use evidence verification and domain context before any consequential conclusion.
