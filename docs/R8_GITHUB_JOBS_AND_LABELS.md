# R8.04g — Authenticated GitHub job status and independently signed labels

R8.04g closes two *provenance* gaps. It cross-checks GitHub's own completed run/job API records against a pinned OIDC-attested artifact run, and authenticates separately signed human reference labels for offline evaluation. Neither feature proves objective code correctness or permits autonomous merge enforcement.

## R8.04g.01 — GitHub Jobs API after run completion

Use the opt-in authenticated read-only CLI after an attested test workflow has **finished**:

```bash
# GH_TOKEN must have read access to Actions for the target repository.
export GH_TOKEN="YOUR_READ_ONLY_ACTIONS_TOKEN"

gh_bin="$(realpath "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_bin" | cut -d ' ' -f 1)"

daddy-reviews github-jobs-verify \
  --root . \
  --gh-binary "$gh_bin" \
  --gh-binary-sha256 "$gh_sha" \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --attestation-commit 0123456789abcdef0123456789abcdef01234567 \
  --test-run-id 1234567890 \
  --test-run-attempt 1
```

The host calls GitHub's official, authenticated REST endpoints for the exact *run attempt* and its attempt-scoped jobs:

- `GET /repos/OWNER/REPO/actions/runs/ID/attempts/ATTEMPT`
- `GET /repos/OWNER/REPO/actions/runs/ID/attempts/ATTEMPT/jobs?per_page=100&page=1`

It requires the exact immutable numeric repository ID, head repository ID, commit SHA, attempt, workflow path, GitHub success/completed status, and **exactly three** successful jobs: `run-fixed-suite`, `sign-only`, and `verify-attested`. Critical steps in each job must be present and completed successfully; skipped, failed, missing, duplicate, other-attempt, self-hosted or unexpected jobs are refused. If the Github API paginates, the declared total count will not match exactly three and verification fails closed.

The verifier calls a SHA-256-pinned `gh` executable by argument vector, not shell. It supplies a bounded explicit `GH_TOKEN` through a temporary private CLI environment, forces GitHub.com, uses read-only `GET`, bounds JSON and time, and does not expose API responses, token or raw log content in the result.

### Combined platform-and-artifact verification

A completed attested execution can be checked in one operator command by adding `--check-live-github-jobs` to the earlier `attested-test-verify` invocation. This requires a read token and independently refuses the overall result unless both the genuine GitHub/Sigstore artifact verification and GitHub's live completed run/job status checks pass.

A dedicated [post-completion Actions workflow](../.github/workflows/verify-attested-run-jobs.yml) runs as a **separate, read-only workflow** after `Attested Test Execution Integration` ends. It has no OIDC/signing or PR write permission, and does not execute the attested repository's test suite. The real workflow passed on a completed GitHub run (Actions run `42684613839`).

**Trust limitation:** a successful, authenticated GitHub REST response is a GitHub-hosted API status claim over TLS, not an independently signed job-status document. Trusted CLI executable, TLS verification, read-only token, repository administration and workflow protection remain operator responsibilities. GitHub job success does not prove the semantics of arbitrary tests. The runner environment field is not always present; `ubuntu-latest` labels are a policy check, not a cryptographic proof of hosted isolation.

Official API reference: [Workflow run attempts](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt) and [attempt-scoped jobs](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt).

## R8.04g.02 — Separate signed defect-label provenance

The offline evaluator previously accepted a self-declared `human_labeled` corpus kind. `human-label-audit` now demands at least two distinct independently enrolled ground-truth adjudicators per case, with genuine Ed25519 signatures over the exact case/source/label/evidence digest. A separate trust registry must give these reviewers the `ground_truth_adjudicator` role; regular model reviewers and `human_verifier` keys cannot self-promote to that role.

Example:

```bash
daddy-reviews human-label-audit \
  --resolution-dataset ./research/human-labeled-cases.json \
  --label-attestations-file ./research/signed-independent-labels.json \
  --label-trust-keys-file ./operator-private/ground-truth-public-keys.json \
  --label-evidence-dir ./research/source-evidence
```

Each signed `daddy-reviews-ground-truth-label-v1` record binds `case_id`, `candidate_id`, `snapshot_id`, `patch_sha256`, `tier`, `label` (`defect` or `clean`), `reviewer_id`, `key_id`, UTC signing timestamp, the fixed blind-protocol declaration `separate_from_model_and_resolution_v1`, bounded `rationale`, and SHA-256 of external supporting evidence bytes. `label_signing_bytes(record)` returns the domain-separated canonical UTF-8 JSON bytes (excluding `signature_b64`) to sign with the reviewer's private key.

The tool verifies the signatures against an **operator-owned, separately provided public-key registry**, plus exact bytes of every signed evidence blob. All evidence files are SHA-256-named. Multiple signers under the same identity do not count as independent. Missing cases, compromised/revoked keys, changed labels or source identities, duplicate human signatures and modified evidence fail closed. Conflicting labels must be resolved outside the model; this tool never silently votes or overwrites ground truth.

Outputs include provenance-audit hashes and the existing human-resolution metrics. Raw evidence and signing keys are not emitted. `promotion_eligible`, `model_quality_approved`, and all PR/merge actions remain **false or none**.

### Essential scientific limitations

- A signature proves key control and signed evidence integrity, **not that the signer is a genuinely independent human, that they were truly blinded, or that their defect label is factually correct**. Blinding is an asserted protocol and must be enforced in study operations.
- Human-resolution reports embedded inside the evaluation dataset are **not re-cryptographically verified** by this labeling step. Re-run `human-verify` using the original signatures and source snapshot for decision authenticity.
- The bundled ten-case corpus is **synthetic**; regression tests generate fresh test-only signing keys. There is no claim that genuine human researchers reviewed live repository defects.
- Real-world precision, recall and false-negative rates require carefully selected genuine repository cases with independently reproduced failures **and negative cases**, adjudicated without exposure to model responses. In particular, evaluation only on findings already generated by the model cannot measure defects it never proposed.
- Even an authenticated, well-powered evaluation cannot authorize PR posting or merge blocking without a separate explicit human release policy.

## Tests and future work

`tests/test_github_job_status.py` tests failed/forged/replayed run attempts, runner mismatch, missing steps, duplicate jobs, token/transport errors and exact API calls. `tests/test_ground_truth_labels.py` uses real in-memory Ed25519 keys for source tampering, reviewer authorization, missing evidence, CLI behavior and no-promotion outcomes. Both run in the Python 3.10/3.12/3.13 CI matrix.

Future work: protected independent reusable test-builder definitions with immutable action pins, unbiased genuine-repository case sampling and human-reviewed omissions, documented inter-annotator agreement, and separately enforced release gates. Those are deployment/research steps, not solved by synthetic CI tests.
