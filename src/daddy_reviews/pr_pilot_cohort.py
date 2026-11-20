"""R8.06b — bounded advisory PR pilot cohort monitoring.

Operator-supplied JSON is untrusted; its GitHub-looking identities do not
prove independent GitHub observations or real human defect adjudication.
This module tracks operational candidate signals and explicit stop triggers,
never promotes a model, publishes comments or authorizes a release.
"""
from __future__ import annotations

from math import ceil
import re

from .pr_pilot import FORMAT

COHORT_FORMAT = "daddy-reviews-pr-pilot-cohort-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
MAX_SUMMARIES = 50


class PilotCohortError(ValueError):
    """Invalid, duplicated or misleading operator-supplied pilot summaries."""


def _valid(summary):
    if not isinstance(summary, dict) or set(summary) != {
        "format", "status", "repository", "repository_numeric_id",
        "pr_number", "head_commit", "base_commit", "patch_sha256",
        "changed_file_count", "added_lines", "deleted_lines",
        "candidate_findings", "review_elapsed_ms", "verified_defects",
        "coverage", "github_read_only", "model_used",
        "human_findings_verified", "human_review_required",
        "pr_comments_posted", "merge_action", "production_approval_granted",
        "source_text_in_summary", "retrieval_method",
    }:
        raise PilotCohortError("Pilot observation must have exact source-free schema")
    numbers = ("repository_numeric_id", "pr_number", "changed_file_count",
               "added_lines", "deleted_lines", "candidate_findings",
               "review_elapsed_ms", "verified_defects", "pr_comments_posted")
    if (summary.get("format") != FORMAT
            or summary.get("status") != "advisory_source_read_verified"
            or not isinstance(summary.get("repository"), str)
            or not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+",
                                summary["repository"])
            or any(type(summary.get(key)) is not int for key in numbers)
            or not 0 < summary["repository_numeric_id"]
            or not 0 < summary["pr_number"] <= 1_000_000_000
            or not 1 <= summary["changed_file_count"] <= 40
            or not 0 <= summary["added_lines"] <= 100_000
            or not 0 <= summary["deleted_lines"] <= 100_000
            or not 0 <= summary["candidate_findings"] <= 500
            or not 0 <= summary["review_elapsed_ms"] <= 120_000
            or summary["verified_defects"] != 0
            or summary["pr_comments_posted"] != 0
            or not isinstance(summary.get("head_commit"), str)
            or not SHA.fullmatch(summary["head_commit"])
            or not isinstance(summary.get("base_commit"), str)
            or not SHA.fullmatch(summary["base_commit"])
            or not isinstance(summary.get("patch_sha256"), str)
            or not DIGEST.fullmatch(summary["patch_sha256"])
            or summary.get("coverage") != "bounded_complete_textual_patch"
            or summary.get("github_read_only") is not True
            or summary.get("model_used") is not False
            or summary.get("human_findings_verified") is not False
            or summary.get("human_review_required") is not True
            or summary.get("production_approval_granted") is not False
            or summary.get("source_text_in_summary") is not False
            or summary.get("merge_action") != "none"
            or summary.get("retrieval_method")
               != "authenticated_github_get_and_exact_local_commit"):
        raise PilotCohortError("Pilot summary has unsupported values or promotion claims")
    return summary


def observe_pilot_cohort(summaries: list, *, minimum_prs: int = 5,
                         p95_budget_ms: int = 60_000,
                         max_candidates_per_pr: int = 20) -> dict:
    if (not isinstance(summaries, list) or len(summaries) > MAX_SUMMARIES
            or type(minimum_prs) is not int or not 1 <= minimum_prs <= MAX_SUMMARIES
            or type(p95_budget_ms) is not int or not 1 <= p95_budget_ms <= 120_000
            or type(max_candidates_per_pr) is not int
            or not 0 <= max_candidates_per_pr <= 500):
        raise PilotCohortError("Pilot cohort bounds are invalid")
    checked = [_valid(item) for item in summaries]
    seen = set()
    for item in checked:
        key = (item["repository_numeric_id"], item["pr_number"])
        if key in seen:
            # Different commits of one PR must not inflate independent
            # cohort size. Operator must choose the current one explicitly.
            raise PilotCohortError("Duplicate PR identity or replayed pilot observation")
        seen.add(key)
    latencies = sorted(x["review_elapsed_ms"] for x in checked)
    p95 = latencies[ceil(0.95 * len(latencies)) - 1] if latencies else None
    total = sum(x["candidate_findings"] for x in checked)
    triggers = []
    if len(checked) < minimum_prs:
        triggers.append("insufficient_distinct_real_pr_observations")
    if p95 is not None and p95 > p95_budget_ms:
        triggers.append("pr_review_latency_candidate_budget_exceeded")
    if any(x["candidate_findings"] > max_candidates_per_pr for x in checked):
        triggers.append("untriaged_findings_per_pr_budget_exceeded")
    # A complete set of operator-supplied snapshots does NOT establish
    # independently authenticated live API, human truth or causal quality.
    return {
        "format": COHORT_FORMAT,
        "status": ("local_pilot_candidate" if not triggers
                   else "pilot_stop_or_insufficient_evidence"),
        "source": "untrusted_operator_supplied_safe_summaries",
        "distinct_pr_observations": len(checked),
        "candidate_finding_count": total,
        "review_p95_ms": p95,
        "total_added_lines": sum(x["added_lines"] for x in checked),
        "total_deleted_lines": sum(x["deleted_lines"] for x in checked),
        "candidate_stop_triggers": sorted(triggers),
        "budget": {
            "minimum_distinct_prs": minimum_prs,
            "p95_review_ms": p95_budget_ms,
            "maximum_candidates_per_pr": max_candidates_per_pr,
        },
        "operator_action": "halt_or_keep_shadow_only" if triggers
                           else "continue_human_supervised_shadow_only",
        "server_api_records_independently_rechecked": False,
        "actual_human_label_quality_proven": False,
        "false_positive_rate": None, "missed_defect_rate": None,
        "population_accuracy_claim": False,
        "production_approval_granted": False,
        "human_signoff_required": True,
        "github_comments_posted": 0,
        "merge_action": "none",
        "release_authorized": False,
    }
