# R8.04d.01–d.02 — Offline operator workflow and runner-signed test receipts

R8.04d provides a **read-only, offline operator CLI**. Unlike the model harness, no inference is needed. The operator explicitly selects an existing R8.02 investigation report, optional R8.04b challenge, authorized R8.04c human Ed25519 attestations, their trusted public-key registry, and the exact test-log bytes identified by SHA-256. It never runs the recorded tests, accesses the network, modifies a repository, or publishes GitHub comments.

## Install

```bash
python -m pip install -e '.[verification]'
```

Use the `daddy-reviews human-verify` command:

```bash
daddy-reviews human-verify \
  --root ./reviewed-source-tree \
  --diff-file ./review-artifacts/patch.diff \
  --report-file ./review-artifacts/investigation.json \
  --challenge-file ./review-artifacts/independent-challenge.json \
  --attestations-file ./review-artifacts/human-attestations.json \
  --trusted-keys-file ./operator-private/human-public-keys.json \
  --evidence-dir ./review-artifacts/test-logs \
  --human-min-reviewers 2
```

If there was **no independent challenge**, omit `--challenge-file`. If there *was* a challenge, omitting it bypasses conflict assessment and is an operator trust-policy failure; callers should treat challenge presence as mandatory whenever the review process produced it.

`test-logs/` must contain files named by their exact lowercase SHA-256 hex digests, such as `7edc...c0e8` (64 hex characters). The CLI checks the contents of every named file against each human-signed `test.log_sha256`.

- The trust registry must be supplied independently of model and reviewer outputs; its file must not be group/world writable.
- Inputs must be bounded regular files with no symlinked file/parent components; an OS supporting `O_NOFOLLOW` is required. Parent directories must be operator-controlled (the current implementation is not race-free against a malicious actor who can replace ancestors between checks).
- Duplicate JSON keys, invalid UTF-8, non-finite JSON values, oversized reports, unreadable logs, log digests not matching filenames, invalid identities, stale snapshots, and unapproved signatures fail closed.
- No automated verification can establish that the provided log was produced by the declared command. Logs are **human-signed integrity evidence**, not independently authenticated runtime execution.

The CLI prints a structured JSON human resolution. **Exit 0** means every candidate reached a human-attested disposition (which can be confirmed or rejected), **not** that the code is safe. **Exit 2** means unresolved or conflicting decisions, or an input validation error.

## Optional runner-signed evidence

An operator may additionally provide a separately managed **CI-runner signing key registry** and signed runner receipts. A receipt includes the key/runner identity, self-declared GitHub Actions workflow path, run ID, job ID and attempt, pinned owner/repository and Git commit, original source snapshot and patch hashes, a test ID/outcome, and the exact SHA-256 of log bytes already signed by human reviewers.

```bash
daddy-reviews human-verify \
  --root ./reviewed-source-tree \
  --diff-file ./review-artifacts/patch.diff \
  --report-file ./review-artifacts/investigation.json \
  --attestations-file ./review-artifacts/human-attestations.json \
  --trusted-keys-file ./operator-private/human-public-keys.json \
  --evidence-dir ./review-artifacts/test-logs \
  --ci-receipts-file ./review-artifacts/runner-receipts.json \
  --ci-runner-keys-file ./operator-private/runner-public-keys.json \
  --ci-expected-repo OWNER/REPO \
  --ci-expected-commit 0123456789abcdef0123456789abcdef01234567
```

All four `--ci-*` flags are required together. The CI runner key registry has distinct role `ci_runner_attestor`, not `human_verifier`. Signature bytes are domain-separated, canonical Ed25519 signatures over `daddy-reviews-runner-receipt-v1` JSON excluding `signature_b64`. `runner_signing_bytes(record)` is the supported signing payload function.

A valid runner-signed report can attain `ci_runner_provenance.status: runner_key_verified`, but it **always** reports `platform_oidc_verified: false` and `github_actions_execution_proven: false`. The verifying host does not fetch GitHub API records, check GitHub's OIDC identity, verify Sigstore bundles, authenticate a GitHub artifact attestation or prove the test executed. The enrolled runner can lie or be compromised. This is a **key-authenticated runner claim**, not a production-grade external CI execution attestation.

A CI validation that does not cover every human-attested test returns `incomplete_runner_evidence` and exit 2. Invalid signatures, stale metadata, mismatched repo/commit, counterfeit logs and duplicate receipts fail closed. No GitHub operations occur.

## Deliberate non-goals and next phase

R8.04d.01–d.02 are secure operator plumbing and provenance *claims*. R8.04d.03 must add blinded, independently adjudicated human-label calibration for false-positive/false-negative and conflict resolution; this cannot be replaced by self-declared synthetic metrics. A subsequent integrity extension must verify genuine hosted-CI attestations (platform identity and signing chains) if the system is to claim externally verifiable job execution.

See [human attestations](R8_HUMAN_VERIFICATION.md) and [independent challenge](R8_INDEPENDENT_CHALLENGE.md).
