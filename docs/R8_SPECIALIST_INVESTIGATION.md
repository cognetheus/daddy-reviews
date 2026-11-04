# R8.02 — Specialist agent investigation harness

**Delivered:** opt-in, bounded multi-turn specialist reasoning over R8.01's seven permissioned read-only tools. This is **actual model → host tool → model orchestration**, not merely adding retrieved code to a single prompt. It preserves the R1–R7 evidence-first policies. It never writes source, posts GitHub reviews, approves or blocks merges.

## Run

```bash
# Requires an explicitly started local Ollama-compatible HTTP endpoint
# The diff's added lines must exactly match the current worktree.
daddy-reviews ai-investigate --root . --base origin/main --head HEAD \
  --model YOUR_LOCAL_MODEL \
  --allow-tool read_file --allow-tool find_references \
  --allow-tool query_dependencies --allow-tool find_tests \
  --investigation-reviewers 3 \
  --investigation-rounds 4 \
  --investigation-tools 3 \
  --agent-parallel 2 --agent-timeout 30

# Completely read-only, deterministic baseline remains available separately
daddy-reviews review --root . --base origin/main --head HEAD
```

Without `--model`, no local inference begins. Without `--allow-tool`, there is **no tool access**, even if a model asks for it. Each `--allow-tool` must name an R8.01 capability; there is no shell, terminal, arbitrary HTTP, filesystem write, Git mutation, GitHub publication, or test execution tool.

## Protocol

The harness uses a strict JSON-turn contract. Per turn, the specialist may emit exactly one **read-only tool request** or one **final findings** response. Nothing else is executable.

```json
{"kind":"tool","call":{"tool":"read_file","path":"src/auth.py","start_line":1,"end_line":20}}
```

After a successful tool invocation, the host provides a bounded JSON tool response and unique **host-issued evidence IDs** bound to source snapshots. The model may then emit:

```json
{"kind":"final","findings":[{"rule":"AUTH-01","path":"src/auth.py","line":7,"claim":"Concrete bug hypothesis","evidence":"Why the path fails","severity":"medium","citations":["E1"]}]}
```

**Citation acceptance rules:** findings must point to a changed **added** line; the citation ID must have actually been issued after a successful tool read; at least one cited source span must overlap the finding line in the same file. The host independently re-checks each tool span's snapshot ID, original file SHA-256, path and line range before assigning IDs. Citations are **source evidence of what the code says**, not independently proven defects.

## Specialist isolation and life cycle

1. Build a bounded R1 review packet. Capture one R7.01 source snapshot and validate every added patch line against the **actual current source bytes** before contacting the model. This detects stale/foreign diffs, but is not a signed Git commit attestation.
2. Select up to six known specialist roles from the existing review tier. The CLI default runs at most three specialists in two parallel workers; specialist selection and output ordering remain deterministic.
3. Give every specialist its **own** R8.01 session and allowlist, per-session audit log, tool-call counter and citation ID namespace. Specialist A cannot reuse Specialist B's evidence IDs.
4. For each model turn, enforce a strict JSON response schema, no extra action fields and bounded prompt/response sizes. Tool requests are validated using the existing typed `ToolRequest` API and never forwarded as executable shell text.
5. Execute read-only tools only when permission has been granted. Failed/denied/partial/stale tool outcomes terminate that specialist as **failed**, never as a clean review.
6. Validate final findings against changed lines and host-issued cited source spans. The host assigns `verification: unverified`, ignoring any model attempt to self-confirm. An unauthorized command, ungrounded citation, oversized output or model error fails closed.
7. Merge completed specialist candidates through the deterministic `adjudicate` function. `merge_action` and `github_publication` always stay `none`. Publication remains a separate explicit and guarded workflow.

## Resource limits

| Resource | Maximum |
| --- | --- |
| Diff input | 24 KB |
| Prompt transport per turn | 60 KB |
| Model JSON response per turn | 32 KB |
| Specialist rounds | 5 (default 4) |
| Tool calls per specialist | 4 (default 3) |
| Specialist roles | 6 (default maximum 3) |
| Parallel specialist workers | 3 (default 2) |
| Findings per specialist | 8 |
| Citation IDs per finding | 6 |
| Per-model HTTP timeout | 120 seconds maximum (default 30) |

The underlying R8.01 tool session also limits source line ranges, dependency depth, output bytes and total tool calls. A real-time **global** deadline is not yet enforced; the upper bound is the finite number of per-turn model requests plus bounded tool calls. Provider usage tokens are recorded only when actually returned in the Ollama transport envelope; zero-cost and zero-token claims are not fabricated.

## Security / model-native limits

- No model output can grant itself new tools, invoke a shell, execute a project test, post a comment, or assert merge authority.
- An untrusted prompt in a patch, source file, Git commit subject or tool response remains **data**, not a privileged instruction. Invalid action schemas fail closed.
- Localhost-only inference is enforced by URL checks and redirects are rejected. **A localhost server may itself be a proxy**; the harness does not attest that inference compute or data processing remain physically local.
- Diff/current-worktree matching requires source SHA-256 agreement for all added lines before model invocation. Deleted-only and binary changes are not supported by this investigator path, even though deterministic review remains available.
- Each specialist failure is recorded without crashing sibling reviewers. An incomplete specialist makes overall status `incomplete`; no false clean review is reported. Findings remain unverified even with valid source citations.
- The tool response is passed to the model as untrusted JSON; it cannot alter the host's source snapshot or permissions. The reviewer must still substantiate causal claims beyond citing a file.

## Developer API

```python
from pathlib import Path
from daddy_reviews.investigative_agents import (
    investigate_with_specialists, local_investigation_provider,
)

provider = local_investigation_provider('YOUR_LOCAL_MODEL')
report = investigate_with_specialists(
    Path('.'), patch_text, provider,
    allowed_tools={'read_file', 'find_references'},
    reviewers=('security', 'code-quality'),
    max_rounds=4, max_tools_per_reviewer=3, max_workers=2,
)
assert report['merge_action'] == report['github_publication'] == 'none'
```

## Acceptance / verification

`tests/test_investigative_agents.py` exercises real two-turn provider/tool/citation sequences, source hash and location correlation, unknown/forged citations, unauthorized tools, schema injection, unsupported line findings, stale/mismatched diff rejection, parallel specialist isolation, timeout/failure isolation, round/tool ceilings, read-only disposition, and a local mock Ollama HTTP server including redirect rejection and CLI invocation. This is an **integration test of the transport and deterministic harness**, not a benchmark of actual model defect-detection quality.

**Next:** R8.03 should introduce a human-labeled investigation evaluation corpus and replayable tool transcripts. Measure false-positive rates, missed defects, context/call consumption and performance under permission-denied and tool-error scenarios before promoting broader autonomous review operation.
