# R8.04j — Preregistered, blinded human-review evaluation

**Delivered:** a source-pinned study plan, separate Ed25519 registrar signature, frozen two-person adjudicator roster, three-way `defect / clean / uncertain` decisions, exact source/evidence replay, and inter-rater agreement with disagreement escalation.

**Not delivered by CI:** real independent external human labels, objective defect truth, a trusted registration timestamp, unbiased population estimates, or permission to approve/publish/merge.

## Study states and trust boundaries

```text
Immutable real Git HEAD + BASE
       |
       v
opportunity-sample  -->  blind.json (human-review scope only)
       |              -->  private.json (model flags, operator ONLY)
       v
study-plan          -->  plan.json (no model flags, fixed case IDs + two reviewers)
       |
       v
EXTERNAL registrar signs exact plan using enrolled study_registrar Ed25519 key
       |
       v
Operator independently commits/anchors signed registration hash BEFORE labels
       |
       v
Two separate human reviewers get ONLY blind.json, investigate, sign observations
       |
       v
study-audit --> verify pinned registration, source Git objects, 2 enrolled keys,
                signed source cases, evidence bytes, uncertainty and agreement
       |
       v
Advisory sample observations ONLY; no release/merge authority
```

The tool **does not create or store human private keys** and never models a human label. Cryptographic signatures prove key control and document integrity, not that a reviewer is independent, actually blinded, or correct.

## 1. Freeze the eligible source frame

Run the existing `opportunity-sample` on a repository checkout with full Git history and pinned, immutable 40-character base/HEAD commits. Use a 0700 private output directory.

```bash
daddy-reviews opportunity-sample \
  --root PATH/TO/CLONE \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_SHA --head HEAD_FULL_SHA \
  --real-sample-seed "study-sealed-seed-2026-11" \
  --real-sample-max-cases 48 \
  --real-blind-output ./operator-private/blind.json \
  --real-private-output ./operator-private/private.json
```

If your evaluation includes an R8.02 completed model report, pass `--real-model-report PATH/TO/report.json` **both** during sampling and during subsequent study commands. Without the report, the study can authenticate source labels but cannot calculate model outcome measures.

### Freeze the research protocol

Choose a stable study ID, two independent reviewer IDs and a claimed UTC registration time (ISO 8601 ending in `Z`). Registration times are **self-declared**, not externally verified.

```bash
daddy-reviews study-plan \
  --root PATH/TO/CLONE \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_SHA --head HEAD_FULL_SHA \
  --real-sample-seed "study-sealed-seed-2026-11" \
  --real-sample-max-cases 48 \
  --real-blind-file ./operator-private/blind.json \
  --real-private-file ./operator-private/private.json \
  --study-id "independent-defect-study-2026" \
  --study-reviewers "researcher-one,researcher-two" \
  --study-registered-at "2026-11-11T12:00:00Z" \
  --study-plan-output ./operator-private/study-plan.json
```

The CLI **recreates the whole Git source opportunity frame** and refuses a plan if the proposed blind packet or private ledger differs. The plan records repository name and numeric ID (operator-pinned), two source commits, frame and private ledger hashes, planned sampled case IDs/source hashes/public scopes, the exact two authorized reviewer IDs, decision rubric, uncertainty handling and scoring limits. It excludes model rules and flagged decisions.

The `study-plan` command writes an owner-only non-overwriting file and reports `plan_sha256`, `registration_signed: false`, and `chronology_independently_proven: false`. This output is **not yet a signed preregistration**.

## 2. Sign and anchor the exact study registration

An operator with separate, trusted `study_registrar` identity must sign an envelope:

```json
{
  "format": "daddy-reviews-signed-study-registration-v1",
  "plan": {"...": "exact contents of study-plan.json"},
  "registrar_id": "study-operator",
  "key_id": "registrar-public-key-id",
  "signature_b64": "BASE64_ED25519_SIGNATURE"
}
```

The signature is calculated over `daddy_reviews.study_protocol.registration_signing_bytes(registration)`, which excludes `signature_b64` and includes a domain-separated canonical JSON payload. Sign **outside the evaluation runner** using an enrolled Ed25519 private key. The trusted public key registry uses:

```json
{
  "registrar-public-key-id": {
    "reviewer_id": "study-operator",
    "role": "study_registrar",
    "enabled": true,
    "public_key_b64": "BASE64_RAW_ED25519_PUBLIC_KEY"
  }
}
```

Store the **whole signed registration** as `registration.json`. Its canonical object SHA-256 is obtained using `daddy_reviews.human_attestation.sha256_json(registration)` (not `sha256sum` over whitespace-formatted JSON). Save that digest **in a separate, operator-controlled location** and independently commit/timestamp-anchor it *before reviewers see cases*. A regular Git commit, protected revision history, or trusted timestamp service can supply independently observable evidence, but this program **does not verify that external chronological evidence**.

The study is not scientifically preregistered simply because the signed document includes an earlier `registered_at` string. Results always say `preregistration_chronology_independently_proven: false`.

## 3. Independent observations with an uncertainty state

