# R8.04e.01–e.02 — Offline GitHub/Sigstore artifact attestation

Unlike R8.04d runner self-signatures, **this implementation delegates cryptographic validation to GitHub CLI's official `gh attestation verify`** and then validates the verified certificate's immutable numeric repository ID and signed artifact digest. GitHub CLI verifies the signing certificate, GitHub Actions OIDC issuer, Sigstore trusted root, timestamp proof, expected signer workflow, and source commit, using explicitly selected files.

A separate [real GitHub Actions workflow](../.github/workflows/attestation-integration.yml) generates an actual `actions/attest@v4` OIDC/Sigstore attestation, downloads the signed bundle and Sigstore trusted root, runs this CLI with a pinned GitHub binary SHA-256, and confirms that changing the artifact causes rejection. Unlike the local mocked policy-unit tests, this workflow exercises real GitHub/Sigstore signing and verification.

## CLI: Verify the origin of a test-log artifact

Prepare artifact and bundle on a trusted online machine using GitHub's documented commands:

```bash
gh attestation download PATH/TO/test-log -R OWNER/REPO
gh attestation trusted-root > trusted_root.jsonl
gh api repos/OWNER/REPO --jq .id
```

Copy the artifact, downloaded bundle and trusted root to the verifier. Record the expected numeric GitHub repository ID, 40-character source commit and signer workflow from trusted operator information. Install GitHub CLI and pin the executable's actual SHA-256.

```bash
gh_binary="$(realpath "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_binary" | cut -d ' ' -f 1)"
artifact_sha="$(sha256sum ./test-log | cut -d ' ' -f 1)"

daddy-reviews github-attestation-verify \
  --root . \
  --attested-artifact-file ./test-log \
  --attestation-bundle-file ./sha256:EXAMPLE.jsonl \
  --sigstore-trusted-root-file ./trusted_root.jsonl \
  --gh-binary "$gh_binary" \
  --gh-binary-sha256 "$gh_sha" \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --attestation-commit 0123456789abcdef0123456789abcdef01234567 \
  --attestation-signer-workflow OWNER/REPO/.github/workflows/ci.yml \
  --attestation-artifact-sha256 "$artifact_sha"
```

Use the actual bundle filename returned by `gh attestation download`. The operator supplies the pinned commit and real repository ID independently; do not derive trusted policy from an unverified bundle, model response or arbitrary downloaded JSON.

The verifier calls the selected executable with `--bundle`, `--custom-trusted-root`, `--repo`, `--source-digest`, `--signer-workflow`, `--cert-oidc-issuer https://token.actions.githubusercontent.com`, `--predicate-type https://slsa.dev/provenance/v1`, `--deny-self-hosted-runners`, and `--format json`. It checks the exit status **before** parsing output; verifies that the CLI-issued certificate's `sourceRepositoryIdentifier` matches the operator-pinned numeric ID, that a verified timestamp is present, and that the signed in-toto statement references exactly the artifact's SHA-256. It never trusts the `predicate` as proof a test succeeded.

## Link platform-authenticated artifact to R8.04c human signatures

Add the same `--attested-artifact-file`, `--attestation-*`, `--sigstore-trusted-root-file`, and `--gh-*` flags to the existing `daddy-reviews human-verify` command, alongside its usual human-attestation report, trust registry and test-log folder.

The host runs genuine offline GitHub verification and requires the platform-authenticated artifact hash to match at least one **cryptographically verified, human-signed `test.log_sha256`**. If some other human-signed logs are not covered by that single artifact, the command reports `incomplete_human_test_coverage` and exits 2; one attestation cannot silently cover multiple different logs.

Success returns an `external_artifact_attestation` result with `platform_oidc_verified: true`, matched repository ID/commit, artifact digest, and coverage counts. It **does not** change any original human decisions or authorize PR publication/merge blocking.

## Security boundaries

- The executable is a host-selected absolute, non-symlink, executable regular file. The verifier recomputes its SHA-256 both before and after execution, rejects group/world-writable executable files and parent directories, and requires an exact pinned digest. The host is responsible for maintaining a trusted binary installation.
- Bundle (1 MiB maximum), Sigstore root (512 KiB), and exact attested artifact (64 KiB) must be bounded local regular files, not symlinks. Operator input is copied into a private temporary directory before external verification. No reviewed repository code is executed.
- The GitHub CLI invocation uses an argument vector, not a shell; has a strict timeout and bounded JSON output. Token-bearing `GH_*`, `GITHUB_*`, `GIT_*` and `SIGSTORE_*` environment variables and ordinary proxy variables are omitted from its subprocess environment.
- Offline mode requires `--bundle` and `--custom-trusted-root`. Network access is not sandboxed by the Python process; strict offline use still requires network isolation at deployment. Trust-root freshness and revocations are the operator's responsibility.
- When verifying bundles offline, matching `owner/repo` **alone** cannot detect repository renames or name reuse. The additional immutable numeric GitHub repository ID check is mandatory. GitHub's offline-verification documentation recommends that check.
- **GitHub-origin verification does not independently prove that tests passed, that a test command was executed as represented by log bytes, or that the workflow's predicate is truthful.** A compromised authorized workflow could publish a fabricated log. Prefer a trusted-builder/reusable workflow with independently controlled test execution.
- Unit tests mock GitHub CLI output to exercise the policy; the separate Actions integration tests real OIDC/Sigstore signing. Neither substitutes for real-repository issue labels or calibrated model quality.

## Next security increments

Implement a trusted, constrained test-execution workflow with separately protected source and permissions; capture GitHub job/run metadata in independently authenticated provenance; monitor root rotation and freshness; build a blinded and independently adjudicated real-repository defect corpus. Until then the project is **artifact origin-verified**, not scientifically defect-detection-verified or authorized for autonomous release blocking.

Official references: [GitHub CLI attestation verification](https://cli.github.com/manual/gh_attestation_verify), [GitHub offline attestation guide](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline).
