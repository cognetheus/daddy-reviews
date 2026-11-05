# R8.04c — Signed human verification and conflict resolution

R8.04c is an **opt-in, read-only Python developer API**. The original AI reviewer proposes a defect (R8.02), a distinct AI reviewer may challenge it (R8.04b), and *independently trusted human reviewers* can sign their evaluations. The host verifies detached Ed25519 signatures and the exact bytes of the supplied test logs. This produces traceable **human-attested dispositions**, not an automatic claim that code is objectively correct or defective.

## Trust and prerequisites

Install the optional verification dependency:

```bash
python -m pip install -e '.[verification]'
```

The application owner must supply a trust registry **separately from the model and report**:

```json
{
  "qa-alice-2026": {
    "reviewer_id": "alice",
    "role": "human_verifier",
    "enabled": true,
    "public_key_b64": "<base64-encoded Ed25519 raw 32-byte public key>"
  }
}
```

The corresponding **private signing keys must remain outside this repository** (e.g., a user-controlled signing service, hardware key, or secret store). Neither the model nor its tools can register trusted humans. Revocation is performed by changing `enabled` in the host-controlled key registry. The operator must enforce organizational identity proofing when enrolling keys; a valid signature proves control of a key, not that the signer is a human or that the observation is truthful.

## Attestation record contract

Each `daddy-reviews-human-attestation-v1` record includes:

- Source identity: exact `candidate_id`, `snapshot_id`, `patch_sha256`, `source_sha256`.
- Reviewer identity: registered `reviewer_id`, `key_id`, UTC `signed_at` timestamp.
- A `decision` of `confirm`, `reject`, or `inconclusive`, plus a bounded rationale.
- `challenge_sha256`: SHA-256 of the corresponding R8.04b challenge outcome, or JSON `null` if there was no challenge. A signed `challenge_acknowledged` boolean explicitly handles disagreement with the model.
- `test` receipt: `test_id`, recorded `command`, `environment`, `outcome` (`reproduced`, `not_reproduced`, or `inconclusive`) and `log_sha256`.
- `signature_b64`: Ed25519 signature over `b"daddy-reviews-human-attestation-v1\\n"` plus canonical, sorted-key, UTF-8 JSON of every other record field (with no spaces between separators).

`signing_bytes(record)` in `daddy_reviews.human_attestation` creates the exact byte sequence that an authorized human signer must sign. An untrusted model-produced response cannot produce a valid attestation without a registered private key.

## Host-side adjudication API

```python
from pathlib import Path
from daddy_reviews.human_resolution import adjudicate_human_verification

# report: full R8.02 ai-investigate JSON, including verification_queue
# challenge: optional R8.04b independent challenge report, or None
# signed_records: separately collected human signature records
# trusted_public_keys: host-owned identity registry, NOT in model output
# logs: {sha256hex: original_test_log_bytes} (supplied by trusted caller)

resolution = adjudicate_human_verification(
    root=Path("."),
    patch=Path("/tmp/patch.diff").read_text(encoding="utf-8"),
    report=report,
    challenge=challenge,
    attestations=signed_records,
    trusted_keys=trusted_public_keys,
    evidence_blobs=logs,
    min_reviewers=2,
)
assert resolution["github_publication"] == resolution["merge_action"] == "none"
```

The caller supplies **actual log bytes**; the implementation recomputes SHA-256 and refuses missing or mismatched bytes. It does **not** execute the recorded test command, access the artifact URL, trust model-provided logs, or verify that the log was really produced by the described test runner. The log receipt is integrity evidence of what the human signed, not remote CI-run attestation.

## Conflict policy

| Observation | Result |
| --- | --- |
| No human signatures | `awaiting_human_verification` |
| One signature or insufficient independent human decisions | `insufficient_independent_human_evidence` |
| Two distinct authorized signatures, same confirmed reproduction | `human_attested_confirmed` |
| Two distinct authorized signatures, same rejection | `human_attested_rejected` |
| Human signatures disagree | `conflicting_human_attestations` |
| Challenger contradicts humans, not expressly acknowledged | `model_disagreement_unacknowledged` |
| Contradictory model challenge acknowledged by all decisive human signers | Signed human disposition may proceed |
| Failed, absent, or incomplete supplied challenge result | Escalate instead of silently discarding the challenge |
| Original reviewer incomplete or provenance invalid | Escalate despite valid human signatures |

Two distinct *registered human identities* are required (configurable 2–4); multiple keys from one reviewer do not count as independent witnesses. All signature records are tied to the exact source snapshot and changed line. Duplicate signed records for the same candidate and reviewer fail closed. One human cannot overwrite an earlier contrary decision without an explicit external policy.

## Auditing and limits

- Result contains receipt SHA-256 hashes, authenticated reviewer IDs, test IDs, log hashes, challenge references, and a deterministic chained audit hash. Raw test logs and signing keys are **not returned**.
- The chain is **tamper-evident under independent retention** but is not an append-only log or a trusted timestamp service. Signed timestamps are self-declared.
- Limits: 48 records, six-kilobyte canonical signature payloads, 64-KiB test logs per receipt, max 64 trusted key records, and 2–4 required independent humans. Invalid schemas or artifacts raise `HumanVerificationError`.
- The system does not execute a repository test or sign anything automatically. Model challenge verdicts are advisory even when accompanied by valid citations.
- `confirmed_findings` remains zero and both merge and GitHub publication actions remain `none`. The `human_attested_confirmations` field counts signed human dispositions **only**, not autonomously actionable findings.
- No CLI support is included in R8.04c; production enrollment, secure signing, immutable artifact storage and independent CI provenance remain integration work.

## Verification

`tests/test_human_resolution.py` covers genuine in-memory Ed25519 signing, two independent reviewers, absent/single/inconclusive signatures, conflicting human decisions, model disagreement, signed acknowledgement, key revocation, hostile fields, replay against changed challenge or source, and test-log tampering. CI explicitly invokes these regressions on Python 3.10, 3.12, and 3.13.

## Remaining R8.04 work

R8.04d should deliver secure artifact collection / CLI ergonomics, verifiable CI provenance rather than self-declared test output, and evaluation of conflicts and missed defects on independently human-labeled repository cases. Do not claim that human signatures are proof of real model accuracy or merge safety.
