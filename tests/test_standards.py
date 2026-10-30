import json
from pathlib import Path
from tempfile import TemporaryDirectory
from daddy_reviews.standards import evaluate_standards

def rule(**overrides):
    data = {
        "id": "AUTH_001", "title": "Verify trust boundary",
        "level": "MUST", "state": "enforced",
        "paths": ["src/auth/*", "src/identity/*"],
        "source": "docs/SECURITY.md#identity",
        "rationale": "Authentication changes require review and tests.",
    }
    return {**data, **overrides}

def setup(root: Path, rules):
    p = root / ".daddy-reviews"
    p.mkdir()
    (p / "standards.json").write_text(json.dumps({"schema_version": 1, "rules": rules}))

def test_no_catalog_is_nonblocking():
    with TemporaryDirectory() as d:
        out = evaluate_standards(Path(d), ["src/auth/login.py"])
    assert out["status"] == "not_configured"
    assert out["merge_enforcement"] == "disabled"

def test_matching_rule_is_not_a_violation_or_merge_blocker():
    with TemporaryDirectory() as d:
        root = Path(d)
        setup(root, [rule()])
        out = evaluate_standards(root, ["src/auth/login.py", "docs/readme.md"])
    assert out["status"] == "loaded"
    assert out["catalog_size"] == 1
    assert len(out["applicable_rules"]) == 1
    match = out["applicable_rules"][0]
    assert match["matched_paths"] == ["src/auth/login.py"]
    assert match["verification"] == "not_evaluated"
    assert match["disposition"] == "guidance_only"
    assert out["merge_enforcement"] == "disabled"

def test_unrelated_changes_match_no_rules():
    with TemporaryDirectory() as d:
        root = Path(d)
        setup(root, [rule()])
        out = evaluate_standards(root, ["src/features/catalog.py"])
    assert out["applicable_rules"] == []

def test_bad_json_and_duplicate_ids_abstain():
    with TemporaryDirectory() as d:
        root = Path(d)
        setup(root, [])
        (root / ".daddy-reviews" / "standards.json").write_text("{")
        assert evaluate_standards(root, [])["status"] == "invalid"
        (root / ".daddy-reviews" / "standards.json").write_text(
            json.dumps({"schema_version": 1, "rules": [rule(), rule()]}))
        assert evaluate_standards(root, ["src/auth/login.py"])["status"] == "invalid"

def test_reject_unsafe_paths_and_unknown_rule_levels():
    with TemporaryDirectory() as d:
        root = Path(d)
        for candidate in (rule(paths=["../../etc/passwd"]), rule(level="BLOCK")):
            if not (root / ".daddy-reviews").exists():
                setup(root, [candidate])
            else:
                (root / ".daddy-reviews" / "standards.json").write_text(
                    json.dumps({"schema_version": 1, "rules": [candidate]}))
            assert evaluate_standards(root, ["src/auth/login.py"])["status"] == "invalid"

def test_symlink_catalog_not_followed():
    with TemporaryDirectory() as d:
        root = Path(d)
        p = root / ".daddy-reviews"
        p.mkdir()
        external = root / "catalog.json"
        external.write_text(json.dumps({"schema_version": 1, "rules": [rule()]}))
        (p / "standards.json").symlink_to(external)
        assert evaluate_standards(root, ["src/auth/login.py"])["status"] == "invalid"
