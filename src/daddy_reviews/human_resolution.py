"""R8.04c: fail-closed human adjudication bound to source and signed receipts.

Two DISTINCT trusted human identities with matching observation logs are required
for an attested resolution. Model refutations remain advisory and disagreements
require signed acknowledgement. This never publishes or blocks any PR.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .agents import AgentRuntimeError
from .human_attestation import (
    FORMAT as ATTESTATION_FORMAT, MAX_RECORDS, HumanVerificationError,
    sha256_json, verify_human_attestation,
)
from .investigative_agents import _changed_added_lines
from .semantic_contracts import capture_worktree, verify_worktree
from .verification_queue import build_verification_queue

FORMAT = "daddy-reviews-human-resolution-v1"
CHALLENGE_FORMAT = "daddy-reviews-independent-challenge-v1"
CHALLENGE_VERDICTS = frozenset({"supported", "refuted", "uncertain"})


def _challenge_map(challenge, snapshot_id, patch_hash, items, manifest):
    if challenge is None:
        return {}
    if (not isinstance(challenge, dict) or challenge.get("format") != CHALLENGE_FORMAT
            or challenge.get("snapshot_id") != snapshot_id
            or challenge.get("patch_sha256") != patch_hash
            or challenge.get("status") not in ("incomplete", "completed_advisory")
            or not isinstance(challenge.get("outcomes"), list)
            or len(challenge["outcomes"]) > 8):
        raise HumanVerificationError("Stale or malformed independent challenge")
    known = {item["id"]: item for item in items}
    files = {f["path"]: f for f in manifest["files"]}
    results = {}
    for outcome in challenge["outcomes"]:
        if not isinstance(outcome, dict):
            raise HumanVerificationError("Malformed challenge outcome")
        cid = outcome.get("candidate_id")
        if not isinstance(cid, str) or cid not in known or cid in results:
            raise HumanVerificationError("Unknown or duplicate challenge candidate")
        if outcome.get("status") not in ("challenged", "escalate_human"):
            raise HumanVerificationError("Unknown challenge outcome status")
        if outcome["status"] == "challenged":
            if (outcome.get("challenge_verdict") not in CHALLENGE_VERDICTS
                    or not isinstance(outcome.get("challenger"), str)
                    or outcome["challenger"] in known[cid]["reviewers"]
                    or not isinstance(outcome.get("citations"), list)
                    or not 1 <= len(outcome["citations"]) <= 80):
                raise HumanVerificationError("Non-independent or unsourced challenge")
            for citation in outcome["citations"]:
                if (not isinstance(citation, dict) or not isinstance(citation.get("source"), dict)):
                    raise HumanVerificationError("Malformed challenge source")
                source = citation["source"]
                entry = files.get(source.get("path"))
                if (not entry or source.get("snapshot_id") != snapshot_id
                        or source.get("source_sha256") != entry["sha256"]
                        or type(source.get("start_line")) is not int
                        or type(source.get("end_line")) is not int
                        or not 1 <= source["start_line"] <= source["end_line"] <= entry["line_count"]):
                    raise HumanVerificationError("Stale challenge source evidence")
        results[cid] = outcome
    if challenge["status"] == "completed_advisory" and (
            len(results) != len([i for i in items if i["status"] == "needs_independent_verification"])
            or any(out["status"] != "challenged" for out in results.values())):
        raise HumanVerificationError("Challenge claims completion without all eligible candidates")
    return results


def adjudicate_human_verification(root: Path, patch: str, report: dict,
                                  attestations: list[dict], trusted_keys: dict,
                                  evidence_blobs: dict, *,
                                  challenge: dict | None = None,
                                  min_reviewers: int = 2) -> dict:
    """Verify signed independent human evidence; only advise human outcomes.

    The host controls the trusted key registry and passes actual observed test
    log bytes. No external file paths or model-supplied commands are executed.
    """
    if (not isinstance(patch, str) or not 0 < len(patch.encode("utf-8")) <= 24_000
            or not isinstance(attestations, list) or len(attestations) > MAX_RECORDS
            or type(min_reviewers) is not int or not 2 <= min_reviewers <= 4
            or not isinstance(evidence_blobs, dict) or len(evidence_blobs) > MAX_RECORDS
            or not isinstance(trusted_keys, dict) or len(trusted_keys) > 64):
        raise HumanVerificationError("Invalid or unbounded adjudication input")
    queue = build_verification_queue(report)
    patch_hash = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if queue["patch_sha256"] != patch_hash:
        raise HumanVerificationError("Human verification patch does not match investigation")
    root = Path(root).resolve()
    manifest = capture_worktree(root)
    if (not manifest["complete"] or not verify_worktree(root, manifest)["verified"]
            or manifest["snapshot_id"] != queue["snapshot_id"]):
        raise HumanVerificationError("Source snapshot is stale or incomplete")
    allowed = _changed_added_lines(patch, root, manifest)
    files = {f["path"]: f for f in manifest["files"]}
    items = {i["id"]: i for i in queue["items"]}
    model_challenges = _challenge_map(challenge, manifest["snapshot_id"],
                                      patch_hash, queue["items"], manifest)

    authenticated = {cid: [] for cid in items}
    seen = set()
    for record in attestations:
        if not isinstance(record, dict) or record.get("format") != ATTESTATION_FORMAT:
            raise HumanVerificationError("Unsigned or unsupported human record")
        cid = record.get("candidate_id")
        if not isinstance(cid, str) or cid not in items:
            raise HumanVerificationError("Human attestation refers to an unknown candidate")
        item = items[cid]
        path = item["path"]
        if (not files.get(path) or item["line"] not in allowed.get(path, set())
                or record.get("source_sha256") != files[path]["sha256"]
                or record.get("snapshot_id") != manifest["snapshot_id"]
                or record.get("patch_sha256") != patch_hash):
            raise HumanVerificationError("Human test source and changed line do not match")
        expected_challenge = (
            sha256_json(model_challenges[cid]) if cid in model_challenges else None
        )
        if record.get("challenge_sha256") != expected_challenge:
            raise HumanVerificationError("Attestation does not bind to current challenge evidence")
        receipt = verify_human_attestation(record, trusted_keys, evidence_blobs)
        unique = (cid, receipt["reviewer_id"])
        if unique in seen:
            raise HumanVerificationError("Multiple attestations from one human on one candidate")
        seen.add(unique)
        authenticated[cid].append(receipt)

    decisions = []
    audit_chain = sha256_json({"format": FORMAT, "snapshot_id": manifest["snapshot_id"],
                              "patch_sha256": patch_hash})
    audit = []
    for item in queue["items"]:
        cid = item["id"]
        receipts = sorted(authenticated[cid],
                          key=lambda x: (x["signed_at"], x["reviewer_id"], x["receipt_sha256"]))
        count_confirm = sum(r["decision"] == "confirm" for r in receipts)
        count_reject = sum(r["decision"] == "reject" for r in receipts)
        outcome = model_challenges.get(cid)
        verdict = outcome.get("challenge_verdict") if outcome else None
        challenge_failed = outcome is not None and outcome["status"] != "challenged"
        opposing = ("refuted" if count_confirm else "supported" if count_reject else None)
        disagreement = opposing is not None and verdict == opposing
        acknowledgement = (not disagreement or
                           all(r["challenge_acknowledged"] for r in receipts
                               if r["decision"] in ("confirm", "reject")))
        if item["status"] != "needs_independent_verification":
            state = "escalate_invalid_source_candidate"
        elif queue["coverage"] != "completed_reviewers_only":
            state = "escalate_incomplete_original_review"
        elif challenge_failed or (challenge is not None and outcome is None):
            state = "escalate_incomplete_independent_challenge"
        elif count_confirm and count_reject:
            state = "conflicting_human_attestations"
        elif disagreement and not acknowledgement:
            state = "model_disagreement_unacknowledged"
        elif count_confirm >= min_reviewers:
            state = "human_attested_confirmed"
        elif count_reject >= min_reviewers:
            state = "human_attested_rejected"
        elif receipts:
            state = "insufficient_independent_human_evidence"
        else:
            state = "awaiting_human_verification"
        for receipt in receipts:
            audit_chain = sha256_json({"previous": audit_chain,
                                       "receipt_sha256": receipt["receipt_sha256"],
                                       "candidate_id": cid})
            audit.append({**receipt, "chain_sha256": audit_chain})
        decisions.append({
            "candidate_id": cid, "path": item["path"], "line": item["line"],
            "rule": item["rule"], "status": state,
            "verified_human_receipts": len(receipts),
            "independent_human_reviewers": sorted(r["reviewer_id"] for r in receipts),
            "human_confirm": count_confirm, "human_reject": count_reject,
            "challenge_verdict": verdict, "model_disagreement": disagreement,
            "disagreement_acknowledged": acknowledgement,
            "publication": "none", "merge_action": "none",
        })
    if not verify_worktree(root, manifest)["verified"]:
        raise HumanVerificationError("Source mutated during human verification")
    terminal = {"human_attested_confirmed", "human_attested_rejected"}
    resolved = sum(d["status"] in terminal for d in decisions)
    return {
        "format": FORMAT, "snapshot_id": manifest["snapshot_id"],
        "patch_sha256": patch_hash,
        "status": ("no_candidates_not_proof_of_clean" if not decisions
                   else "human_attested_resolution" if resolved == len(decisions)
                   else "human_attention_required"),
        "decisions": decisions, "resolved_count": resolved,
        "human_attested_confirmations": sum(
            d["status"] == "human_attested_confirmed" for d in decisions
        ),
        "audit": audit, "audit_chain_sha256": audit_chain,
        "trust": "ed25519_signatures_against_host_supplied_key_registry",
        "log_policy": "sha256_matched_supplied_log_bytes_not_executed",
        "confirmed_findings": 0, "github_publication": "none",
        "merge_action": "none",
        "policy": "Signed human opinions are traceable, not proof of runtime behavior. "
                  "No model or human attestation authorizes automatic PR action.",
    }
