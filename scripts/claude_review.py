"""Read-only Claude Code adapter for Daddy Reviews; never runs project code or writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))
from daddy_reviews.diff import DiffError, MAX_PATCH_BYTES
from daddy_reviews.review import review_patch


class ReviewAbstention(Exception):
    """A source or coverage contract failed closed."""


def _git(root: Path, *args: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            encoding="utf-8", errors="strict", timeout=30, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ReviewAbstention(f"Git unavailable or invalid ({type(exc).__name__})") from exc
    if cp.returncode:
        raise ReviewAbstention(f"Git inspection failed: {cp.stderr.strip()[:240]}")
    if len(cp.stdout.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ReviewAbstention("Git inspection exceeded bounded output budget")
    return cp.stdout


def _commit(root: Path, ref: str) -> str:
    if not ref or ref.startswith("-") or "\x00" in ref or "\n" in ref:
        raise ReviewAbstention("Invalid revision")
    sha = _git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ReviewAbstention("Revision is not a full SHA-1 commit")
    return sha


def _patch(root: Path, *refs: str) -> str:
    return _git(root, "-c", "core.quotePath=false", "diff", "--no-ext-diff",
                "--no-textconv", "--no-color", "--find-renames", "--unified=0",
                *refs, "--")


def run(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description="Read-only Daddy Reviews for Claude Code")
    p.add_argument("--root", default=".", help="Path inside target Git worktree")
    p.add_argument("--scope", choices=("working", "branch"), default="working")
    p.add_argument("--base", help="Required explicit base revision for branch scope")
    p.add_argument("--task", default="Review changed code")
    args = p.parse_args(argv)
    if args.scope == "branch" and not args.base:
        raise ReviewAbstention("Branch review requires explicit --base")
    if args.scope == "working" and args.base:
        raise ReviewAbstention("--base only applies to branch scope")
    requested = Path(args.root).resolve()
    root = Path(_git(requested, "rev-parse", "--show-toplevel").strip()).resolve()
    head = _commit(root, "HEAD")
    if args.scope == "branch":
        if _git(root, "status", "--porcelain=v1", "--untracked-files=normal"):
            raise ReviewAbstention("Branch checkout is dirty; use working scope or a clean checkout")
        base = _commit(root, args.base)
        patch = _patch(root, f"{base}...{head}")
        selection = {"scope": "branch", "base_sha": base, "head_sha": head}
    else:
        patch = _patch(root, head)
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").count("\x00")
        selection = {"scope": "working", "head_sha": head,
                     "untracked_files_excluded": untracked}
    if not patch:
        return {"status": "no_tracked_diff", "selection": selection,
                "notice": "No tracked patch analyzed; this is not a clean-code verdict."}
    evidence = review_patch(root, patch, args.task)
    if _commit(root, "HEAD") != head:
        raise ReviewAbstention("HEAD changed during analysis")
    if args.scope == "branch":
        if _git(root, "status", "--porcelain=v1", "--untracked-files=normal"):
            raise ReviewAbstention("Checkout changed during branch review")
        if _patch(root, f"{base}...{head}") != patch:
            raise ReviewAbstention("Branch diff changed during analysis")
    elif _patch(root, head) != patch:
        raise ReviewAbstention("Working diff changed during analysis")
    return {"status": "evidence_generated", "selection": selection,
            "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            "advisory_only": True,
            "notice": "All candidates unverified; no project tests, model calls, approvals, or publishing ran.",
            "review": evidence}


def main() -> int:
    try:
        result = run()
    except (ReviewAbstention, DiffError, OSError, ValueError) as exc:
        print(json.dumps({"status": "abstained", "reason": str(exc)[:300], "advisory_only": True}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "evidence_generated" else 2


if __name__ == "__main__":
    raise SystemExit(main())
