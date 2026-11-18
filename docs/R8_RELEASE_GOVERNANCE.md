# R8.05b — Production release governance and runner privilege isolation

**Status:** Implementation and CI security checks delivered; **GitHub release-policy approval blocked** until the repository administrator enables protected-branch controls. This is a read-only audit, not a branch-configuration tool.

## Actual GitHub configuration observed — 18 November 2026

Repository `cognetheus/daddy-reviews` (GitHub numeric ID **1431087545**, default branch `main`) currently reports:

| GitHub evidence | Observation |
|---|---|
| `GET /repos/cognetheus/daddy-reviews/branches/main` | `protected: false` |
| `GET /repos/cognetheus/daddy-reviews/rulesets?includes_parents=true` | empty array, no applicable rulesets returned |
| `GET /repos/cognetheus/daddy-reviews/branches/main/protection` | HTTP 403, connector lacks branch-protection-read permission |
| GitHub Actions CI | Python 3.10/3.12/3.13 tests and actual Sigstore integrations have run, but this **does not protect the branch** |

**Therefore:** a green test suite must **not** be used as evidence that this repository has protected release governance. The actual `main` branch is presently unprotected. The GitHub App's 403 does not grant permission to change this, and Daddy Reviews does not silently create or weaken protection.

## R8.05b code improvements

### 1. Read-only branch governance auditor

`src/daddy_reviews/release_governance.py` provides `verify_live_branch_governance()`, backed by an explicitly supplied read-only GitHub API token and SHA-256-pinned official `gh` executable. It checks three exact HTTPS GET responses:

1. `/repos/OWNER/REPO` — repository numeric identity, exact full name, default branch, not archived/disabled.
2. `/repos/OWNER/REPO/branches/main` — immutable expected head commit and GitHub-reported protected flag.
3. `/repos/OWNER/REPO/branches/main/protection` — authenticated classic branch-protection policy.

The policy demands all of these conditions:

| Control | Minimum |
|---|---|
| Required reviews | **2 distinct approvals**, dismiss stale approvals, require code-owner approval |
| CI checks | Required exact `test (3.10)`, `test (3.12)` and `test (3.13)`, in strict up-to-date mode |
| Administrator bypass | `enforce_admins.enabled=true` |
| Unresolved discussion | `required_conversation_resolution.enabled=true` |
| Force pushes and deletion | Explicitly disabled |
| Branch identity | `main`, exact commit, correct numeric repository ID, `protected=true` |

This implementation deliberately requires readable **classic branch-protection API evidence**. Rulesets alone are not silently interpreted as equivalent: ruleset bypass/target semantics would require a separate audited verifier. A 403, 404, missing or malformed policy, stale source commit, or insufficient reviews produces `blocked_branch_security_gate`; a missing token, unsafe repository identity or unauthenticated metadata fails outright.

Run from a trusted operator host using a fine-grained credential allowed **repository Administration: read**, or another suitably scoped read-only installation token:

```bash
export GH_TOKEN="...operator-provided-read-only-token..."
gh_binary="$(readlink -f "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_binary" | cut -d ' ' -f1)"
head_sha="$(git rev-parse HEAD)"

daddy-reviews branch-governance-audit \
  --root . \
  --attestation-repo cognetheus/daddy-reviews \
  --attestation-repo-id 1431087545 \
  --attestation-commit "$head_sha" \
  --governance-branch main \
  --gh-binary "$gh_binary" \
  --gh-binary-sha256 "$gh_sha"
```

The operator's local checkout must be at the GitHub branch's **current exact HEAD** for that pinned SHA to pass. A blocked policy prints a machine-readable gap list and exits **2**. An authenticated policy match reports `authenticated_branch_policy_verified` but **still** sets `release_authorized=false`, `human_signoff_required=true`, `merge_action=none` and `github_publication=none`. Branch protection alone never authorizes a release.

### 2. Actual admin configuration needed

In repository **Settings → Branches → Branch protection rules**, create or strengthen protection for `main`, requiring two approving reviews, stale-review dismissal, CODEOWNERS, up-to-date required CI checks, admin enforcement, conversation resolution, and explicitly disabled deletion/force pushes. Protect workflow and security-policy changes through mandatory code-owner review. The new `.github/CODEOWNERS` maps production-sensitive workflows, source and dependency configuration to repository owner `@cognetheus`.

Repository collaborators must be chosen deliberately; two approving GitHub accounts are not the same as two independent people. The operator should confirm rules actually apply with a sufficiently privileged **read-only** inspection credential. There is no automatic branch-protection mutation in this change.

### 3. Isolated OIDC signing for the original Sigstore workflow

Previously `.github/workflows/attestation-integration.yml` ran checkout, package install, pytest and OIDC attestation in one privileged job.

The upgraded real workflow separates:

```text
prepare-artifact (untrusted source, pytest, contents:read, no OIDC)
            |
            v
sign-only (OIDC + attestations:write; NO checkout / Python / shell)
            |
            v
verify-genuine-github-attestation (read-only checkout + artifact verification)
```

The signer uses only the approved, immutable SHA-pinned `actions/download-artifact` and `actions/attest`. Untrusted repository code has no signing token, and the verifier has `attestations:read` only. The CI checkout no longer persists GitHub credentials and has explicit read-only top-level permission. Every workflow is statically checked for GitHub-hosted runners, explicit restrictive permissions, absence of `pull_request_target`, and credential-free checkout.

Tests include adversarial GitHub API snapshots, 403/404 fail-closed behavior, CI-bypass and stale check rejection, forged IDs and booleans, signer code-execution exclusion, and runner/permission regressions. These tests cannot validate administrator-controlled GitHub protection configuration; that requires the live audit above.

## Remaining R8.05 work

- **Administration required:** actually enable and verify `main` protections and workflow CODEOWNERS enforcement. This is currently the largest external blocker.
- Pin reproducible runtime/transitive dependency graph, audit Python/TypeScript/.NET package behavior, and decide reproducible build strategy.
- Stress-test bounded readers, memory/duration limits, token handling, rate limits and incident rollback.
- Establish operational SLOs, observability, evidence retention, failure alerts and operator-controlled release authorization.
- Finish independent real-human evaluation for R8.04k. Do not enable autonomous PR approval or merging.

Reference: [GitHub branch protection docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) and [GitHub Actions security](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions).
