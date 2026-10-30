"""Cross-phase regression checks for the read-only review packet."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from daddy_reviews.review import review_patch

PATCH = (
    "diff --git a/src/auth/check.py b/src/auth/check.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/src/auth/check.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def authorize(user):\n"
    "+    return user is not None\n"
)

def test_packet_contains_tier_policy_and_adjudication_without_approval():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "src/auth").mkdir(parents=True)
        (root / "src/auth/check.py").write_text(
            "def authorize(user):\n    return user is not None\n")
        policy = root / ".daddy-reviews"
        policy.mkdir()
        (policy / "standards.json").write_text(json.dumps({
            "schema_version": 1,
            "rules": [{
                "id": "SEC_001", "title": "Review authorization",
                "level": "MUST", "state": "enforced",
                "paths": ["src/auth/*"], "source": "SECURITY.md",
                "rationale": "Verify role and tenant isolation",
            }]
        }))
        packet = review_patch(root, PATCH)

    assert packet["review_tier"]["tier"] == "full"
    assert packet["standards"]["status"] == "loaded"
    assert packet["standards"]["applicable_rules"][0]["id"] == "SEC_001"
    assert packet["standards"]["applicable_rules"][0]["verification"] == "not_evaluated"
    assert packet["standards"]["merge_enforcement"] == "disabled"
    assert packet["adjudication"]["merge_action"] == "none"
    assert packet["disposition"] == "no_verified_blockers"
    assert len(packet["files"]) == 1
    assert "src/auth/check.py" in packet["review_tier"]["review_required_files"]

def test_broken_local_policy_abstains_without_fabricating_noncompliance():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / ".daddy-reviews").mkdir()
        (root / ".daddy-reviews/standards.json").write_text("{")
        packet = review_patch(root, "")
    assert packet["standards"]["status"] == "invalid"
    assert not packet["standards"]["applicable_rules"]
    assert packet["review_tier"]["tier"] == "lite"
    assert packet["adjudication"]["summary"] == {}
