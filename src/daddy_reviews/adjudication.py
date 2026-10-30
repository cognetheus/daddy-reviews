"""Conservative cross-reviewer finding consolidation.

This is a *deterministic coordinator stage*, not a model-based judge.
It does not authorize GitHub comments, approvals or merge blocking.
"""
from __future__ import annotations
from collections import Counter
from collections.abc import Iterable, Mapping
import re

MAX_ITEMS = 500
MAX_TEXT = 4000
LEVELS = {"critical", "high", "medium", "low", "suggestion"}
VERIFICATIONS = {"confirmed", "unverified", "refuted"}


def _identity(item: Mapping) -> tuple[str, str, int, str]:
    claim = re.sub(r"\s+", " ", str(item.get("claim", "")).strip().lower())
    return (str(item.get("rule", "")), str(item.get("path", "")),
            item.get("line", -1), claim)


def _valid(item: object) -> bool:
    if not isinstance(item, Mapping):
        return False
    for key in ("rule", "path", "claim", "evidence"):
        if not isinstance(item.get(key), str) or len(item[key]) > MAX_TEXT:
            return False
    line = item.get("line")
    return (type(line) is int and line > 0 and item.get("severity") in LEVELS
            and item.get("verification") in VERIFICATIONS
            and item.get("changed") in (True, False, None))


def adjudicate(findings: Iterable[dict]) -> dict:
    """Deduplicate, expose uncertainty, and produce *advisory* dispositions."""
    # Materialize at most MAX_ITEMS + 1; reject pathological generator input.
    from itertools import islice
    incoming = list(islice(findings, MAX_ITEMS + 1))
    if len(incoming) > MAX_ITEMS:
        return {"status": "invalid", "reason": "finding budget exceeded", "findings": [],
                "merge_action": "none"}
    if any(not _valid(item) for item in incoming):
        return {"status": "invalid", "reason": "invalid finding schema", "findings": [],
                "merge_action": "none"}

    groups = {}
    for f in incoming:
        groups.setdefault(_identity(f), []).append(f)
    results = []
    for _, group in sorted(groups.items(), key=lambda entry: (entry[0][1], entry[0][2], entry[0][0])):
        confirmations = {x["verification"] for x in group}
        head = group[0]
        if "confirmed" in confirmations and "refuted" in confirmations:
            state = "disputed"
            rationale = "Reviewers contradict one another; require independent resolution"
        elif confirmations == {"refuted"}:
            state = "dismiss"
            rationale = "All reviewers refuted the candidate"
        elif confirmations == {"confirmed"}:
            # A declared 'confirmed' label is insufficient without supporting
            # verification artifact. Even then, human review is required.
            proven = any(bool(str(x.get("verification_artifact", "")).strip()) for x in group)
            if proven and head["changed"] is True and head["severity"] in {"critical", "high"}:
                state = "human_block_review"
                rationale = "Documented severe candidate requires human approval before any block"
            elif not proven:
                state = "investigate"
                rationale = "Confirmation assertion lacks an independent verification artifact"
            else:
                state = "advisory"
                rationale = "Confirmed lower-risk or unchanged finding; no automated merge block"
        else:
            state = "investigate"
            rationale = "Unverified finding; not grounds for merge blocking"
        results.append({
            "rule": head["rule"], "path": head["path"], "line": head["line"],
            "claim": head["claim"], "severity": head["severity"],
            "reviewers": sorted(set(x.get("reviewer", "unspecified") for x in group
                                    if isinstance(x.get("reviewer", "unspecified"), str))),
            "duplicate_count": len(group), "status": state, "reason": rationale,
        })
    return {
        "status": "evaluated", "candidate_count": len(incoming),
        "unique_count": len(results),
        "summary": dict(sorted(Counter(r["status"] for r in results).items())),
        "findings": results, "merge_action": "none",
        "limitations": [
            "An independent replay artifact is not itself proof of a real production defect.",
            "No model judge, agent execution, GitHub review publication, or merge blocking occurs.",
            "Repeated assertions are not independent corroboration.",
        ],
    }
