# R8.04h — Real-repository sampling and blinded human case audit

R8.04h advances beyond synthetic replay by sampling source lines from **real, pinned Git commits**. It creates two intentionally segregated artifacts:

1. **Blind packet** (`daddy-reviews-blind-review-packet-v1`) for independent human investigators: Git source commit identities, changed source location, immutable source/line SHA-256, up to 200 characters of untrusted source line, and **no model flags, rules, verdicts or human labels**.
2. **Private ledger** (`daddy-reviews-sealed-model-predictions-v1`) for the operator, kept hidden until independent adjudication: case IDs, source locations, original model rule IDs/flag status if a completed reviewer report was supplied, and exact selected/eligible populations.

This is a **research-intake and evaluation harness**. Actual Git source does not imply known defects. Neither current CI nor these protocols claim that external independent researchers have discovered and labeled real repository issues.

## 1. Reproducibly sample a genuine repository

Use a locally available clone with full parent and head objects. Base and head must be full immutable commit SHAs, with base an ancestor of head. HEAD must be the requested head SHA.

```bash
git -C PATH/TO/REPO rev-parse HEAD
git -C PATH/TO/REPO rev-parse HEAD^
```

Create a trusted private directory (not accessible to the model or human adjudicators). The operator must supply the repository's real GitHub numeric ID from an independently trusted source; the local collector does not contact GitHub to authenticate that ID.

```bash
mkdir -p /tmp/daddy-intake
chmod 700 /tmp/daddy-intake

daddy-reviews real-sample \
  --root PATH/TO/REPO \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_COMMIT_SHA \
  --head HEAD_FULL_COMMIT_SHA \
  --real-sample-seed "sealed-study-seed-2026-11" \
  --real-sample-max-cases 40 \
  --real-blind-output /tmp/daddy-intake/blind.json \
  --real-private-output /tmp/daddy-intake/model-ledger.json
```

This command is read-only with respect to the Git repository. It reads the exact Git object at HEAD and uses `git diff --no-ext-diff --no-textconv --unified=0 BASE HEAD`; every sampled addition must match the corresponding byte-decoded line of the immutable Git blob. Git symlinks, unsupported extensions, binary content, ambiguous paths, stale/missing objects, overly large files/patches or excessive changed lines are rejected rather than silently reinterpreted.

The output files are owner-only (`0600`), exclusively created without overwriting existing artifacts. If the path or its ancestor is a symlink, or the directory is group/world-writable, the export is refused. The printed JSON summary does **not** include model predictions or raw source text.

### Optional model hypotheses

If you have a completed R8.02 specialist investigation report from **that same diff**, pass:

```bash
--real-model-report PATH/TO/completed-investigation.json
```

The report must have matching `patch_sha256`, completed reviewer status, bounded source-backed model findings and changed-line anchors. An incomplete or stale report fails closed.

Without a report, **every case is unflagged and no model performance can be calculated**. Do not mistake "unflagged" for a model proving code safe when the model was never run.

The sample selection uses a deterministic SHA-256 seeded ranking. When unflagged locations exist, it reserves at least half the requested sample budget for them (subject to available candidates). This allows humans to investigate potential **omissions**, not just the defects the model proposed. Model flags and rule IDs live only in the operator's sealed ledger. The selection is not a statistical random sample certified for unbiased repository-wide recall.

## 2. Blind independent adjudication

Give reviewers **only the blind JSON**. Never give them the private ledger, specialist model outputs, reviewer resolutions or the model's claimed vulnerabilities during blinded assessment.

Ask each separately enrolled ground-truth adjudicator to examine the exact commit and source location, independently reproduce or reject a failure, inspect surrounding relevant context and record negative cases and uncertainty. A sampled line may be benign; the presence of source is not evidence of a bug.

Sign a `daddy-reviews-ground-truth-label-v1` record for every `case_id` with:

