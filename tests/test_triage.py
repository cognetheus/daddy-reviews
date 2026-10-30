"""Regression cases for adaptive, non-blocking review scope."""
from pathlib import Path
from tempfile import TemporaryDirectory
from daddy_reviews.diff import parse_diff
from daddy_reviews.triage import assess_review_tier

def patch(path: str, additions: int = 1) -> str:
    lines = "".join(f"+line_{i}\n" for i in range(additions))
    return (f"diff --git a/{path} b/{path}\n"
            f"new file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{additions} @@\n{lines}")

def test_small_docs_change_is_trivial():
    with TemporaryDirectory() as d:
        report = assess_review_tier(Path(d), parse_diff(patch("docs/README.md")))
    assert report["tier"] == "trivial"
    assert report["changed_lines"] == 1
    assert report["recommended_reviewers"] == ("code-quality",)

def test_auth_change_escalates_even_one_line():
    with TemporaryDirectory() as d:
        report = assess_review_tier(Path(d), parse_diff(patch("src/auth/login.py")))
    assert report["tier"] == "full"
    assert any("security-sensitive" in reason for reason in report["reasons"])

def test_lookalike_word_does_not_trigger_auth():
    with TemporaryDirectory() as d:
        report = assess_review_tier(Path(d), parse_diff(patch("src/author_profiles.py")))
    assert report["tier"] == "trivial"

def test_migration_beats_generated_marker():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "migrations").mkdir()
        (root / "migrations" / "001.sql").write_text("-- @generated\nALTER TABLE users ADD COLUMN age int;\n")
        report = assess_review_tier(root, parse_diff(patch("migrations/001.sql")))
    assert report["tier"] == "full"
    assert "migrations/001.sql" in report["review_required_files"]
    assert not report["context_only_files"]

def test_lockfile_context_only_but_never_disappears():
    with TemporaryDirectory() as d:
        report = assess_review_tier(Path(d), parse_diff(patch("package-lock.json")))
    assert report["context_only_files"] == ("package-lock.json",)
    assert any("remains in evidence" in warning for warning in report["warnings"])

def test_generated_header_context_only_and_symlink_abstains():
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "gen.py").write_text("# @generated\nvalue = 1\n")
        generated = assess_review_tier(root, parse_diff(patch("gen.py")))
        assert generated["context_only_files"] == ("gen.py",)
        outside = root / "other.py"
        outside.write_text("# @generated\n")
        (root / "link.py").symlink_to(outside)
        linked = assess_review_tier(root, parse_diff(patch("link.py")))
        assert "link.py" in linked["review_required_files"]

def test_large_diff_routes_full_and_empty_abstains():
    with TemporaryDirectory() as d:
        large = assess_review_tier(Path(d), parse_diff(patch("src/useful.py", 101)))
        empty = assess_review_tier(Path(d), parse_diff(""))
    assert large["tier"] == "full"
    assert empty["tier"] == "lite"
    assert any("No parsed file" in warning for warning in empty["warnings"])

def test_binary_marked_for_independent_review():
    binary = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
    with TemporaryDirectory() as d:
        report = assess_review_tier(Path(d), parse_diff(binary))
    assert any("binary change" in warning for warning in report["warnings"])
