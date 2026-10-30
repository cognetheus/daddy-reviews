# R7.02 — TypeScript/JavaScript semantic references

**Implemented:** a bounded read-only TypeScript 6 compiler adapter, available separately from the existing lexical JS/TS graph and symbol heuristics. The adapter resolves **compiler symbol identities**, not spelling matches. It does not claim runtime reachability or verify software defects.

## Setup

Node.js 22+ recommended. Python's base package still has **zero additional mandatory dependencies**. Opt in to the exact pinned compiler version:

```bash
npm install --prefix tooling/typescript --ignore-scripts --no-audit --no-fund
python -m pip install -e .

# Target must identify a TS/TSX/JS/JSX source and one declaration name
daddy-reviews ts-semantic --root . --changed src/core/auth.ts --symbol authorize

# Optional: ensure evidence matches a previously captured read-only manifest
daddy-reviews snapshot --root . > /tmp/review-source-snapshot.json
daddy-reviews ts-semantic --root . --changed src/core/auth.ts --symbol authorize \
  --snapshot-file /tmp/review-source-snapshot.json
```

TypeScript is pinned to **6.0.3** in `tooling/typescript/package.json`. This adapter intentionally rejects other versions rather than assuming TypeScript 7 has the same JavaScript compiler API. Installing the optional compiler does not execute repository project scripts; `npm install --ignore-scripts` is the recommended tool installation mode. The indexer itself never runs npm.

## Implementation architecture

- `semantic_contracts.py` captures and validates the bounded source manifest, including exact file SHA-256.
- `ts_semantic.py` verifies the complete snapshot, sends at most 5 MB of selected source text to a child Node process with bounded timeout, then validates every returned reference against snapshot paths/line ranges.
- `tooling/typescript/semantic-index.cjs` builds a TypeScript `Program` with a **virtual, read-only CompilerHost**. The only on-disk content it may load is the trusted pinned TypeScript compiler's own `lib.*.d.ts`. User repository source/config comes from validated input bytes.
- The compiler `TypeChecker` resolves aliases, imports, re-exports, declared functions, methods, classes, interfaces, variables, constructors, and supported type/heritage references. Results include `compiler_version`, exact source location, definition location, source hash, snapshot ID, relationship and `compiler/resolved` provenance.
- TypeScript/JavaScript source is **parsed, not executed**. No compilation output, repository hooks, package resolution downloads, GitHub writes, tool calls, or shell execution of source.

## Supported relationships

| Kind | Example |
| --- | --- |
| `direct_call` | Imported or aliased named function invocation |
| `constructor_call` | `new RenamedClass()` resolving to original class |
| `member_call` | Receiver-type-resolved class/interface method call |
| `property_reference` | Resolved property access, if it targets the requested declaration |
| `type_reference` | Type/interface use in annotations or generic references |
| `heritage_reference` | `class Service implements Interface` or `extends Base` |

The indexer recognizes root `tsconfig.json`/`jsconfig.json` compiler options, including simple local `baseUrl` and `paths` mappings. Missing/unresolved imports and source parse errors mark the response partial, rather than claiming full coverage. Shadowed imports are not credited as references to their imported names.

## Safety, limitations and explicit omissions

- **Read-only and opt-in:** `ts-semantic` is an explicit new command; existing `review` and `symbol-impact` behavior remains backward compatible.
- **Only one root config:** tsconfig `extends`/project `references`, nested package-specific config graphs, and cross-project package exports require the R7.06 project-aware adapter. They currently produce an incomplete result or a recorded limitation rather than silent pretend-resolution.
- Source budgets: 800 indexed TS/JS files, 5 MB source bytes, 7 MB process input, at most 500 output reference locations. Current worktree manifest is bounded separately by R7.01.
- Statuses: `complete` means compiler identity resolution finished within supported scope; `partial` warns about unsupported/ambiguous source conditions; `unresolved`, `ambiguous`, `incomplete`, `stale`, and `unavailable` never advertise complete semantic coverage. Non-complete CLI exits with code 2.
- The tool does not prove execution, dynamic module loading, runtime monkey-patching, cross-language behavior, remote imports, external package runtime calls, reachability or vulnerability severity.
- Tests cover real compiler invocation, aliases, barrel re-exports, shadowing, class method/constructor identity, interfaces, inheritance, local tsconfig paths, missing imports, source drift, disallowed source execution, absent compiler, and CLI output.

## Acceptance and next phase

R7.02 acceptance requires executing the actual pinned TypeScript compiler in the GitHub Python 3.10/3.12/3.13 CI matrix, including all new tests with the compiler installed, while preserving prior tests. This is a **single-symbol query adapter**, not yet a persistent whole-repository symbol index; R7.06 is responsible for cross-project indexing, caching and ranked context retrieval. R7.03 next develops deeper Python language-semantic indexing through the same provenance contract.
