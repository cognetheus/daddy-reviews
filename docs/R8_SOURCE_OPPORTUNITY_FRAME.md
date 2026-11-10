# R8.04i — Outside-diff source opportunity sampling

**Status:** implemented source-intake and adjudication protocol. Real GitHub integration passed. Independently reproduced, externally human-labeled defects have **not** been collected, and there is no production model accuracy claim.

## Problem and scope boundary

R8.04h sampled only added lines. That usefully exposed model-nominated and model-unflagged additions, but it could not investigate errors in unchanged lines and untouched files. R8.04i introduces a separate, versioned *nonblank source line-anchor* sampling frame covering tracked **regular Git blobs** at a pinned HEAD commit.

This is intentionally **not** a universal defect recall estimator:

- A diff-only reviewer has a defined right to report only added lines. A bug in untouched code must **not** be counted as a false negative for that reviewer.
- A sampled nonblank line is not a unique defect or an independent failure opportunity. Full bug attribution can span files, lines and historical behavior.
- The four sampling buckets depend on model flags, and deterministic SHA-256 ranks do not make the sample an independent random draw with a known probability. Raw sample precision/recall is therefore biased.
- A signed human label certifies key-controlled authorship and intact supporting evidence, not that the defect is real, that two operators were actually blinded, or that the model is accurate.

## Sample definition

All source comes from immutable local Git objects, never the mutable working file's bytes. Supported extensions include Python, JavaScript/TypeScript, Java, C#, and Go. Git symlinks, submodules, binary/overlarge blobs, unsafe paths and ambiguous tree entries are never treated as source.

Every eligible nonblank tracked line is classified publicly into:

| Public source scope | Meaning | Model FN eligible? |
|---|---|---|
| `added` | A nonblank added line in the base→head diff | Only if a completed matching diff-only model report exists |
| `unchanged_touched` | Unchanged line inside a file touched by the diff | **No** |
| `unchanged_other` | Line in a file untouched by the diff | **No** |

Inside the **private-only** ledger, `added` is divided into `added_flagged` and `added_unflagged`. The draw rotates across the four private buckets, using seed-derived SHA-256 ordering within each. The resulting sample covers multiple source scopes when capacity permits. This is a deliberately stratified operational study, not a statistically representative sample.

The explicit frame reports counts of eligible lines by public scope, selected cases and excluded Git entries. Private report-only counts and model rules are never added to the blind packet.

## 1. Collect and freeze a source frame

Use a real local clone with both commits available. `HEAD` must equal the full requested head SHA; base must be an ancestor. The operator must independently know the repository name and immutable GitHub numeric ID; local Git itself does not authenticate GitHub ownership.

```bash
mkdir -p ./study-private
chmod 700 ./study-private

daddy-reviews opportunity-sample \
  --root ./reviewed-repository \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_40_CHAR_SHA \
  --head HEAD_FULL_40_CHAR_SHA \
  --real-sample-seed "precommitted-study-seed-2026-11" \
  --real-sample-max-cases 48 \
  --real-blind-output ./study-private/blind.json \
  --real-private-output ./study-private/private-ledger.json
```

Add `--real-model-report ./completed-investigation.json` only if you have an R8.02 specialist investigation report with matching diff SHA-256, valid source citations and completed status. Do not invent or alter the report. Without a completed model report, only the source frame is produced and **no prediction metrics are possible**.

The collector executes only bounded Git read commands and exports two **distinct, owner-only (`0600`), exclusively created** JSON files. Symlinked output paths and writable shared directories are rejected, and existing files are not overwritten. The CLI prints a safe, metadata-only summary.

Send **only `blind.json`** to blinded researchers. It includes source location, public source scope, source/line SHA-256, at most 200 characters of untrusted code text and study instructions. It includes no model verdicts, rules, hidden flagged bucket or proposed human label.

Keep `private-ledger.json` inaccessible to them. It includes model flags and rules for added lines, scope markers, eligibility counts, hashes and a binding to the original blind packet. Open the ledger only after all independent human decisions are signed.

