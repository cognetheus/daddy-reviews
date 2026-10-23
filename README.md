# Daddy Reviews

**Evidence-first engineering intelligence for PRs and repository review.**

![CI](https://github.com/cognetheus/daddy-reviews/actions/workflows/ci.yml/badge.svg)

v0.2.0 now includes a working **read-only Git diff evidence collector**, conservative Python AST symbol and reuse reconnaissance, risk-aware task routing, and a structured findings contract. This is not yet a full autonomous PR reviewer or a verified multi-language analysis platform.

## Install and test

\`\`\`bash
python -m pip install -e . pytest
pytest -q
\`\`\`

## Usage

\`\`\`bash
# Diff-first evidence packet for a local PR branch (base ref must exist locally)
daddy-reviews review --root . --base origin/main --head HEAD

# Offline review using an existing Git unified patch
daddy-reviews review --root . --diff-file /tmp/change.patch

# Earlier commands remain available
daddy-reviews plan --task 'Review PR' --changed src/auth/tenant.py
daddy-reviews inventory --root .
daddy-reviews audit --root . --changed src/daddy_reviews/core.py
\`\`\`

Every command is read-only, returns JSON, and performs no GitHub posting or repository writes. An evidence packet contains changed hunks/line numbers, initial risk routing, Python changed symbols, textual possible references, potential structurally duplicated Python function bodies, matching test-file paths, and preliminary swallowed-exception candidates restricted to changed lines.

**Evidence limitations matter:** textual matches are not an accurate call graph; function-body similarity does not justify automatic consolidation; a test filename is not verified test coverage; a zero-finding result is not a merge approval. All heuristic findings remain unverified until confirmed using appropriate code/context/runtime evidence.

## Skills and roadmap

- [skills/SKILL.md](skills/SKILL.md) — skill router and evidence policy
- [skills/pr-review/SKILL.md](skills/pr-review/SKILL.md) — diff-first and bigger-picture PR review protocol
- [docs/REVIEW_PROTOCOL.md](docs/REVIEW_PROTOCOL.md) — operational methodology and limitations
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — implemented architecture and trust boundaries
- [docs/ROADMAP.md](docs/ROADMAP.md) — staged cross-language implementation roadmap

The rest of \`skills/\` contains specialist guides for frontend, backend, security, ORM, dependencies, infrastructure, architectural review, finding verification, and repository intelligence.

## Engineering principles

1. Understand intent and existing code before recommending new work.
2. PR-first, then meaningful consumer and architectural impact analysis.
3. Evidence before severity; no quotas for findings or critical bugs.
4. Version-aware guidance, authoritative standards and clear uncertainty.
5. No source changes or GitHub review publication without explicit authorization.

## Attribution

Published exclusively under the connected \`cognetheus\` account without co-author trailers.
