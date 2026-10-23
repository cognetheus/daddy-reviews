# Daddy Reviews

**Evidence-first software engineering review infrastructure.**

This repository starts with a working Phase 0–1 foundation: deterministic task-aware review planning, blast-radius indicators, read-only Python repository reconnaissance, a conservative candidate detector, a calibrated finding schema, and tests. It is **not** yet a complete multi-language semantic reviewer or GitHub PR bot.

## Quick start

```bash
python -m pip install -e . pytest
pytest -q
daddy-reviews plan --task 'Review PR' --changed src/auth/tenant.py
daddy-reviews inventory --root .
daddy-reviews audit --root . --changed src/daddy_reviews/core.py
```

All commands are read-only. Output is JSON. Findings from static heuristics are **unverified candidates**, not proof of defects. No GitHub posting or modifications are performed.

## Core principles

- Review intent first; choose depth according to actual blast radius.
- Review PR diffs before following relevant consumers and cross-layer contracts.
- Investigate before classifying; severity, verification, and disposition are separate.
- No quotas for bugs or critical findings; zero findings is a valid outcome.
- Search for existing repository capabilities before recommending new implementations.
- Prefer official, version-appropriate standards to trendy recommendations.
- Separate changed defects from pre-existing debt and theoretical risks.
- Independent verification and human authorization precede publication/remediation.

## Current scope

- `plan`: task routing and coarse risk signals based on filenames (heuristics, not proof).
- `inventory`: Python symbol inventory and language-extension counts.
- `audit`: preliminary Python silent-catch candidates; intentionally low severity and unverified.
- Skills are extensive operator guidance for agent-assisted review; they do **not** imply corresponding automated checks are implemented.

See `docs/ROADMAP.md` and `skills/` for the staged design and detailed operator instructions.
