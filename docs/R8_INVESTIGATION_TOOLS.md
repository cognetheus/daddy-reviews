# R8.01 — Permissioned read-only investigation tools

**Delivery:** seven typed tools in `src/daddy_reviews/investigation.py`, exposed through both a Python API (`InvestigationSession.execute(ToolRequest(...))`) and explicit CLI `daddy-reviews investigate`. This is a standalone, deterministic investigation interface; **it is not yet an autonomous agent tool loop**. R8.02 will integrate it into bounded specialist review orchestration.

## Tool contracts

| Tool | Required argument(s) | Results | Precision boundary |
| --- | --- | --- | --- |
| `read_file` | `path`, optional `start_line`/`end_line` | Source text, line bounds, SHA-256 span | Source text remains untrusted; no file modification |
| `find_symbol` | `path`, `symbol` | AST/compiler-resolved target declaration, adapter status | Python AST remains candidate; TS/javac/Roslyn resolution remains within each adapter's known scope |
| `find_references` | `path`, `symbol`, optional `limit` | Source-backed reference set, total/truncation | Never proves runtime call reachability |
| `query_dependencies` | `path`, optional `depth`/`limit` | Bounded inbound/outbound import and cross-layer candidate edges | Incomplete if evidence display/output ceiling reached; not a whole-program graph |
| `inspect_contract` | `path`, `route`, `method` | Literal OpenAPI 3.x operation and bounded JSON field summaries | Only indexed conventional `openapi.json` / `openapi-v3.json` / `swagger.json`; not live API verification |
| `find_tests` | `path`, optional `depth`/`limit` | Tests connected via actual import/call graph edges | No speculative filename-only matches; absence of results is not proof of missing tests |
| `inspect_history` | `path`, optional `limit` | Local Git HEAD, hashes, author date, subject of commits affecting path | No remote lookup; git subjects untrusted; history is not proof of behavior |

Tool output format is `daddy-reviews-investigation-v1`. Every response has `tool`, `status`, `snapshot_id`, bounded `data`, `evidence`, warnings, `trust: untrusted_repository_source`, `runtime_calls_proven: false`. Successful calls additionally carry the request/byte budget state. Statuses include `complete`, `partial`, `not_found`, `unavailable`, `incomplete`, `stale`, `denied`, `budget_exceeded`. **Only `complete` returns CLI exit 0**. Every other status returns exit 2, preserving machine-readable JSON.

## Example CLI

```bash
# Read-only capability must be explicitly granted; without --allow-tool it is denied
daddy-reviews investigate --root . --tool read_file --allow-tool read_file \
  --path src/auth.py --start-line 1 --end-line 30

# Python symbol declaration
daddy-reviews investigate --root . --tool find_symbol --allow-tool find_symbol \
  --path src/auth.py --symbol authorize

# Compiler/AST symbol references with explicit output ceiling
daddy-reviews investigate --root . --tool find_references --allow-tool find_references \
  --path src/auth.py --symbol authorize --tool-limit 12

# Known inbound/outbound source-backed dependencies
daddy-reviews investigate --root . --tool query_dependencies --allow-tool query_dependencies \
  --path src/auth.py --max-depth 3

# OpenAPI route contract (file must be in R7.01 source manifest)
daddy-reviews investigate --root . --tool inspect_contract --allow-tool inspect_contract \
  --path openapi.json --route /api/users --http-method GET

# Graph-connected tests only
daddy-reviews investigate --root . --tool find_tests --allow-tool find_tests \
  --path src/auth.py --tool-limit 10

# Local Git history (no network, no file content checkout)
daddy-reviews investigate --root . --tool inspect_history --allow-tool inspect_history \
  --path src/auth.py --tool-limit 5
```

A caller may supply `--snapshot-file` with the existing `daddy-reviews snapshot` output to pin all tools to the same source manifest. A stale manifest returns a `stale` result and suppresses all findings; the session never falls back to the live tree silently.

## Python orchestration API

```python
from pathlib import Path
from daddy_reviews.investigation import InvestigationSession, ToolRequest

session = InvestigationSession(Path('.'), allowed_tools={'read_file', 'find_tests'},
                               max_calls=4, max_bytes=32_000)
first = session.execute(ToolRequest('read_file', 'src/auth.py', end_line=25))
related = session.execute(ToolRequest('find_tests', 'src/auth.py', depth=3, limit=8))
assert first['status'] in {'complete', 'partial', 'stale', 'not_found'}
```

Permissions are per-session **capabilities**. No tool may be invoked unless it appears in the session's explicit allowlist, and an unexpected tool identifier is rejected before execution. Tool names are not dynamic executable commands. This release does not authorize shell access, writing code, executing tests, posting review comments, mutating Git, or network calls.

## Budgets and trust boundaries

- Session: at most 12 calls, 128 KB of returned JSON bytes, and 32 KB per individual result. Default is 12 calls / 128 KB; limits can only be reduced.
- Source selection: 1–100 LF-delimited lines, up to 12 KB of source excerpt, no symlinks, no paths outside the captured worktree.
- Symbols/references/dependencies/tests: at most 40 returned items per requested direction; dependency depth 1–4; a hit at a result limit may return `partial`.
- Git history: at most 12 local commits and a five-second command timeout; no remote operations, no Git credentials in output. Git HEAD is checked twice to avoid mixing revisions.
- Contracts: OpenAPI 3.x JSON only, conventional filename, R7.01 snapshot `MAX_FILE_BYTES` (350 KB), bounded operation/field response. No remote `$ref` resolution or external schema fetch.
- Every execution checks the full source-manifest fingerprint **before and after**, and returns no evidence if source changed. Source spans also include exact path, source SHA-256, line and declared confidence.
- Python source is parsed or read, not imported or executed. Optional TS/Javac/Roslyn adapters may spawn bounded compiler processes but do not execute reviewed source; the tool registry itself has no arbitrary shell interface.
- File bytes, repository comments, Git subjects and retrieved snippets are **untrusted data**, not trusted instructions. The tool dispatcher never forwards those to an LLM in R8.01.

## Verification gate

`tests/test_investigation.py` exercises all seven tools, permission denial, type/line/path validation, limit truncation, source drift, malformed OpenAPI, local Git history, fake test-name rejection, prompt injection and read-only behavior. CI explicitly executes it on Python 3.10, 3.12 and 3.13 and runs the CLI denial/grant flow. Existing R7 compiler and graph tests also remain mandatory.

## What remains for R8.02

R8.01 delivers **tool contracts and deterministic execution**, not agent autonomy. R8.02 must implement per-specialist tool-call authorization, model-output schema parsing, investigation budgets, verified citation joins, safe abstentions, orchestration/termination rules, and quality evaluations that measure false positives. Automatic GitHub PR publication remains separately permission-gated.