## 2. Collect separately signed human labels

For each blind case, two or more independently enrolled `ground_truth_adjudicator` identities must research and reproduce (or rule out) the alleged problem. Consider tests, surrounding source context, baseline behavior, negative examples and the possibility of uncertainty. Do not force uncertain human outcomes into `defect`/`clean`; unresolved cases should remain pending rather than be silently scored.

Each adjudicator signs a `daddy-reviews-ground-truth-label-v1` document using `label_signing_bytes(record)` and their registered Ed25519 key. Bind:

- `case_id` and `candidate_id`: both the blind case ID;
- `snapshot_id`: the exact HEAD commit SHA;
- `patch_sha256`, `tier`: the frozen blind packet's values;
- `label` (`defect` or `clean`), enrolled `reviewer_id` and `key_id`, signed UTC timestamp, blind-protocol declaration and substantive rationale;
- `evidence_sha256`: hash of an independently stored, bounded reproduction evidence file (filename is exactly its lowercase SHA-256).

The signed metadata and bytes are never treated as instructions and are never executed. A trust registry controlled by the study operator supplies public keys; private keys must stay outside the dataset. Human disagreement triggers explicit escalation, **not a majority vote, arbitrary overwrite or claimed model score**.

## 3. Verify source and labels before looking at model predictions

```bash
daddy-reviews opportunity-audit \
  --root ./reviewed-repository \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_40_CHAR_SHA \
  --head HEAD_FULL_40_CHAR_SHA \
  --real-sample-seed "precommitted-study-seed-2026-11" \
  --real-sample-max-cases 48 \
  --real-blind-file ./study-private/blind.json \
  --real-private-file ./study-private/private-ledger.json \
  --real-model-report ./completed-investigation.json \
  --label-attestations-file ./study-private/signed-labels.json \
  --label-trust-keys-file ./study-private/ground-truth-public-keys.json \
  --label-evidence-dir ./study-private/reproduction-evidence
```

Omit `--real-model-report` here if it was absent during sampling. In that case the audit can validate human labels, but no model score is reported. The audit re-derives the entire source frame from pinned Git objects and confirms both input packets match that precise frame. Signatures and exact evidence bytes are validated per case. It refuses unsigned, missing, duplicate, stale, mismatched, tampered or disputed records.

If a completed matching model report exists, `scope_separated_sample_observations_only` reports **descriptive, unweighted, biased** precision/recall among selected **added-line anchors only**, plus separately counted context defects on untouched or unchanged lines. These context discoveries are **not** model false negatives. No sample result is promoted to population accuracy, reviewer approval, GitHub publication or automatic merge authorization.

## 4. Real GitHub Actions integration

[Real Repository Opportunity Frame](../.github/workflows/real-opportunity-frame.yml) uses actual tracked Git objects from this repository and runs source-only unit/integration tests. It verifies that the blind packet includes changed additions, unchanged lines in touched files and lines in untouched files, and that the model-ledger content is absent from the blind packet.

It uploads only `blind.json` and a safe summary as the seven-day `daddy-blind-opportunity-frame` artifact. **It does not upload `private.json`**, sign real human labels, run a model, publish GitHub reviews or make model-quality claims. Since the blind artifact contains small excerpts of real source, keep it restricted to code you are authorized to disclose.

The Python 3.10/3.12/3.13 CI suite exercises real Git commit fixtures and generated test-only Ed25519 signers. A green test proves only the software contracts and safeguards, not independent external research.

## Remaining experimental work

Organize a study with independent participants and a **precommitted** repository/commit sampling plan. Consider unit- and behavior-based defect opportunities rather than only line anchors, measure annotator agreement and inconclusive outcomes, control issue duplication and confounders, compare against a stable held-out baseline, and preserve externally authenticated ownership/source provenance. Only after genuine labeled cases and adequate statistical power should this evolve into an empirical reviewer-quality claim. The current system intentionally leaves `population_accuracy_claim=false`, `promotion_eligible=false`, and PR/merge actions disabled.
