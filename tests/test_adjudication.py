from daddy_reviews.adjudication import adjudicate

def finding(**changes):
    candidate = dict(rule="SEC-1", path="src/auth/login.py", line=12,
                     claim=" Authentication  bypass ", evidence="changed trust check",
                     severity="critical", verification="unverified", changed=True)
    candidate.update(changes)
    return candidate

def test_unverified_critical_is_not_blocked():
    review = adjudicate([finding()])
    assert review["findings"][0]["status"] == "investigate"
    assert review["merge_action"] == "none"

def test_deduplicates_across_reviewers_without_severity_inflation():
    review = adjudicate([
        finding(reviewer="security"),
        finding(claim="authentication bypass", reviewer="code-quality"),
    ])
    assert review["unique_count"] == 1
    assert review["findings"][0]["reviewers"] == ["code-quality", "security"]
    assert review["findings"][0]["duplicate_count"] == 2

def test_disagreement_abstains():
    review = adjudicate([
        finding(verification="confirmed", verification_artifact="test trace"),
        finding(verification="refuted", reviewer="independent-verifier"),
    ])
    assert review["findings"][0]["status"] == "disputed"

def test_reported_confirmation_without_artifact_needs_investigation():
    assert adjudicate([finding(verification="confirmed")])["findings"][0]["status"] == "investigate"

def test_confirmed_severe_requires_human_even_with_artifact():
    review = adjudicate([
        finding(verification="confirmed", verification_artifact="reproduction/test_auth.py")
    ])
    assert review["findings"][0]["status"] == "human_block_review"
    assert review["merge_action"] == "none"

def test_refuted_candidate_dismissed():
    assert adjudicate([finding(verification="refuted")])["findings"][0]["status"] == "dismiss"

def test_changed_line_and_type_are_required():
    assert adjudicate([finding(line=True)])["status"] == "invalid"
    assert adjudicate([finding(severity="not-a-severity")])["status"] == "invalid"

def test_empty_and_excess_findings():
    assert adjudicate([])["summary"] == {}
    assert adjudicate([finding() for _ in range(501)])["status"] == "invalid"