- `case_id` and `candidate_id` both set to the blind packet's `case_id`;
- `snapshot_id` set to the full sampled HEAD commit;
- `patch_sha256` and `tier` copied from the blind packet;
- a proposed `label` of `defect` or `clean`, a fixed blind protocol declaration `separate_from_model_and_resolution_v1`, UTC timestamp, signed rationale, and SHA-256 of a separately stored evidence blob;
- `reviewer_id` and `key_id` registered under the distinct `ground_truth_adjudicator` role.

Use `daddy_reviews.ground_truth_labels.label_signing_bytes(record)` as the canonical domain-separated Ed25519 signing payload. Sign privately outside the reviewer model environment. Keep each evidence file under its lowercase 64-character SHA-256 filename. Two independent enrolled identities are required per source location (configurable 2–4). The verifying host gets only the public keys.

A signed label verifies key control and unmodified evidence, **not truth or actual blinding**. Disagreement between two authorized adjudicators results in escalation with no computed quality metrics. The operator must arrange independent reproduction and conflict resolution without leaking the private model ledger.

## 3. Audit labels against the exact immutable sample and measure omissions

Once human review finishes:

```bash
daddy-reviews real-label-audit \
  --root PATH/TO/REPO \
  --attestation-repo OWNER/REPO \
  --attestation-repo-id 123456789 \
  --base BASE_FULL_COMMIT_SHA \
  --head HEAD_FULL_COMMIT_SHA \
  --real-sample-seed "sealed-study-seed-2026-11" \
  --real-sample-max-cases 40 \
  --real-model-report PATH/TO/completed-investigation.json \
  --real-blind-file /tmp/daddy-intake/blind.json \
  --real-private-file /tmp/daddy-intake/model-ledger.json \
  --label-attestations-file /tmp/daddy-intake/signed-human-labels.json \
  --label-trust-keys-file /tmp/daddy-intake/ground-truth-public-keys.json \
  --label-evidence-dir /tmp/daddy-intake/evidence
```

If no model report was supplied to `real-sample`, omit it from `real-label-audit` as well. Labels can still be authenticated, but prediction metrics remain null.

**The audit rebuilds the population and exact selection from Git commit objects** and requires equality of the blind packet and private ledger before inspecting human signatures. It checks every case ID, source SHA, rule mapping, sampling seed, patch digest, and two distinct authorized reviewers with exact evidence bytes. No caller-supplied JSON can redefine the sample population.

With a completed model report and consistent human labels, the output distinguishes:

- `true_positive`: flagged changed-line anchor adjudicated as defective;
- `false_positive`: flagged anchor adjudicated clean;
- `sampled_unflagged_defect`: changed source location **not flagged** by the model but adjudicated defective;
- `sampled_unflagged_clean`: unflagged anchor adjudicated clean.

For the selected sample only, it reports precision among flagged anchors, recall among sampled changed-line anchors and unflagged defect yield. **These are descriptive sample observations, not unbiased repository-wide precision/recall or proof of actual defect truth.** Source line anchors are not necessarily unique bugs. The corpus excludes pre-existing code not changed in the sampled diff. Statistical representativeness, reviewer independence and human correctness must be separately established.

## Security and real-world research limitations

The GitHub-hosted [real intake integration](../.github/workflows/real-corpus-intake.yml) has passed against committed source from this repository. It deliberately has **no model report and no human labels**, and checks only the truthful "actual Git source / no accuracy measured" state. It does not publish code excerpts or the private ledger as downloadable artifacts.

The synthetic adversarial tests create local **real Git repositories**, including commits and tracked symlinks, but their signed labels are generated by fixtures, not by real-world adjudicators. The CI run demonstrates correctness of the mechanism, not empirical model quality.

Remaining graduation work: collect independently selected repositories and commits with blinded human adjudicators, evaluate entire units of defect opportunity beyond changed-line anchors, validate reviewer agreement with counterexamples, publish an auditable sampling frame with documented exclusions, and test held-out model variants. **Automatic PR publishing, reviewer promotion and merge blocking remain unavailable.**
