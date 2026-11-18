# R8.05c — Dependency constraints and bounded test-runner reliability

**Status:** Engineering gates delivered; production reproducibility is **partially** improved, not fully established. The repository's `main` branch is still unprotected and real independent human defect evidence remains outstanding.

## 1. Exact dependency inputs

| Surface | Previous behavior | R8.05c behavior | Residual limitation |
|---|---|---|---|
| TypeScript compiler helper | `npm install --no-package-lock` despite exact `typescript` version | `tooling/typescript/package-lock.json` v3 with TypeScript **6.0.3 SHA-512 tarball integrity**; `npm ci --ignore-scripts`; `.npmrc` disables scripts | npm registry/CDN and host runtime still trusted; lock verified by npm at install |
| .NET helper | SDK `8.0.x` floated to latest patch | `tooling/dotnet/global.json` requires **8.0.428** with `rollForward: disable`; GitHub setup-dotnet installs and validates exact SDK | Host/SDK provenance, OS/runtime and .NET SDK transitive content not cryptographically reproducible |
| Python build backend | `setuptools>=68` floated across builds | `setuptools==80.9.0` in `pyproject.toml` | PyPI artifact hashes and build platform remain unpinned |
| Python CI verification | Unconstrained `pytest` and broad `cryptography>=43,<48` | Shared `ci/requirements-constraints.txt` enforced across CI and hosted verification/intake jobs | **Version constraints only**; not a `--require-hashes` lock |

Successful baseline GitHub CI logs on 18 November 2026 supplied these compatible Python versions: `cryptography==47.0.0`, `cffi==2.1.1`, `pytest==9.2.0`, `pluggy==1.7.0`, `packaging==26.3`, `iniconfig==2.3.1`, `pygments==2.21.0`. Python 3.10 requires `pycparser==3.11`; Python 3.11+ can use `pycparser==3.12`. The constraints also pin old-Python auxiliary dependencies (`exceptiongroup`, `tomli`, `typing_extensions`).

The TypeScript tarball's SHA-512 integrity was cross-checked against the published **Microsoft TypeScript Server Replay** package lock for `typescript@6.0.3`. It is verified at `npm ci` execution, not assumed based only on a version string.

`tests/test_dependency_lock_policy.py` rejects lockfile drift, unlocked npm installs, missing integrity, floating .NET SDK, unpinned Python constraint declarations and CI jobs bypassing the shared constraint file.

**Production portability note:** `tooling/typescript` still installs optional tooling from npm registry; this is *not* source vendoring or an offline build guarantee. The Java tool uses a JDK 21 line and runner image; an exact JDK patch and image/digest require follow-up controls. Python wheels/sdists and pip build isolation require hashes and an audited per-platform lock strategy before claiming hermetic reproducibility.

## 2. Supervisor process hardening

The fixed-suite attested CI supervisor previously used `subprocess.run(..., capture_output=True)`, which buffers both streams in memory until process completion and can exhaust a runner on noisy code.

R8.05c introduces `src/daddy_reviews/bounded_exec.py`:

- `subprocess.Popen` with a fixed argument vector, **no shell**, `stdin=DEVNULL`, `close_fds=True`, and a new POSIX process session.
- Nonblocking `selectors` drainage of both stdout and stderr, **hard stream output caps** and a monotonic deadline. Streams are never accumulated beyond the configured cap.
- On timeout or excess output, the process group is killed, child reaped and output marked **incomplete**. The attested fixed-suite record reports a failed outcome, never an optimistic `passed`.
- The supervised pytest child now receives an **explicit seven-variable environment allowlist**, not the runner's ambient cloud credentials, GitHub authentication, tokens, proxies, or local Python import overrides.
- `tests/test_bounded_exec.py` exercises real million-byte stdout/stderr floods, a sleeping child past the deadline, successful two-pipe output, invalid budgets, secret-denial and fail-closed attestation behavior.

The attestation's original schema is unchanged. External Sigstore provenance continues to establish artifact origin, **not the truth of the supervised tests**.

**Security boundary:** this runner is **not** a general sandbox for untrusted repositories. The fixed test suite is authored in the reviewed repository and executes only in the unprivileged GitHub-hosted test job. If the test process escapes to another process/session or accesses public network services, this function does not provide kernel-level containment. Strong execution isolation is a separate release requirement.

## 3. How to validate

From the repository checkout:

```bash
npm ci --prefix tooling/typescript --ignore-scripts --no-audit --no-fund
python -m pip install --constraint ci/requirements-constraints.txt -e '.[verification]' pytest
python -m pytest -q tests/test_dependency_lock_policy.py tests/test_bounded_exec.py tests/test_test_execution.py
(cd tooling/dotnet && dotnet --version) # must be 8.0.428
```

The CI matrix executes those regression tests under Python 3.10, 3.12 and 3.13. GitHub's real `attested-test-execution.yml` integration also executes the fixed suite in an isolated non-OIDC job, signs the resulting bounded artifact in a separate OIDC-only job, and verifies it in another read-only job.

## 4. Remaining R8.05 gates

1. Enable actual protected `main` and enforce CODEOWNERS / required CI / two approvals with live branch-security verification.
2. Add pip `--require-hashes` constraints or trusted wheelhouse/SBOM for each supported Python and OS target, with reproducible SDK/JDK provenance.
3. Strengthen compiler adapter subprocesses and other external commands to enforce streaming budgets, process group kill, sandbox/resource constraints and network-denial where needed.
4. Establish operational SLOs for review latency, memory and success, with reproducible failure-injection load tests, alerting and incident rollback.
5. Run the externally preregistered, independently adjudicated human study from R8.04k before any model promotion or PR/merge authority.

**All autonomous approvals and merge blocking remain disabled.** No dependency lock or bounded execution test changes the status of the unprotected branch or proves real-world review quality.
