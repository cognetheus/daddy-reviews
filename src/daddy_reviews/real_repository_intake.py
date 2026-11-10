"""R8.04h.01 — deterministic, commit-pinned REAL repository case intake.

This samples actual changed source lines from *git objects*, never synthetic
fixtures or model-authored source snippets. It deliberately includes unflagged
locations so false negatives are eligible for independent discovery.

Operator distributes ONLY the blind packet. Model predictions stay in a
separate private ledger. Neither output contains human labels, and no claim of
ground-truth accuracy is made by this collector.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import subprocess

from .diff import DiffError, HUNK, parse_diff
from .human_attestation import sha256_json
from .semantic_contracts import _safe_path

FORMAT = "daddy-reviews-real-repository-intake-v1"
BLIND = "daddy-reviews-blind-review-packet-v1"
LEDGER = "daddy-reviews-sealed-model-predictions-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go"}
MAX_PATCH = 2_000_000
MAX_SOURCE = 350_000
MAX_LINES = 8_000
MAX_SAMPLES = 160
MAX_FILES = 60


class RealIntakeError(ValueError):
    """Unsupported, untrustworthy or unbounded source intake."""


def _git(root: Path, *args: str, limit: int = MAX_PATCH) -> bytes:
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "-c", "core.hooksPath=/dev/null",
             "-c", "core.quotePath=false", *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RealIntakeError("Read-only Git object lookup unavailable") from exc
    if process.returncode != 0 or len(process.stdout) > limit:
        raise RealIntakeError("Git object lookup failed, was unbounded, or ref was missing")
    return process.stdout


def _line_map(patch: str) -> dict:
    """Parse actual added-line text; reject ambiguous headers and unsupported diffs."""
    matches = {}
    current = None
    new_line = 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current, in_hunk = None, False
        elif line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif (hunk := HUNK.match(line)):
            new_line, in_hunk = int(hunk.group(3)), True
        elif in_hunk:
            if line.startswith("+"):
                if current:
                    key = (current, new_line)
                    if key in matches:
                        raise RealIntakeError("Duplicate changed line in diff")
                    matches[key] = line[1:]
                new_line += 1
            elif line.startswith(" "):
                new_line += 1
            elif line.startswith("-") or line.startswith("\\ No newline"):
                continue
            else:
                in_hunk = False
    return matches


def _source(root, head, path):
    if not _safe_path(path) or Path(path).suffix not in EXTENSIONS:
        raise RealIntakeError("Unsafe or unsupported changed source")
    raw = _git(root, "show", f"{head}:{path}", limit=MAX_SOURCE)
    if b"\0" in raw or len(raw) > MAX_SOURCE:
        raise RealIntakeError("Binary or oversized source cannot be sampled")
    try:
        content = raw.decode("utf-8")
    except UnicodeError as exc:
        raise RealIntakeError("Changed source is not UTF-8") from exc
    return raw, content.splitlines()


def _normalize_model_report(report, *, patch_sha, additions):
    if report is None:
        return {}, "no_model_report"
    if (not isinstance(report, dict)
            or report.get("format") != "daddy-reviews-agent-investigation-v1"
            or report.get("status") != "complete"
            or report.get("patch_sha256") != patch_sha
            or not isinstance(report.get("model_findings"), list)
            or len(report["model_findings"]) > 48):
        raise RealIntakeError("Model report incomplete, stale or not from investigation harness")
    from .verification_queue import build_verification_queue
    try:
        build_verification_queue(report)
    except (ValueError, KeyError, TypeError) as exc:
        raise RealIntakeError("Invalid model verification queue") from exc
    predicted = {}
    for finding in report["model_findings"]:
        key = (finding["path"], finding["line"])
        if key not in additions:
            raise RealIntakeError("Model prediction not anchored to actual added line")
        predicted.setdefault(key, set()).add(finding["rule"])
    return {k: sorted(v) for k, v in predicted.items()}, "completed_model_report"


def _rank(seed, record):
    return hashlib.sha256(
        f"{seed}\0{record['path']}\0{record['line']}\0{record['source_sha256']}".encode()
    ).hexdigest()


def build_real_repository_intake(root: Path, *, repository: str,
                                 repository_id: int, base_commit: str,
                                 head_commit: str, seed: str,
                                 max_cases: int = 40,
                                 report: dict | None = None) -> dict:
    """Sample added, tracked code lines from genuine base/head Git object IDs.

    No commit is checked out and no test, model, network or untrusted code runs.
    Git objects bind changed source; repository ID is operator-pinned metadata
    and needs separate GitHub API verification for external authenticity.
    """
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or type(repository_id) is not int or repository_id <= 0
            or not isinstance(base_commit, str) or not SHA.fullmatch(base_commit)
            or not isinstance(head_commit, str) or not SHA.fullmatch(head_commit)
            or base_commit == head_commit
            or not isinstance(seed, str) or not 8 <= len(seed) <= 128
            or type(max_cases) is not int or not 1 <= max_cases <= MAX_SAMPLES):
        raise RealIntakeError("Pinned Git repository, two commits, seed and case count required")
    root = Path(root).resolve()
    if not root.is_dir():
        raise RealIntakeError("Git repository checkout is unavailable")
    actual = _git(root, "rev-parse", "--verify", "HEAD", limit=100).decode().strip()
    if actual != head_commit:
        raise RealIntakeError("Working Git HEAD is not the requested immutable commit")
    try:
        ancestor = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor",
             base_commit, head_commit], capture_output=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RealIntakeError("Cannot verify immutable commit ancestry") from exc
    if ancestor.returncode != 0:
        raise RealIntakeError("Pinned base is not an ancestor of requested head")
    patch_bytes = _git(root, "diff", "--no-ext-diff", "--no-textconv",
                       "--unified=0", base_commit, head_commit, "--",
                       limit=MAX_PATCH)
    try:
        patch = patch_bytes.decode("utf-8")
        changes = parse_diff(patch)
    except (UnicodeError, DiffError) as exc:
        raise RealIntakeError("Changed-source diff is invalid or not text") from exc
    if not changes or len(changes) > MAX_FILES:
        raise RealIntakeError("No bounded diff or too many changed files")
    expected = _line_map(patch)
    records = []
    files = {}
    for change in changes:
        if change.binary or not change.added_lines or not change.new_path:
            continue
        path = change.new_path
        if Path(path).suffix not in EXTENSIONS:
            continue
        if not _safe_path(path) or path in files:
            raise RealIntakeError("Duplicate or unsafe changed path")
        raw, lines = _source(root, head_commit, path)
        digest = hashlib.sha256(raw).hexdigest()
        files[path] = {"sha256": digest, "line_count": len(lines)}
        for line in change.added_lines:
            if len(records) >= MAX_LINES:
                raise RealIntakeError("Source population exceeds bounded sampling budget")
            key = (path, line)
            if (key not in expected or type(line) is not int or line < 1
                    or line > len(lines) or lines[line - 1] != expected[key]):
                raise RealIntakeError("Diff added line does not match immutable head Git object")
            records.append({"path": path, "line": line, "source_sha256": digest,
                            "line_sha256": hashlib.sha256(lines[line-1].encode()).hexdigest(),
                            "line_text": lines[line-1][:200]})
    if not records:
        raise RealIntakeError("No supported, line-grounded source additions")
    if len({(r["path"], r["line"]) for r in records}) != len(records):
        raise RealIntakeError("Duplicate changed source anchors")
    patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    predictions, mode = _normalize_model_report(
        report, patch_sha=patch_sha,
        additions={(r["path"], r["line"]) for r in records})
    flagged = [r for r in records if (r["path"], r["line"]) in predictions]
    unflagged = [r for r in records if (r["path"], r["line"]) not in predictions]
    flagged.sort(key=lambda r: _rank(seed, r))
    unflagged.sort(key=lambda r: _rank(seed, r))
    # Even a very noisy model cannot consume the whole human labeling budget:
    # when possible reserve at least half of sampled locations for unflagged
    # source lines, which may contain defects no model proposed.
    unflagged_quota = min(len(unflagged), (max_cases + 1) // 2)
    selected = unflagged[:unflagged_quota] + flagged[:max_cases-unflagged_quota]
    remaining = [x for x in (unflagged[unflagged_quota:] +
                              flagged[max_cases-unflagged_quota:])
                 if (x["path"], x["line"]) not in {
                     (r["path"], r["line"]) for r in selected}]
    remaining.sort(key=lambda r: _rank(seed, r))
    selected += remaining[:max(0,max_cases-len(selected))]
    selected.sort(key=lambda r: (r["path"], r["line"]))
    identity = {"repository": repository, "repository_id": repository_id,
                "base_commit": base_commit, "head_commit": head_commit,
                "patch_sha256": patch_sha, "seed_sha256": hashlib.sha256(seed.encode()).hexdigest()}
    case_records = []
    ledger = []
    for r in selected:
        cid = sha256_json({**identity, "path": r["path"], "line": r["line"]})[:24]
        case_records.append({
            "case_id": cid, "tier": "lite", "path": r["path"], "line": r["line"],
            "source_sha256": r["source_sha256"],
            "line_sha256": r["line_sha256"], "source_line_untrusted": r["line_text"],
            "label": None, "blind_to_model_output": True,
            "review_instructions": "Independently determine whether a defect exists; "
                                   "include reproduction, negative cases and uncertainty.",
        })
        rules = predictions.get((r["path"], r["line"]), [])
        ledger.append({"case_id": cid, "path": r["path"], "line": r["line"],
                       "model_flagged": bool(rules), "model_rules": rules})
    population = {
        "eligible_added_lines": len(records), "flagged_added_lines": len(flagged),
        "unflagged_added_lines": len(unflagged),
        "sampled_flagged": sum(v["model_flagged"] for v in ledger),
        "sampled_unflagged": sum(not v["model_flagged"] for v in ledger),
        "sampled": len(ledger),
    }
    blind = {"format": BLIND, **identity, "cases": case_records,
             "blinding": "operator_must_distribute_only_blind_packet",
             "status": "awaiting_independent_human_adjudication",
             "source": "actual_git_commit_objects_not_synthetic",
             "model_predictions_included": False,
             "github_publication": "none", "merge_action": "none"}
    private = {"format": LEDGER, **identity,
               "blind_packet_sha256": sha256_json(blind),
               "model_report_sha256": sha256_json(report) if report is not None else None,
               "prediction_mode": mode, "cases": ledger,
               "population": population,
               "score_release_authorized": False,
               "github_publication": "none", "merge_action": "none"}
    return {
        "format": FORMAT, "status": "real_source_intake_not_ground_truth",
        "blind_packet": blind, "private_ledger": private,
        "manifest_sha256": sha256_json({"blind": blind, "private": private}),
        "source_provenance": "pinned_local_git_objects_repository_id_operator_supplied",
        "labels_authenticated": False, "empirical_accuracy_claim": False,
        "promotion_eligible": False, "merge_action": "none",
        "github_publication": "none",
    }

def _output_path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RealIntakeError("Refusing symlinked output path or parent")
    if not path.parent.is_dir():
        raise RealIntakeError("Explicit output directory does not exist")
    if path.parent.stat().st_mode & 0o022:
        raise RealIntakeError("Output directory must not be group/world writable")
    if path.exists():
        raise RealIntakeError("Existing intake artifact cannot be overwritten")
    return path


def write_real_intake_files(intake: dict, blind_path: Path, ledger_path: Path) -> dict:
    """Write segregated blind/private files using exclusive owner-only creation.

    Do not send the private ledger to adjudicators; it contains model predictions.
    Caller chooses a trusted, private output directory. No overwrite or symlinks.
    """
    if (not isinstance(intake, dict)
            or intake.get("format") != FORMAT
            or intake.get("status") != "real_source_intake_not_ground_truth"):
        raise RealIntakeError("Only genuine intake schema may be exported")
    blind = _output_path(blind_path)
    ledger = _output_path(ledger_path)
    if blind == ledger:
        raise RealIntakeError("Blind and private scoring outputs must be separate files")
    created = []
    try:
        for path, obj in ((blind, intake["blind_packet"]),
                          (ledger, intake["private_ledger"])):
            payload = (json.dumps(obj, sort_keys=True, indent=2,
                                  ensure_ascii=False) + "\n").encode("utf-8")
            if len(payload) > 2_000_000:
                raise RealIntakeError("Sample output exceeds 2 MB ceiling")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
    except (OSError, ValueError, KeyError) as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise RealIntakeError("Unable to securely write segregated sample artifacts") from exc
    return {
        "format": FORMAT, "status": "operator_case_packets_created",
        "blind_packet_sha256": sha256_json(intake["blind_packet"]),
        "private_ledger_sha256": sha256_json(intake["private_ledger"]),
        "population": intake["private_ledger"]["population"],
        "model_predictions_disclosed_in_blind_packet": False,
        "human_labels_collected": False, "accuracy_measured": False,
        "promotion_eligible": False,
        "github_publication": "none", "merge_action": "none",
    }
