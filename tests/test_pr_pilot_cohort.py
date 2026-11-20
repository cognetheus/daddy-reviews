"""R8.06b: read-only PR observation aggregation is never accuracy approval."""
import copy
import pytest

from daddy_reviews.pr_pilot import FORMAT
from daddy_reviews.pr_pilot_cohort import observe_pilot_cohort, PilotCohortError


def sample(pr=1, latency=1200, findings=2):
    return {
        "format":FORMAT,"status":"advisory_source_read_verified",
        "repository":"cognetheus/daddy-reviews",
        "repository_numeric_id":1431087545,
        "pr_number":pr,"head_commit":"a"*40,
        "base_commit":"b"*40,"patch_sha256":"c"*64,
        "changed_file_count":1,"added_lines":2,"deleted_lines":1,
        "candidate_findings":findings,"review_elapsed_ms":latency,
        "verified_defects":0,"coverage":"bounded_complete_textual_patch",
        "github_read_only":True,"model_used":False,
        "human_findings_verified":False,"human_review_required":True,
        "pr_comments_posted":0,"merge_action":"none",
        "production_approval_granted":False,"source_text_in_summary":False,
        "retrieval_method":"authenticated_github_get_and_exact_local_commit",
    }


def test_5_distinct_observed_prs_are_local_candidate_not_real_release():
    result=observe_pilot_cohort([sample(i) for i in range(1,6)])
    assert result["status"]=="local_pilot_candidate"
    assert result["distinct_pr_observations"]==5
    assert result["candidate_finding_count"]==10
    assert result["review_p95_ms"]==1200
    assert result["candidate_stop_triggers"]==[]
    assert result["source"]=="untrusted_operator_supplied_safe_summaries"
    assert result["server_api_records_independently_rechecked"] is False
    assert result["false_positive_rate"] is None
    assert result["missed_defect_rate"] is None
    assert result["production_approval_granted"] is False
    assert result["release_authorized"] is False
    assert result["github_comments_posted"]==0 and result["merge_action"]=="none"


def test_workflow_summaries_with_owner_only_private_digest_are_cohort_compatible():
    events=[sample(i) for i in range(1,6)]
    for event in events:
        event.update({
            "private_evidence_saved":True,
            "private_evidence_sha256":"e"*64,
            "private_evidence_not_published":True,
        })
    cohort=observe_pilot_cohort(events)
    assert cohort["status"]=="local_pilot_candidate"
    assert cohort["distinct_pr_observations"]==5
    assert "private_evidence_sha256" not in str(cohort)


@pytest.mark.parametrize("mutate",[
    lambda d: d.update(private_evidence_sha256="bad"),
    lambda d: d.update(private_evidence_saved=False),
    lambda d: d.update(private_evidence_not_published=False),
    lambda d: d.pop("private_evidence_sha256"),
])
def test_malformed_or_partial_private_receipt_never_passes_cohort(mutate):
    record=sample()
    record.update({
        "private_evidence_saved":True,
        "private_evidence_sha256":"d"*64,
        "private_evidence_not_published":True,
    })
    mutate(record)
    with pytest.raises(PilotCohortError):
        observe_pilot_cohort([record])


def test_no_open_PR_evidence_is_blocked_without_synthetic_metrics():
    result=observe_pilot_cohort([])
    assert result["status"]=="pilot_stop_or_insufficient_evidence"
    assert "insufficient_distinct_real_pr_observations" in result["candidate_stop_triggers"]
    assert result["review_p95_ms"] is None
    assert not result["production_approval_granted"]


def test_high_latency_and_excess_findings_trigger_manual_halt():
    items=[sample(i,latency=100_000 if i==5 else 1000,
                  findings=25 if i==5 else 2) for i in range(1,6)]
    result=observe_pilot_cohort(items)
    assert result["status"]=="pilot_stop_or_insufficient_evidence"
    assert "pr_review_latency_candidate_budget_exceeded" in result["candidate_stop_triggers"]
    assert "untriaged_findings_per_pr_budget_exceeded" in result["candidate_stop_triggers"]
    assert result["operator_action"]=="halt_or_keep_shadow_only"
    assert not result["production_approval_granted"]


def test_multiple_snapshots_of_same_pr_do_not_inflate_cohort():
    first,second=sample(1),sample(1)
    second["head_commit"]="d"*40
    with pytest.raises(PilotCohortError,match="Duplicate"):
        observe_pilot_cohort([first,second])


@pytest.mark.parametrize("mutate",[
    lambda x: x.update(secret="cloud-key=leaked"),
    lambda x: x.update(pr_comments_posted=1),
    lambda x: x.update(production_approval_granted=True),
    lambda x: x.update(human_findings_verified=True),
    lambda x: x.update(model_used=True),
    lambda x: x.update(verified_defects=1),
    lambda x: x.update(status="model-approved"),
    lambda x: x.update(review_elapsed_ms=-1),
    lambda x: x.update(pr_number=True),
    lambda x: x.update(head_commit="bad"),
    lambda x: x.update(merge_action="merge"),
])
def test_malformed_promotional_or_source_leaking_summary_rejected(mutate):
    value=sample()
    mutate(value)
    with pytest.raises(PilotCohortError):
        observe_pilot_cohort([value])


def test_bad_cohort_budget_rejected():
    for params in ({"minimum_prs":True},{"minimum_prs":51},
                   {"max_candidates_per_pr":501},{"p95_budget_ms":0}):
        with pytest.raises(PilotCohortError):
            observe_pilot_cohort([],**params)
