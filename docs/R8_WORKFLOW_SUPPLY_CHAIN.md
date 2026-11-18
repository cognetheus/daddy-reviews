# R8.05a — Immutable GitHub Actions supply-chain pins

All executable `uses:` dependencies in `.github/workflows/` have been changed from mutable major tags to exact **full 40-character upstream commit IDs**, verified against official GitHub action Git refs on November 18, 2026. Readable major versions are retained as YAML comments.

| Action | Pinned commit SHA |
|---|---|
| `actions/checkout@v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python@v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/setup-dotnet@v4` | `67a3573c9a986a3f9c594539f4ab511d57bb3ce9` |
| `actions/setup-java@v4` | `cf277c60eb25467037889841efdb72551f06f6c3` |
| `actions/setup-node@v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| `actions/upload-artifact@v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| `actions/download-artifact@v4` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| `actions/attest@v4` | `1e69f48acb82d1966a394da916b4c1698aa569d6` |

CI's `tests/test_workflow_sha_pins.py` scans **every workflow**, and rejects an unpinned, unknown or changed action reference. Existing least-privilege, OIDC separation, read-only research and blind-artifact policy tests remain in force.

**Security impact:** upstream tags can move, whereas a fully pinned Git object cannot silently change under the same SHA. This reduces a major supply-chain redirection risk for the OIDC signing job, which is deliberately action-only.

**Maintenance tradeoff:** immutable pins also freeze security fixes. Vet each new action release, source commit, changelog and transitive dependencies before updating this table, all references and the CI allowlist in one reviewed commit. GitHub itself recommends full SHA pins for Actions security.

Remaining R8.05 work: verify branch/workflow protection settings, pin transitive and runtime dependencies, harden the GitHub Actions runner and credentials, and validate real-world reliability/latency under load. SHA pinning does **not** attest arbitrary test results or externally authenticate human defect labels.

Reference: [GitHub secure use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
