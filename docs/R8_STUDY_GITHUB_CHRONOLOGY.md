# R8.04k — External GitHub chronology and real human study handoff

**Status:** Implemented code and negative tests; no genuine preregistered human study has been completed. The GH Actions anchor workflow must be manually dispatched by a real registrar and two separate enrolled GitHub accounts for a study. A green CI fixture does not make the study genuine.

R8.04j signed a preregistration and human observations, but could not independently tell when the operator froze those commitments. R8.04k adds an *external GitHub-hosted run created-at and account-ID check* for one study-registration commitment and two distinct reviewer-label receipts. Its trust anchor is GitHub's authenticated REST records and workflow run titles, not a timestamp embedded inside the study JSON.

**Scope of evidence:** It proves the GitHub API reports that three specific, pinned actors dispatched an immutable-hash commitment in the expected order. It does **not** independently prove that researchers personally studied code, were blinded, used separate identities, discovered genuine defects, or signed documents at the claimed local time. Workflows may be changed by repository administrators unless protections prevent it.

## Dedicated anchor repository — security boundary

Prefer a **separate, empty, operator-controlled study-anchor repository** rather than granting human adjudicators write access to production code. To manually dispatch a GitHub Actions workflow, those accounts generally need write access to the repository containing it. The anchor repo must contain no production secrets, deployment permissions or build pipelines. Protect the anchoring workflow, restrict and audit collaborators, and protect the trusted branch. Its filename must be `.github/workflows/study-evidence-anchor.yml`; install that same audited definition in the anchor repo.

The public GitHub Actions workflow accepts only three text inputs: `kind` (`registration` or `reviewer`), `study_sha256`, and `payload_sha256`. It validates SHA-256 string shapes and runs without checking out any repository source, using GitHub OIDC, uploading any file, executing a code-review process, or writing to a repository. GitHub's generated run **display title** is:

```text
Daddy Study Anchor | KIND | REGISTRATION_SHA256 | PAYLOAD_SHA256
```

The independent verifier accepts only the exact title, workflow path, numeric workflow ID, numeric GitHub repository ID, head source SHA and branch, workflow_dispatch event, first attempt, successful completion, and expected numeric GitHub actor/triggering actor. A rerun of an old workflow does not count. All requests use an operator-pinned SHA-256 of the `gh` CLI executable and a read-only `GH_TOKEN`.

## 1. Finish a signed plan; freeze GitHub account enrollment

First create a `study-plan` from actual Git sources (see [R8.04j](R8_PREREGISTERED_STUDY.md)). The registrar separately signs the resulting JSON using their already enrolled Ed25519 `study_registrar` key; store it as `registration.json`. Independently pin the canonical SHA-256 using `sha256_json(registration)`.

Obtain the **numeric GitHub IDs** of the independent registrar and two reviewer accounts from trusted GitHub user records; do not use mutable display names. Determine the numeric GitHub workflow ID for your isolated anchor repository, e.g.:

```bash
gh api /repos/OWNER/ANCHOR_REPO/actions/workflows/study-evidence-anchor.yml --jq .id
gh api /users/REGISTRAR_LOGIN --jq .id
gh api /users/REVIEWER_ONE_LOGIN --jq .id
gh api /users/REVIEWER_TWO_LOGIN --jq .id
```

Now produce an owner-only, *non-overwritable* enrollment contract:

```bash
daddy-reviews study-enrollment \
  --root . \
  --study-registration-file ./private/registration.json \
  --study-registration-sha256 SIGNED_REGISTRATION_CANONICAL_SHA256 \
  --study-anchor-repository OWNER/ANCHOR_REPO \
  --study-anchor-repository-id NUMERIC_ANCHOR_REPO_ID \
  --study-anchor-workflow-id NUMERIC_WORKFLOW_ID \
  --study-anchor-branch main \
  --study-registrar-actor-id NUMERIC_REGISTRAR_GITHUB_ID \
  --study-reviewer-actors researcher-one:NUMERIC_REVIEWER_ONE_ID,researcher-two:NUMERIC_REVIEWER_TWO_ID \
  --study-enrollment-output ./private/enrollment.json
```

The emitted `enrollment_sha256` binds the exact signed registration hash, anchor repository identity, workflow ID, branch, and both reviewer account IDs. **Do not assign reviewer accounts later.** This digest is the payload of the first GitHub registration anchor. The enrollment file itself stays private; GitHub receives only hashes.

## 2. Registrar anchors the study BEFORE reviewing

The registrar, authenticated to their already pre-enrolled GitHub account, manually dispatches:

```bash
gh workflow run study-evidence-anchor.yml \
  -R OWNER/ANCHOR_REPO -r main \
  -f kind=registration \
  -f study_sha256=SIGNED_REGISTRATION_CANONICAL_SHA256 \
  -f payload_sha256=ENROLLMENT_CANONICAL_SHA256
```

Wait for that specific workflow run to finish successfully. Record its numeric `run_id` and exact 40-character `head_sha` (workflow source commit). The **registration payload is the enrollment digest**, not a copy of the signed study hash.

Prepare `anchors.json` with the precommitted enrollment from `enrollment.json`:

```json
{
  "format": "daddy-reviews-github-study-anchor-manifest-v1",
  "anchor_repository": "OWNER/ANCHOR_REPO",
  "anchor_repository_id": 123456,
  "workflow_id": 9876543,
  "head_branch": "main",
  "enrollment": {"...": "exact contents of enrollment.json"},
  "registration": {
    "run_id": 11111,
    "actor_id": 22222,
    "head_sha": "0123456789abcdef0123456789abcdef01234567"
  },
  "reviewers": []
}
```

