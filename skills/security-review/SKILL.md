---
name: security-review
description: API, Application and Supply-Chain Security Review. Evidence-first, calibrated review that considers existing repository capabilities.
---

# API, Application and Supply-Chain Security Review

## Activation and responsibility

Trace authentication, session and token lifetimes, object/property authorization, tenant isolation, input validation, output encoding, injection risks, SSRF, CSRF, XSS, origin/CORS, secrets, webhook signatures, replays, rate limits, logging redaction, role boundaries and transitive dependency risks. Use OWASP ASVS/API Top 10 as verification baselines with version provenance.

## Non-negotiable engineering nuance

Clearly separate reachable exploit, defense-in-depth recommendation and unverified hypothesis. Do not expose secrets in examples or tests. Use controlled negative tests and least-privilege review tooling. Shared authorization edits may justify full system review even if one line.

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