Distribute **only the original blind packet** and necessary source/reproduction access to the two frozen researchers. Do not reveal the model report, private ledger, study outcomes or each other's judgments.

Each researcher supplies one signed `daddy-reviews-study-adjudicator-record-v1` per sampled `case_id` with:

- `study_plan_sha256`: exact digest of the frozen signed plan;
- `case_id`, `source_sha256`, `line_sha256`, `head_commit`: exactly as in the frozen plan;
- `reviewer_id`, `key_id`: predeclared human and their separately registered `ground_truth_adjudicator` public key;
- `decision`: **`defect`, `clean`, or `uncertain`**;
- `blind_protocol`: exactly `separate_from_model_and_resolution_v1`;
- `signed_at`: a UTC timestamp later than the claimed registration time; `rationale`: 20–1600 characters;
- `evidence_sha256`: SHA-256 of independent reproduction/inspection evidence bytes, stored at `EVIDENCE_DIRECTORY/<lowercase-sha256>`;
- `signature_b64`: Ed25519 signature over `daddy_reviews.study_protocol.observation_signing_bytes(record)`.

The verification registry contains the two independently enrolled `ground_truth_adjudicator` keys, with `reviewer_id`, `role`, `enabled` and `public_key_b64`. The registrar's public key, user identity and authority are **separate**. No reviewer can change the study roster retroactively. Duplicate signatures, wrong roles, swapped source or evidence hashes, shared signer keys, post hoc decision edits and inconsistent signatures are rejected.

Researchers can leave cases pending. A signed `uncertain` decision remains uncertain; it is **not** silently coerced into a defect or a clean result.

## 4. Audit frozen study without trusting submitted label JSON

```bash
daddy-reviews study-audit \
  --root PATH/TO/CLONE \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_SHA --head HEAD_FULL_SHA \
  --real-sample-seed "study-sealed-seed-2026-11" \
  --real-sample-max-cases 48 \
  --real-blind-file ./operator-private/blind.json \
  --real-private-file ./operator-private/private.json \
  --study-registration-file ./operator-private/registration.json \
  --study-registration-sha256 INDEPENDENTLY_PINNED_CANONICAL_SHA256 \
  --study-registrar-keys-file ./operator-private/registrar-public-keys.json \
  --label-attestations-file ./operator-private/signed-human-observations.json \
  --label-trust-keys-file ./operator-private/adjudicator-public-keys.json \
  --label-evidence-dir ./operator-private/reproduction-evidence
```

Add `--real-model-report` here only if used during original sampling and plan generation.

`study-audit` rejects a forged/changed registration digest or signature and **recreates the entire source frame from immutable Git objects**. It requires the plan's exact frame/case list, original blind and private hashes, frozen reviewer identities, signatures, intact evidence and reported timestamps. It never executes evidence.

It reports coverage and unresolved cases, plus **raw paired agreement and three-category Cohen's kappa** over cases with two signed observations. Kappa may be `null` for no fully paired cases or degenerate marginals. Agreement is not the same as label correctness. Both reviewers selecting `uncertain` counts toward raw categorical agreement but blocks scoring.

If any case is unsubmitted, disputed or mutually uncertain, `status=pending_or_disputed_human_adjudication`, `sample_observations=null`, and the CLI exits **2**. If every case is resolved and model output was present, only descriptive unweighted *added-line sample* precision/recall and separate context discovery counts are returned. If there was no model report, prediction metrics remain null.

**Every result:** `factual_defect_truth_proven=false`, `population_accuracy_claim=false`, `model_quality_approved=false`, `promotion_eligible=false`, `github_publication=none`, `merge_action=none`.

## Real GitHub integration

[Preregistration Protocol Preview](../.github/workflows/study-preregistration-preview.yml) reads genuine tracked Git objects, runs the real source sampling and preregistration planner, and uploads a seven-day `daddy-unsigned-study-plan-preview` artifact containing **only the unsigned plan and safe summary**. It never uploads the private ledger, unblinds a model, creates human signatures or claims that a study is chronologically registered. The two preview reviewer names are sample identities and **not real enrolled humans**.

CI uses generated test-only Ed25519 keys and real temporary Git commits to verify signed source binding, independent roles, no-overwrite plan files, 3-way uncertainty, partial labels, conflicting reviewers, missing evidence, registrar spoofing, hash tampering and disagreement/no-promotion. These tests **cannot serve as empirical reviewer-quality data**.

## Remaining release gates

1. Freeze repository selection and the complete study protocol in a separately timestamp-authenticated immutable record, with policy-controlled access.
2. Recruit real independently identified researchers, ensure blinding and prevent shared data/LLM contamination; securely manage their enrolled signing keys.
3. Collect actual reproduction evidence and adjudicate uncertain/conflicting cases with a separate predeclared procedure; do not reclassify them post hoc.
4. Define a defect-level sampling unit and representative study design with bias analysis, sample-size justification, inter-annotator error analysis and held-out test populations before publishing model accuracy.
5. Keep autonomous PR approval, model promotion and merge blocking disabled until a **separate explicit release authority** accepts the evidence and safety policy.