The `{ "...": "..." }` placeholder above must be replaced with the entire actual enrollment object. With a sufficiently scoped **read-only** GitHub token (`GH_TOKEN`), verify this registration alone:

```bash
gh_binary="$(realpath "$(command -v gh)")"
gh_sha="$(sha256sum "$gh_binary" | cut -d' ' -f1)"

daddy-reviews study-anchor-verify \
  --root . \
  --study-registration-file ./private/registration.json \
  --study-registration-sha256 SIGNED_REGISTRATION_CANONICAL_SHA256 \
  --study-anchor-manifest-file ./private/anchors.json \
  --gh-binary "$gh_binary" \
  --gh-binary-sha256 "$gh_sha"
```

Output `github_registration_anchor_matched` means an authenticated GitHub server record matches the registration and enrollment digests. It is **not** a verification of the registrar's Ed25519 signature or reviewer outcomes; `study-audit` performs those checks separately.

## 3. Two genuine reviewers work independently and submit receipts

Distribute **only the blind packet** and necessary source context to the two frozen researchers. They independently research every assigned case and create Ed25519-signed `defect`, `clean`, or `uncertain` observations with supporting reproduction/negative-case evidence. Never ask the model to create these verdicts or share the sealed prediction ledger with researchers.

After each reviewer has signed every sampled case, compute their personal receipt digest:

```bash
daddy-reviews study-review-receipt \
  --root . \
  --study-registration-file ./private/registration.json \
  --study-registration-sha256 SIGNED_REGISTRATION_CANONICAL_SHA256 \
  --label-attestations-file ./private/signed-human-observations.json \
  --study-reviewer-id researcher-one
```

The returned `payload_sha256` binds **all** of that reviewer's signed observations by case ID. The digest generator does not independently verify signatures; use the audit command for that.

The reviewer logs into their precommitted GitHub account and manually dispatches:

```bash
gh workflow run study-evidence-anchor.yml \
  -R OWNER/ANCHOR_REPO -r main \
  -f kind=reviewer \
  -f study_sha256=SIGNED_REGISTRATION_CANONICAL_SHA256 \
  -f payload_sha256=REVIEWER_ONE_PAYLOAD_SHA256
```

Repeat from the **second** account with its **own** signed-bundle digest. Save each account's numeric GitHub run ID and head commit. Add two entries to `anchors.json`:

```json
"reviewers": [
  {"reviewer_id":"researcher-one", "run_id":11112, "actor_id":33333,
   "head_sha":"0123456789abcdef0123456789abcdef01234567"},
  {"reviewer_id":"researcher-two", "run_id":11113, "actor_id":44444,
   "head_sha":"0123456789abcdef0123456789abcdef01234567"}
]
```

Reviewers are *not* allowed to share the registrar account, each other's account, or a signing key. The verifier cross-checks the account IDs against the enrollment SHA committed in the **earlier** registration run. GitHub timestamps must be strictly ordered: registrar run created first, then separate researcher receipt runs. Signed observation timestamps must be consistent with those platform timestamps. GitHub timestamps do not prove when the actual independent inspection occurred.

## 4. Combined real-source, signatures, agreement and GitHub chronology audit

Run the existing `study-audit` with its full source/label/trust/evidence flags (see [R8.04j](R8_PREREGISTERED_STUDY.md)), and add:

```bash
  --require-live-study-anchors \
  --study-anchor-manifest-file ./private/anchors.json \
  --gh-binary "$gh_binary" \
  --gh-binary-sha256 "$gh_sha"
```

This first re-derives the immutable Git sampling frame, validates the signed registrar registration, two independent enrolled Ed25519 signers, signed case labels, evidence hashes, reviewer agreement, unresolved cases and the original read-only model report. Then it queries **three separate GitHub Actions runs** using the read-only authenticated API, checking exact digest-bound workflow identities and chronological order.

With an authentic complete chain, the report includes `external_chronology` with `externally_authenticated_GitHub_run_metadata=true` and identifies the GitHub-created timestamps. If any evidence is missing, the required GitHub API call fails, results are disputed, the workflow was rerun, the actor was switched, the enrollment was modified after registration, or a signed receipt digest differs, the CLI fails closed and does **not** emit a success report.

## Non-negotiable limitations

- The source and signed label assertions must come from **actual, independently supervised human review** to be scientifically valid; CI uses synthetic signed fixture labels.
- GitHub Actions `created_at` is a GitHub-hosted server record, and its report is obtained over authenticated HTTPS. This is not a hardware-trusted timestamp, a Sigstore-backed source-code signature, or proof of genuine human independence.
- Independent GitHub accounts are not automatically independent people. Enrollment/trust management is a separate organizational responsibility.
- Grant **no outside reviewers write access to the production codebase** merely so they can dispatch anchors. Use an empty dedicated research anchor repo with protected workflows and explicit permissions; separately validate those protections.
- PR-wide recall, unique bug discovery, issue deduplication and uncertainty-adjusted statistical confidence require a properly designed independent study; the source-line sampling frame remains biased.
- Neither anchor verification nor successful source/label audit authorizes AI promotion, PR comment publication, autonomous approvals or merge blocking.

Official GitHub references: [Manual workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) and [Workflow runs API](https://docs.github.com/en/rest/actions/workflow-runs).
