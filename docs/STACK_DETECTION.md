# Technology stack discovery — v0.3.0

Command: daddy-reviews stack --root .

## Implemented behavior

A read-only, bounded manifest inventory for four ecosystems. No install, build, runtime execution, external network, package metadata resolution or security scan is performed.

- JavaScript/TypeScript: package.json dependencies, devDependencies, peerDependencies, optionalDependencies.
- Python: pyproject.toml project and Poetry dependencies (when tomllib is available), requirements*.txt direct pinned or ranged declarations.
- .NET: *.csproj package references and target frameworks, including SDK Web project marker.
- Java: pom.xml dependency declarations and relevant Java compiler target properties.

A result includes manifest path, ecosystem, declared name/constraint, framework/ORM candidates, runtime target declarations and parse limitations. Output always warns that declared versions are not verified installed or resolved versions.

## Trust and completeness

- Vendor/build directories are skipped and symlinked manifests excluded.
- Each manifest is size capped at 1 MB; manifest count capped at 100. Excesses are reported as incomplete.
- Dependency versions from Maven BOM, central NuGet, Gradle or lockfiles may not be resolved; this is not a complete SBOM.
- Python 3.10 lacks stdlib tomllib; pyproject dependencies are skipped with a warning, while requirements files can be scanned. A later adapter can use an explicitly pinned TOML parser without importing project code.
- Detection by package name is a *capability hint*, not proof a framework/ORM is active in production.
- No vulnerability, license, release-freshness or security-reachability conclusions are generated.

## How to use

1. Run stack inventory.
2. Verify runtime versions, lockfiles, deployed image targets and the actual application folder for monorepos.
3. Choose relevant standards-engine reference modules.
4. Run applicable typechecks, linters, tests or instrumented queries.
5. Record exact standard version and official reference for consequential findings.
6. Mark uncertain findings as needing verification; never manufacture critical issues from package names.

## Major future improvements

Resolve manifests and lockfiles per ecosystem, support Gradle/central package management fully, produce SBOM, detect capability overlap from actually used APIs, version official standards via recorded fetch dates, and test upgrade migrations against real toolchains.
