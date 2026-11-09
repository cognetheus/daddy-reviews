# R8.04f — Supervised test execution with GitHub-authenticated evidence

R8.04f adds a fixed-suite test supervisor, strict execution evidence format, a read-only offline operator verification CLI, and an integration workflow that performs actual pytest execution, independently attests its bounded evidence artifact using GitHub Actions OIDC/Sigstore, then verifies that signature and the recorded process outcome.

This is **higher assurance than a self-declared test log**, but does not mean external cryptography proves a test actually ran truthfully. An authorized compromised workflow can still forge process outputs. No model or human decision is automatically published or allowed to block merges.

## Three-job trust separation

The integration workflow is [`.github/workflows/attested-test-execution.yml`](../.github/workflows/attested-test-execution.yml).

1. **`run-fixed-suite`** (GitHub-hosted, `contents:read`, no OIDC/signature privileges): checked-out source executes a *single pinned test suite* `tests/test_human_quality.py`. `capture_fixed_ci_test` invokes the Python pytest module directly without a shell; captures process return code, output and SHA-256 hashes in a bounded JSON artifact. It refuses to run if an OIDC request token/URL or GitHub token is exposed in the process environment. Only a `passed` and complete record is uploaded for signing.
2. **`sign-only`** (GitHub-hosted, `id-token:write`, `attestations:write`): downloads the exact test artifact, runs only `actions/download-artifact@v4` and `actions/attest@v4`. It does **not** checkout or install the repository or execute its source/Python code. OIDC permission exists only here. The resulting GitHub attestation authenticates *artifact origin* at the pinned source commit.
3. **`verify-attested`** (`contents:read`, `attestations:read`, **no OIDC permission**): retrieves the same artifact and Sigstore bundle, verifies with the pinned GitHub CLI executable and TUF root, revalidates the signed in-toto/SLSA subject digest, immutable repository ID, expected source commit and signer workflow, and then parses the bounded test-execution record. It asserts test status `supervisor_recorded_passed_origin_authenticated` and also deliberately reports `test_outcome_proven:false`.

A modified exit code or other tampered artifact is rejected by the real signature verification workflow. The three-job integration and source-identity test provide a meaningful, reproducible vertical slice with tightly scoped signing privileges.

## Captured record

The `daddy-reviews-supervised-test-execution-v1` JSON record carries the exact `repository`, `source_commit`, `workflow`, `run_id`, `run_attempt`, pinned `suite` and `suite_sha256`, module-launcher contract, bounded timeout, UTC timestamps and duration, process `exit_code`, `outcome`, `output_complete`, base64 stdout/stderr and their SHA-256s.

The host re-derives the reported outcome from `exit_code` and `output_complete`. A zero exit code with truncated output is **not** a valid `passed` outcome. Missing hashes, incorrect source identities, a different suite, forged OIDC-origin metadata or invalid base64 fail closed. The total artifact must be no larger than 64 KiB; output is capped at 15,000 bytes per stream. Raw test output is not included in the final audit result.

## Offline operator CLI

Gather the supervised JSON artifact, authentic Sigstore bundle and trusted root from the exact desired GitHub Actions run. Pin the numeric repository ID, full source commit, suite file SHA-256, workflow identity and run ID from independent operator records.

```bash
gh_binary="$(realpath "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_binary" | cut -d ' ' -f 1)"
artifact_sha="$(sha256sum supervised.json | cut -d ' ' -f 1)"
suite_sha="$(sha256sum tests/test_human_quality.py | cut -d ' ' -f 1)"

daddy-reviews attested-test-verify \
  --root . \
  --attested-artifact-file ./supervised.json \
  --attestation-bundle-file ./sha256:ACTUAL_BUNDLE_NAME.jsonl \
  --sigstore-trusted-root-file ./trusted_root.jsonl \
  --gh-binary "$gh_binary" \
  --gh-binary-sha256 "$gh_sha" \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --attestation-commit 0123456789abcdef0123456789abcdef01234567 \
  --attestation-signer-workflow OWNER/REPO/.github/workflows/attested-test-execution.yml \
  --attestation-artifact-sha256 "$artifact_sha" \
  --test-suite-sha256 "$suite_sha" \
  --test-run-id 1234567890 \
  --test-run-attempt 1
```

Exit 0 means the artifact signature and pinned-record policy passed **and the supervisor reported a successful complete process exit**. Exit 2 means unresolved/failing process status or invalid inputs/attestation. Neither result authorizes a GitHub write or a merge gate.

## Security limitations and production prerequisites

- Captured `run_id`, `run_attempt`, timestamps and process outputs are *workflow-produced claims*. The signing certificate authenticates the workflow identity and artifact, not the accuracy of those claims. Cross-check GitHub's Jobs API and audit logs independently before relying on run metadata.
- The current test suite is deliberately fixed. Tests execute repository source; never run untrusted pull-request changes with signing credentials or repository write tokens. On real deployments use protected branches, protected reusable workflow definitions, no attacker-influenced dependencies, pinned action commits and a hardened runner environment. The example workflow uses action major-version tags; these are not immutable SHAs.
- The `sign-only` job does not execute repository Python; third-party GitHub actions themselves remain an upstream supply-chain boundary.
- The evidence is not a real defect label, nor does it connect to a particular human-attested finding. It does not establish a model's false-negative rate or validate code changes in arbitrary repositories.
- The verification process is bounded and read-only with no repository test execution. `capture_fixed_ci_test` is a separate opt-in Python API for **isolated trusted CI only**, not a general operator CLI command.
- Validate Sigstore trusted-root freshness and GitHub account/repository policy independently. The offline verifier cannot prevent a compromised host or malicious privileged actor from substituting the trusted binary/root/policy before invocation.
- Next gate: independently authenticated GitHub Jobs API status for the exact run and step, a protected centrally controlled test builder, and real independently adjudicated repository evaluation data.

## Validation

`tests/test_test_execution.py` checks a real local pytest subprocess and adversarial record mutation; `tests/test_attested_test_cli.py` verifies the operator CLI. The three-job integration tests a genuine OIDC/Sigstore signer and rejects tampering. The regular CI Python 3.10, 3.12, 3.13 matrix runs the supervisor and CLI regression gates.
