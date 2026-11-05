"""R8.04a: deterministic, non-authoritative verification and escalation queue.

Source evidence proves provenance, never the claimed defect. This module does
not accept model-produced verification verdicts, execute reviewed code, or
authorize publication/merge blocking.
"""
from __future__ import annotations

import hashlib
import json

FORMAT = "daddy-reviews-verification-queue-v1"
MAX_FINDINGS = 48
MAX_RUNS = 6
MAX_TEXT = 3000
SEVERITIES = {"suggestion", "low", "medium", "high", "critical"}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _safe_text(value: object, limit: int = MAX_TEXT) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def build_verification_queue(report: dict) -> dict:
    """Build bounded human work items from an R8.02 investigation report.

    All evidence IDs are scoped to the originating reviewer. A malformed
    provenance record is escalated as invalid evidence, never upgraded.
    """
    if not isinstance(report, dict) or report.get("format") != "daddy-reviews-agent-investigation-v1":
        raise ValueError("Expected an R8 specialist investigation report")
    snapshot = report.get("snapshot_id")
    patch = report.get("patch_sha256")
    findings = report.get("model_findings")
    runs = report.get("reviewer_runs")
    if (not _safe_text(snapshot, 128) or not isinstance(patch, str)
            or len(patch) != 64 or any(c not in "0123456789abcdef" for c in patch)
            or not isinstance(findings, list) or len(findings) > MAX_FINDINGS
            or not isinstance(runs, list) or len(runs) > MAX_RUNS):
        raise ValueError("Unbounded or malformed investigation report")

    runs_by_name = {}
    for run in runs:
        if (not isinstance(run, dict) or not _safe_text(run.get("reviewer"), 80)
                or run["reviewer"] in runs_by_name
                or run.get("status") not in ("completed", "failed")):
            raise ValueError("Malformed or duplicate reviewer run")
        runs_by_name[run["reviewer"]] = run

    grouped = {}
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Finding must be an object")
        path, line, rule, reviewer = (
            finding.get("path"), finding.get("line"),
            finding.get("rule"), finding.get("reviewer")
        )
        if (not _safe_text(path, 512) or type(line) is not int or line < 1
                or not _safe_text(rule, 120) or reviewer not in runs_by_name
                or not _safe_text(finding.get("claim"))
                or not _safe_text(finding.get("evidence"))
                or finding.get("severity") not in SEVERITIES):
            raise ValueError("Malformed or unbounded finding")
        key = (path, line, rule)
        grouped.setdefault(key, []).append(finding)

    items = []
    for (path, line, rule), members in sorted(grouped.items()):
        reviewers = sorted({item["reviewer"] for item in members})
        provenance_valid = True
        sources = set()
        for finding in members:
            evidence = finding.get("source_evidence")
            cited = finding.get("citations")
            if (finding.get("verification") != "unverified"
                    or finding.get("changed") is not True
                    or not isinstance(evidence, list) or not 1 <= len(evidence) <= 6
                    or not isinstance(cited, list) or len(cited) != len(evidence)):
                provenance_valid = False
                continue
            used = set()
            for record in evidence:
                if not isinstance(record, dict) or set(record) != {"id", "source"}:
                    provenance_valid = False
                    continue
                source = record["source"]
                eid = record["id"]
                if (not _safe_text(eid, 32) or eid not in cited or eid in used
                        or not isinstance(source, dict)
                        or source.get("snapshot_id") != snapshot
                        or source.get("path") != path
                        or type(source.get("start_line")) is not int
                        or type(source.get("end_line")) is not int
                        or not source["start_line"] <= line <= source["end_line"]
                        or not isinstance(source.get("source_sha256"), str)
                        or len(source["source_sha256"]) != 64
                        or any(c not in "0123456789abcdef" for c in source["source_sha256"])):
                    provenance_valid = False
                    continue
                used.add(eid)
                sources.add((path, source["source_sha256"],
                             source["start_line"], source["end_line"]))
            if len(used) != len(cited):
                provenance_valid = False

        severities = sorted({m["severity"] for m in members})
        reason = ("invalid_source_provenance" if not provenance_valid
                  else "conflicting_severity" if len(severities) != 1
                  else "independent_verification_required")
        items.append({
            "id": _digest({"snapshot": snapshot, "patch": patch, "key": [path, line, rule]})[:24],
            "path": path, "line": line, "rule": rule,
            "status": "escalate_human" if reason != "independent_verification_required"
                      else "needs_independent_verification",
            "reason": reason, "reviewers": reviewers, "candidate_count": len(members),
            "severities_claimed": severities,
            "source_spans": [
                {"path": p, "sha256": sha, "start_line": first, "end_line": last}
                for p, sha, first, last in sorted(sources)
            ] if provenance_valid else [],
            "required_checks": [
                "Reproduce the claimed failure in a controlled environment",
                "Check a counterexample or expected behavior",
                "Record a human-reviewed test result and applicable code context",
            ],
            "verification": "unverified", "publication": "none",
        })

    failed = sorted(name for name, run in runs_by_name.items()
                    if run["status"] != "completed")
    overall_incomplete = report.get("status") != "complete" or bool(failed)
    return {
        "format": FORMAT, "snapshot_id": snapshot, "patch_sha256": patch,
        "status": "human_escalation_required" if overall_incomplete
                  or any(i["status"] == "escalate_human" for i in items)
                  else "pending_independent_verification" if items else "no_candidates_not_proof_of_clean",
        "items": items,
        "incomplete_reviewers": failed,
        "coverage": "incomplete" if overall_incomplete else "completed_reviewers_only",
        "confirmed_findings": 0,
        "merge_action": "none", "github_publication": "none",
        "policy": "Model assertions and source citations do not prove a defect; human verification is required.",
    }
