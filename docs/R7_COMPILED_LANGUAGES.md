# R7.04 — Compiler-backed Java and C#/.NET semantic references

**Scope:** two optional, read-only language adapters for standalone projects with bounded sources. This milestone does **not** claim full Eclipse JDT LS integration, Maven/Gradle project resolution, MSBuild solution workspaces or runtime reachability.

## Architecture

| Language | Engine | Toolchain | Source evidence |
| --- | --- | --- | --- |
| Java | JDK `javac` Compiler Tree API (`JavacTask`, `Trees`, element identity) | JDK 17+; CI JDK 21 | File hash, snapshot ID, line, `compiler/resolved` |
| C#/.NET | `Microsoft.CodeAnalysis.CSharp` Roslyn `CSharpCompilation` semantic model | .NET 8 SDK pinned in `tooling/dotnet/global.json` | File hash, snapshot ID, line, `compiler/resolved` |

Both run in separate subprocesses, using only **temporary copies of verified source bytes**. Project source is parsed and resolved, never executed. Java processing uses `-proc:none`, no Maven/Gradle and no external classpath. The C# helper uses only Roslyn assemblies shipped with the selected SDK, without NuGet packages, source generators or reviewed project build scripts. No outbound network calls are performed by the analyzers.

## Installation and invocation

```bash
# Java (JDK 17+, recommended JDK 21): no build dependencies or separate JDT LS
daddy-reviews java-semantic --root . \
  --changed src/main/java/com/example/UserService.java \
  --symbol UserService.authorize

# C# (build trusted helper once using SDK 8; no NuGet packages)
cd tooling/dotnet && dotnet build -c Release && cd ../..
daddy-reviews cs-semantic --root . \
  --changed src/Services/UserService.cs --symbol UserService.Authorize

# Optional: pin a previously captured snapshot
daddy-reviews snapshot --root . > /tmp/source-manifest.json
daddy-reviews java-semantic --root . --changed app/Service.java \
  --symbol Service.run --snapshot-file /tmp/source-manifest.json
```

### Response contract

Both commands return `daddy-reviews-compiled-semantic-v1` with `language`, `status`, `compiler_version`, exact `definition`, `references`, `context_bundle`, warnings and `runtime_calls_proven: false`. Each reference is backed by an R7.01 `SourceSpan` containing the original file's SHA-256 hash, snapshot identity, and exact line. Status `complete` means supported compiler identity resolution finished without observed errors; `partial` means source dependency/compiler diagnostics impaired coverage. Other statuses (`unavailable`, `incomplete`, `unresolved`, `ambiguous`, `stale`) are explicit abstentions. The CLI exits nonzero if status is not `complete`.

### Supported relationships

- `method_call`: method invocation resolving to the exact target compiler symbol (not name equality).
- `constructor_call`: `new ClassName(...)` resolving to the target class, not an unrelated homonym.
- `type_reference`: type identifier/annotation resolving to the selected declared class/interface.

Each adapter reads at most 800 files / 5 MB selected source, emits up to 500 reference records, and is constrained by a default 30-second compiler deadline. The Python wrapper checks content-hash freshness before and after analysis; all subprocess-reported paths and line numbers are validated against the complete source snapshot.

## Limitations / next steps

- **Java uses JDK compiler APIs, not Eclipse JDT LS.** It deliberately avoids starting a long-lived Java workspace daemon in this phase. Projects needing Maven/Gradle module, dependency, annotation-processor or generated-symbol resolution require a future optional JDT LS/project adapter.
- **Roslyn uses standalone compilation, not MSBuildWorkspace.** It resolves symbols across the supplied local C# source set and trusted framework references, but doesn't load `.sln`/`.csproj` metadata, third-party packages, analyzers or source generators. Missing dependencies produce `partial`, not a false clean result.
- Query selection is intentionally limited to an unambiguous class name or `Class.method`. Overloaded methods, namespaces with identical class names, polymorphic overrides, generic runtime dispatch and dynamic reflection require more project context; ambiguous targets abstain.
- A compiler-resolved reference is evidence of static binding only. It is **not** proof that a path runs, that a regression exists, or that a finding is suitable for automated PR blocking.
- The helper source is trusted repository code, whereas reviewed repository files remain untrusted data; source is copied to an isolated temporary directory but this milestone is **not** a process sandbox against operating-system-level attacks.

## Verification

CI uses Python 3.10, 3.12 and 3.13 with JDK 21 and the pinned .NET 8 SDK. Integration tests exercise actual javac Trees and Roslyn symbol binding, negative name-shadow cases, constructor references, unresolved dependencies, stale/incomplete snapshots, invalid paths and CLI compatibility. Test skips on machines lacking optional toolchains are expected only outside this configured CI matrix.

**Next:** R7.05 cross-layer dependency intelligence, then R7.06 ranked context retrieval and project-aware incremental graph integration.
