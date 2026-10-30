# R7.01 — Semantic repository evidence contracts

R7.01 establishes the **verified source-manifest and evidence contracts** required before introducing TypeScript, Python, Java and C# semantic analyzers. It does not claim that those analyzers exist. All existing review/graph commands remain unchanged.

## Source snapshot API

- `capture_worktree(root: Path) -> dict`: deterministic SHA-256 content manifest for supported source files and selected configuration files, including path, size, line count, and file digest. No source code is executed and no files are written.
- `validate_snapshot(snapshot) -> dict`: strictly validates an untrusted manifest's version, paths, uniqueness, ordering, numeric budgets, provenance and content ID.
- `read_snapshot(path: Path) -> dict`: bounded, symlink-rejecting JSON reader.
- `verify_worktree(root, previous) -> dict`: independently re-enumerates local files to detect added, removed or changed files. Returns `fresh` only when both scans are complete and content IDs match.
- `bound_span(snapshot, path, start, end, origin, certainty)`: creates source locations attached to the captured file's SHA and the manifest ID. Cannot use incomplete manifests, nonexistent files or invalid line ranges.
- `SemanticSymbol`, `SemanticReference`, `ContextExcerpt`, `context_bundle`: typed, length-bounded serialization contracts for future language adapters and contextual review retrieval. Evidence originating from another manifest or an altered file hash is rejected.

### CLI

```bash
# Read-only. Redirect output to save a manifest explicitly.
daddy-reviews snapshot --root . > local-source-manifest.json

# Does not execute tests or source. Exit 0=fresh, exit 2=stale or incomplete.
daddy-reviews snapshot-verify --root . --snapshot-file local-source-manifest.json
```

Keep manifest files out of the indexed tree and out of public logs when filenames are sensitive. A worktree manifest is **not an authenticated Git tree** or a byte-for-byte archival copy. It is immutable metadata identifying content observed during a scan, and the filesystem may change immediately afterward. Do not feed stale results to review agents.

### Contract fields

| Contract | Required provenance | Confidence / status |
| --- | --- | --- |
| Worktree snapshot | SHA-256 over sorted file hashes, explicit source kind, scan completeness | Complete or explicitly incomplete; not Git-authenticated |
| Source span | Snapshot ID, path, file SHA-256, line range, origin | `resolved`, `candidate`, or `unknown` (declared by originating adapter, not auto-verified) |
| Semantic symbol | Name, kind, source span | Inherits origin and certainty from its span |
| Semantic reference | Target name, relationship, source span, optional target span | Candidate until actual semantic resolution or tests support it |
| Context excerpt | Source span, text, purpose | A bounded quoted text segment, not proof of correct behavior |
| Context bundle | One snapshot ID and referentially consistent evidence records | No claim that runtime calls have been verified |

Snapshot and context-bundle schema formats are `daddy-reviews-semantic-snapshot-v1` and `daddy-reviews-context-bundle-v1`. Contracts deliberately abstain rather than fabricate source positions, true runtime invocation, or developer intent.

## Indexing budgets and safety

- Up to 4,000 supported source/config files, maximum 350 KB per file and 24 MB total bytes.
- Symlinked sources/directories are never traversed, source trees with budget violations or unreadable content become incomplete, and verified source spans cannot be constructed from them.
- JSON manifest input is capped at 8 MB; paths cannot be absolute or traverse outside the worktree.
- The manifest is in-memory/read-only by default; no GitHub posting, model call, source modification, or external network requests.

## Evaluation baseline

The `evals/r7_context_scenarios.json` file contains **four synthetic design scenarios**: Python authorization consumers, TypeScript barrel re-exports, shadowed symbols, and clean changes. These are architectural test specifications with grounded expected source locations, **not human-verified software-defect labels** and not evidence of semantic-indexing accuracy. Contract/CLI tests ensure the fixture locations and manifest provenance are valid; compiler-level expected references become behavioral gates when R7.02 and R7.03 are implemented.

## Execution gates and next dependency

R7.01 is complete when every supported Python CI version passes the snapshot, stale-state, source-path, symlink, forged-digest, type validation and existing CLI backward-compatibility tests. R7.02 must implement actual TypeScript compiler-backed symbol resolution against these contracts, and must explicitly distinguish unresolved/partial results rather than claiming compiler resolution.
