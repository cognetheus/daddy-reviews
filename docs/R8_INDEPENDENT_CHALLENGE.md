# R8.04b — Independent specialist counterexample challenge

R8.04b introduces an **opt-in, read-only** challenge of R8.02 source-grounded candidate findings. A separate specialist gets a bounded claim, not the original review transcript, and must use host-issued evidence from a fresh, independent R8.01 tool session to return one of `supported`, `refuted`, or `uncertain`. These labels remain **unverified model hypotheses**, not reproduced bugs or human evidence.

## Python API

```python
from pathlib import Path
from daddy_reviews.independent_challenge import (
    challenge_findings, local_challenge_provider,
)
from daddy_reviews.investigative_agents import investigate_with_specialists, local_investigation_provider

root = Path(".")
patch = Path("/tmp/change.diff").read_text()
original = investigate_with_specialists(
    root, patch, local_investigation_provider("YOUR_LOCAL_MODEL"),
    allowed_tools={"read_file"}, reviewers=("security",),
)
challenge = challenge_findings(
    root, patch, original,
    local_challenge_provider("YOUR_LOCAL_MODEL"),
    reviewer="code-quality", allowed_tools={"read_file", "find_tests"},
    max_challenges=4,
)
assert challenge["merge_action"] == challenge["github_publication"] == "none"
```

The original investigation and challenge are both explicitly opt-in. **No CLI integration is included in R8.04b.** This developer API does not run tests, infer actual model quality, or post GitHub comments. A localhost listener may proxy inference elsewhere.

## Host boundaries

- Source snapshot ID and patch SHA-256 must match R8.02; incomplete original reviewer runs, stale sources and changed diff lines abort before inference.
- Up to eight candidate challenges are selectable, four by default. Each uses at most three model turns and two read-only tools, with an isolated citation registry.
- A reviewer named in the original claim cannot independently challenge that same claim. Non-independent, denied, missing or partial tool results, malformed verdicts, forged evidence IDs, provider faults and budget exhaustion escalate rather than clearing the original issue.
- The challenger can cite read-only source anywhere within the snapshot, including a relevant test or call site. A citation proves inspected source, **not** the truth of a causal or refutation claim.
- Challenged hypotheses never mutate the original R8.02 report or the R8.04a verification queue.
- Outcomes contain no inferred confirmations. Publication and merge control remain `none`.

## Next remaining work

R8.04c: human-authored, independently authenticated verification artifacts (including source, reproducible test run, trust identity and audit provenance), plus explicit conflict resolution and human acceptance/rejection policy. A real-world, human-labeled evaluation corpus must measure false positives and missed defects before release promotion.
