"""Opt-in incremental PR re-review planning with explicit state persistence.

The input is the *complete current PR diff* against the intended base, not
merely the last commit diff. No GitHub writes and no hidden local state writes.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .diff import parse_diff
from .triage import assess_review_tier, REVIEWERS

MAX_STATE = 300_000
SHA = re.compile(r"^[a-f0-9]{40}$")
VERSION = "daddy-reviews-rerun-v1"


class RerunError(ValueError):
    pass


def _split(patch: str) -> dict[str, str]:
    """Extract each complete file patch to avoid false cache hits on line counts."""
    chunks = []
    current = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                chunks.append("".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append("".join(current))
    parsed = parse_diff(patch)
    if len(chunks) != len(parsed):
        raise RerunError("Cannot align file patches with parsed diff")
    return {f.new_path or f.old_path: hashlib.sha256(c.encode()).hexdigest()
            for f, c in zip(parsed, chunks)}


def _state(head: str, patch: str) -> dict:
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise RerunError("Expected a full lowercase Git commit SHA")
    if not isinstance(patch, str) or len(patch.encode()) > 8_000_000:
        raise RerunError("Invalid or oversized PR patch")
    files = _split(patch)
    if len(files) > 3000:
        raise RerunError("More than 3000 changed files not supported")
    return {"format": VERSION, "head_sha": head,
            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(), "files": files}


def read_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE:
        raise RerunError("State is symlinked, invalid or oversized")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RerunError("Cannot parse previous rerun state") from exc
    if not isinstance(data, dict) or data.get("format") != VERSION:
        raise RerunError("Unrecognized rerun state")
    files = data.get("files")
    if (not isinstance(files, dict) or len(files) > 3000 or
            not all(isinstance(k, str) and isinstance(v, str) and
                    re.fullmatch(r"[a-f0-9]{64}", v) for k, v in files.items()) or
            not isinstance(data.get("head_sha"), str) or
            not SHA.fullmatch(data["head_sha"]) or
            not isinstance(data.get("patch_sha256"), str) or
            not re.fullmatch(r"[a-f0-9]{64}", data["patch_sha256"])):
        raise RerunError("Malformed rerun state")
    return data


def plan_rerun(root: Path, patch: str, head: str, previous: dict | None = None) -> dict:
    latest = _state(head, patch)
    if previous is not None:
        # Enforce the same validation on injected in-memory states.
        if (previous.get("format") != VERSION or
                not isinstance(previous.get("files"), dict)):
            raise RerunError("Invalid previous state")
    old = previous["files"] if previous else {}
    current = latest["files"]
    changed = sorted(path for path, digest in current.items() if old.get(path) != digest)
    removed = sorted(path for path in old if path not in current)
    unchanged = sorted(path for path, digest in current.items() if old.get(path) == digest)
    if previous is None:
        action = "initial_review"
    elif changed or removed:
        action = "review_changed"
    elif previous["patch_sha256"] != latest["patch_sha256"]:
        # Ordering/meta changes: conservatively review.
        action = "review_changed"
    elif previous["head_sha"] != head:
        # Same complete diff on a different commit: no need to claim a fresh
        # review; any linked verification/publication must still be rechecked.
        action = "revalidate_head"
    else:
        action = "no_change"
    # A removed file patch can alter current overall PR scope or dependencies.
    # Conservatively route the complete current patch rather than silently
    # trusting cached context from a vanished file.
    all_changes = parse_diff(patch)
    selected = (all_changes if removed else
                [c for c in all_changes if (c.new_path or c.old_path) in changed])
    tier = assess_review_tier(root, selected)
    if removed:
        tier["tier"] = "full"
        tier["recommended_reviewers"] = REVIEWERS["full"]
        tier["reasons"] = (*tier["reasons"], "Previous PR diff files disappeared; revalidate full current patch")
    return {
        "format": VERSION, "action": action,
        "previous_head_sha": previous["head_sha"] if previous else None,
        "head_sha": head, "head_changed": previous is not None and previous["head_sha"] != head,
        "changed_files": changed, "removed_files": removed, "reused_file_evidence": unchanged,
        "selected_reviewers": list(tier["recommended_reviewers"])
        if action in ("initial_review", "review_changed") else [],
        "reanalysis_scope": "entire_current_patch" if removed else
                            "changed_patch_files" if changed else "none",
        "risk_tier": tier["tier"] if action in ("initial_review", "review_changed") else None,
        "state": latest, "wrote_state": False,
        "limitations": [
            "Incremental plan only; existing review evidence is not automatically verified as fresh.",
            "File fingerprints derive from the full input patch, not compiler or runtime semantics.",
            "A changed shared dependency can require a broader review than filename selection.",
            "No hosted reviewer, PR comment, or cache write occurs without separate opt-in.",
        ],
    }


def save_state(path: Path, state: dict) -> None:
    """Atomic user-requested state write. Reject symlink paths."""
    if path.is_symlink() or path.parent.is_symlink():
        raise RerunError("Refusing symlink state path")
    if path.exists() and not path.is_file():
        raise RerunError("State target must be a file")
    if not path.parent.is_dir():
        raise RerunError("State directory does not exist")
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"))
    if len(raw.encode()) > MAX_STATE:
        raise RerunError("State exceeds storage budget")
    fd, temporary = tempfile.mkstemp(prefix=".daddy-rerun-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
