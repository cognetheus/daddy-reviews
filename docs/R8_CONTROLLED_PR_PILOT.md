# R8.06 — Controlled, read-only GitHub pull-request pilot

**Delivery:** Source-pinned live GitHub PR ingestion, scoped advisory-only workflow, bounded pilot cohort telemetry, failure/stop conditions, regression tests and operator runbook. **This implementation has no autonomous publication, approval, merge or production release path.**

## Trust boundaries

```text
Open GitHub PR (untrusted)
     |
     +----> GitHub API GET PR / per-file patches / GET PR again
     |          - numeric repo ID; open state; exact expected head + base
     |          - <=40 files, <=262144-byte combined patch, <=65536-byte responses
     |          - per-file added/deleted counts rederived from actual patch
     |
     +----> Untrusted PR checkout (exact head SHA; no package install)
                     |
                     v
Trusted **base-commit** Daddy Reviews CLI (installed separately)
                     |
                     v
    Local bounded source evidence packet, human review required
                     |
             +-------+-------+
             |               |
     Private owner-only     Public source-free summary
     full review report     GitHub Actions artifact (7 days)
     **NOT uploaded**       no source, paths, findings or raw text
                     |
                     v
        Operator-controlled pilot-cohort (offline)
        *candidate* p95/errors/stop triggers ONLY
                     |
                     v
         Real humans validate each defect; release is BLOCKED
```

### R8.06a — Live pull request command

Use Python 3.10+ with verification dependency installation from a trusted checkout:

```bash
cd ~/dev/daddy-reviews
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[verification]'

# Inspect a specific, currently OPEN PR. Ensure /path/to/pr-source
# is checked out to exactly that PR's head SHA. Never execute its code.
# The token requires contents:read and pull-requests:read only.
export GH_TOKEN='...read-only-token...'
gh_exe="$(realpath "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_exe" | cut -d' ' -f1)"

.venv/bin/daddy-reviews pilot-pr \
  --root /path/to/pr-source \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id NUMERIC_REPOSITORY_ID \
  --pr PR_NUMBER \
  --expected-head-sha EXACT_40_CHARACTER_HEAD_SHA \
  --gh-binary "$gh_exe" \
  --gh-binary-sha256 "$gh_sha" \
  --pilot-private-output /private/operator-folder/pr-report.json \
  > /private/operator-folder/pr-summary.json
```

Full findings are written in a new **owner-only 0600** file, exclusively (no overwrite or symlink target), for human investigation. The stdout summary has only source-free counts/digests. A 403, invalid credentials, unexpected GitHub API structure, 40-file limit exceeded, missing/binary/truncated text patch or changed head/base fails closed. **No partial result may imply full diff coverage.**

This process rejects PRs with any missing per-file `patch`. Binary-only, very large, metadata-only renames and other unsupported changes are intentionally **abstentions**, not defect-free approvals. Review candidates are heuristic and unverified; never assume a clean advisory report means no defects.

### R8.06b — Cohort tracking

Collect only genuinely observed source-free `pilot-pr` summaries from successive real PRs as a JSON array (max 50 records). One PR number counts once, even across multiple sync commits. Then:

```bash
daddy-reviews pilot-cohort \
  --root . \
  --pilot-summaries-file /private/operator-folder/pr-summaries.json \
  --pilot-min-prs 5 \
  --pilot-p95-ms 60000 \
  --pilot-max-findings 20
```

The monitor tracks independent PR count, candidate findings, patch-line totals, p95 review latency and local alert codes. With fewer than five distinct PRs or a threshold violation, it prints an explicit `pilot_stop_or_insufficient_evidence` result and exits 2. Otherwise it prints `local_pilot_candidate`, meaning **continue human-supervised shadow operation only**. The source-free JSON input is **self-reported and unauthenticated**; its aggregate cannot prove human agreement, false-positive rate, missed defects or live API authenticity.

Human reviewer must independently reproduce findings, track confirmed/false positive/unresolved cases and misses using the signed R8.04k study protocol. Until actually recorded by independent people, `false_positive_rate` and `missed_defect_rate` are `null`.

### R8.06c — Real GitHub Actions workflow

[Advisory PR Pilot](../.github/workflows/advisory-pr-pilot.yml) activates for non-draft PRs on `opened`, `synchronize`, `reopened` or `ready_for_review`. It has **no `pull_request_target` event**, no OIDC, no write-scope access, no model API invocation, no posting and no merge. It uses two separate checkouts: trusted tool code from the PR's **base commit**, and untrusted source from `refs/pull/NUMBER/head` without stored GitHub checkout credentials. Only the trusted tool code is installed into Python. PR checkout HEAD is compared to a separately pinned API head SHA, both before and after reading the bounded per-file patch. GitHub's API response is refetched after processing to catch a concurrent update.

The workflow publishes only `daddy-pr-advisory-summary` for seven days, containing summary counts/digests, no code or paths. Private findings remain on the runner and are discarded at job end; the workflow is intentionally **not a mechanism to deliver full review source**. For local Claude Code usage, run `pilot-pr` with `--pilot-private-output` and have Claude inspect it as an **untrusted candidate packet**.

**No open PR at implementation start** means integration tests were initially mocked, with real Git source/commit checks in other workflows. Do not infer a successfully exercised real PR from a green unit test. The actual PR workflow run must appear on a genuine pull request.

## Confirmed live end-to-end integration — November 20, 2026

The actual workflow was exercised on [PR #1 — R8.06 SHADOW PILOT, DO NOT MERGE](https://github.com/cognetheus/daddy-reviews/pull/1), a harmless new Python source file in a separate branch. The first temporary fixture version contained literal `\\n` sequences (invalid Python), which correctly made the graph-cache CI fail closed instead of claiming an incomplete index was a full hit. The fixture was corrected to real newlines in PR head `cac5fddf6911edbd02c2003b3e2cffc88e7d288c`.

- [Actual read-only PR analysis](https://github.com/cognetheus/daddy-reviews/actions/runs/44776590365): **completed / success** on corrected PR head.
- [Initial real PR analysis](https://github.com/cognetheus/daddy-reviews/actions/runs/44775887578): also passed on the original fixture, confirming the distinct advisory path; the CI graph-cache failure was separate and fixed in the PR fixture.
- The Actions run uploaded only `daddy-pr-advisory-summary` as a bounded artifact; private findings were not uploaded.
- Authenticated GitHub PR API reported **zero pull-request reviews, zero inline comments and zero issue comments; the PR remains open and unmerged** at verification.
- The user-facing PR is deliberately **not for merging**. Closing it later is a separate human decision.
- This is exactly **one** real PR. It verifies workflow wiring and source protections, **not** the five-PR cohort floor, reviewer sensitivity/precision or independent human defect truth.

Until five distinct real source PRs and genuine adjudications exist, `pilot-cohort` cannot establish a statistically meaningful reviewer-quality claim, and branch protection must still be configured by an administrator.

## Operator acceptance and manual rollback

| Gate | Candidate target | Enforcement |
|---|---|---|
| Exact GitHub source | Open PR + numeric repo ID + head SHA stable | Hard failure, no output |
| Scope integrity | Every non-binary textual patch present, counts match | Hard failure/abstention |
| Permissions | No write token, no source package install | CI static checks + human policy |
| Pilot cohort | >=5 unique real PRs, p95 <=60s, <=20 unverified findings/PR | Advisory monitor; breach triggers halt |
| Quality | Independently validated labels, conflicts and missed defects | External R8.04k requirement; NOT claimed |
| GitHub branch protection | 2 approving reviews, CODEOWNERS, required CI, no direct pushes | External administrator task; currently unprotected |
| Release | Explicit human operator review, signed decision and rollback proof | Not automated; no authority granted |

On a TOCTOU error, malformed source scope, outage, failed CI, missing human review, unexpected publishing, evidence tamper or latency breach: **stop pilot expansion**, never downgrade a failure to a clean review, and retain only bounded diagnostic digests. An authorized human must disable the workflow or remove pilot invocation while reviewing GitHub audit logs and incident cause. No automatic replay of publishing requests is supported. To roll back any production changes, use a protected, reviewed PR after actual branch protection is enabled.

**Release stance:** R8.06 provides real live-PR **advisory infrastructure**, not autonomous PR-review quality certification or approved v2.0. The complete release remains gated on actual independent human findings and measured quality, authenticated protected `main`, complete supply-chain assurance and explicit operations owner approval.
