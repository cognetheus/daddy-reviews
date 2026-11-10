"""R8.04i.01: Git-blob-backed, four-stratum review opportunity sampling.

New, versioned format: keeps R8.04h's changed-line contracts stable. Sample
units are NONBLANK source *line anchors* in tracked regular Git blobs, NOT
unique defects or complete execution paths. Context anchors can reveal legacy
defects, but MUST NOT count as misses by a diff-only model.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .diff import parse_diff, DiffError
from .human_attestation import sha256_json
from .real_repository_intake import (
    RealIntakeError, SHA, REPO, EXTENSIONS, MAX_PATCH, MAX_SOURCE,
    _git, _line_map, _source, _normalize_model_report,
    write_real_intake_files,
)
from .semantic_contracts import _safe_path

FORMAT = "daddy-reviews-opportunity-frame-v1"
BLIND = "daddy-reviews-opportunity-blind-packet-v1"
LEDGER = "daddy-reviews-opportunity-private-ledger-v1"
STRATA = ("added_flagged", "added_unflagged", "unchanged_touched", "unchanged_other")
PUBLIC_STRATA = ("added", "unchanged_touched", "unchanged_other")
MAX_FILES = 400
MAX_ELIGIBLE_LINES = 120_000
MAX_TOTAL_BYTES = 24_000_000
MAX_CASES = 160
MAX_TREE_BYTES = 2_000_000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_entries(root: Path, head: str) -> tuple[list[str], dict]:
    tree = _git(root, "ls-tree", "-r", "-z", head, "--", limit=MAX_TREE_BYTES)
    paths = []
    excludes = Counter()
    seen = set()
    for item in tree.split(b"\0"):
        if not item:
            continue
        try:
            prefix, name = item.split(b"\t", 1)
            mode, kind, object_id = prefix.split(b" ")
            path = name.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise RealIntakeError("Invalid tracked Git object frame") from exc
        if path in seen or not _safe_path(path):
            raise RealIntakeError("Ambiguous or unsafe tracked Git path")
        seen.add(path)
        if Path(path).suffix not in EXTENSIONS:
            excludes["other_extensions"] += 1
            continue
        if mode not in (b"100644", b"100755") or kind != b"blob":
            excludes["nonregular_code_entries"] += 1
            continue
        if not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", object_id):
            raise RealIntakeError("Malformed Git blob identity")
        paths.append(path)
    if not paths or len(paths) > MAX_FILES:
        raise RealIntakeError("No tracked code or bounded file limit exceeded")
    return sorted(paths), dict(excludes)


def _ranking(seed: str, item: dict) -> str:
    return _sha((
        seed + "\0" + item["path"] + "\0" +
        str(item["line"]) + "\0" + item["source_sha256"]
    ).encode("utf-8"))


def build_opportunity_frame(root: Path, *, repository: str, repository_id: int,
                            base_commit: str, head_commit: str, seed: str,
                            max_cases: int = 48, report: dict | None = None) -> dict:
    """Read immutable tracked source, sample added AND unchanged lines.

    Stratify to avoid model-nominated-only selection. No code is executed.
    Caller pins GitHub numeric repository ID independently; local Git objects
    are reproducible content, not externally authenticated repository origin.
    """
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or type(repository_id) is not int or repository_id < 1
            or not isinstance(base_commit, str) or not SHA.fullmatch(base_commit)
            or not isinstance(head_commit, str) or not SHA.fullmatch(head_commit)
            or base_commit == head_commit
            or not isinstance(seed, str) or not 8 <= len(seed) <= 128
            or type(max_cases) is not int or not 1 <= max_cases <= MAX_CASES):
        raise RealIntakeError("Exact Git commits, positive repository ID and bounded seed required")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise RealIntakeError("Expected real Git working checkout")
    actual = _git(root, "rev-parse", "--verify", "HEAD", limit=100).decode().strip()
    if actual != head_commit:
        raise RealIntakeError("HEAD does not match pinned immutable source commit")
    # Use normal Git argument-vector invocation, never a shell or git hooks.
    ancestor = _git(root, "merge-base", base_commit, head_commit, limit=100).decode().strip()
    if ancestor != base_commit:
        raise RealIntakeError("Base commit is not an ancestor of head")
    patch_raw = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--unified=0",
                     base_commit, head_commit, "--", limit=MAX_PATCH)
    try:
        patch = patch_raw.decode("utf-8")
        changes = parse_diff(patch)
    except (UnicodeError, DiffError) as exc:
        raise RealIntakeError("Invalid real-source diff") from exc
    if not changes:
        raise RealIntakeError("Source change required for frame")
    changed_paths = {c.new_path for c in changes if c.added_lines and c.new_path
                     and Path(c.new_path).suffix in EXTENSIONS}
    changed_additions = {(c.new_path, number) for c in changes
                         if c.new_path in changed_paths for number in c.added_lines}
    if not changed_additions or len(changed_additions) > MAX_ELIGIBLE_LINES:
        raise RealIntakeError("No bounded changed source additions")
    line_map = _line_map(patch)
    paths, excluded = _tree_entries(root, head_commit)
    if not changed_paths <= set(paths):
        raise RealIntakeError("Changed source not in immutable regular Git tree")
    patch_hash = _sha(patch_raw)
    predictions, report_mode = _normalize_model_report(
        report, patch_sha=patch_hash, additions=changed_additions)
    # A source file may contain many meaningful lines; sampling is bounded and
    # deterministic, but labels are line opportunities rather than whole bugs.
    records = []
    total_bytes = 0
    public_counts = Counter()
    private_counts = Counter()
    for path in paths:
        raw, lines = _source(root, head_commit, path)
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_BYTES:
            raise RealIntakeError("Source tree exceeds bounded sampling bytes")
        digest = _sha(raw)
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            if len(records) >= MAX_ELIGIBLE_LINES:
                raise RealIntakeError("Source line population exceeds bounded frame")
            key = (path, number)
            added = key in changed_additions
            if added and line != line_map.get(key):
                raise RealIntakeError("Added source does not match Git diff")
            public_stratum = ("added" if added else
                              "unchanged_touched" if path in changed_paths else
                              "unchanged_other")
            stratum = ("added_flagged" if key in predictions else
                       "added_unflagged" if added else public_stratum)
            record = {
                "path": path, "line": number, "stratum": stratum,
                "public_stratum": public_stratum, "source_sha256": digest,
                "line_sha256": _sha(line.encode("utf-8")),
                "source_line_untrusted": line[:200],
            }
            records.append(record)
            private_counts[stratum] += 1
            public_counts[public_stratum] += 1
    if not records:
        raise RealIntakeError("No nonblank tracked source opportunities")
    # Ensure all NONBLANK added locations are represented. Blank added lines
    # are explicitly excluded by this study's sampling frame.
    nonblank_changed = {(r["path"], r["line"]) for r in records
                        if r["public_stratum"] == "added"}
    if nonblank_changed != {key for key, value in line_map.items()
                            if key in changed_additions and value.strip()}:
        raise RealIntakeError("Incomplete source frame or changed-line mismatch")
    by_stratum = {s: [] for s in STRATA}
    for r in records:
        by_stratum[r["stratum"]].append(r)
    for bucket in by_stratum.values():
        bucket.sort(key=lambda item: _ranking(seed, item))
    # Round-robin quotas guarantee cross-stratum coverage when budget allows;
    # draws within each stratum use deterministic SHA-256 ranks. Biased by
    # design; no population recall/precision estimate is implied.
    selected = []
    offsets = dict.fromkeys(STRATA, 0)
    while len(selected) < max_cases:
        progress = False
        for name in STRATA:
            offset = offsets[name]
            if offset < len(by_stratum[name]) and len(selected) < max_cases:
                selected.append(by_stratum[name][offset])
                offsets[name] += 1
                progress = True
        if not progress:
            break
    selected.sort(key=lambda r: (r["path"], r["line"]))
    identity = {
        "repository": repository, "repository_id": repository_id,
        "base_commit": base_commit, "head_commit": head_commit,
        "patch_sha256": patch_hash, "seed_sha256": _sha(seed.encode()),
    }
    blind_cases, ledger_cases = [], []
    for item in selected:
        case_id = sha256_json({
            **identity, "path": item["path"], "line": item["line"],
            "source_sha256": item["source_sha256"],
            "public_stratum": item["public_stratum"],
        })[:24]
        blind_cases.append({
            "case_id": case_id, "tier": "lite", "path": item["path"],
            "line": item["line"], "stratum": item["public_stratum"],
            "source_sha256": item["source_sha256"],
            "line_sha256": item["line_sha256"],
            "source_line_untrusted": item["source_line_untrusted"],
            "label": None, "blind_to_model_output": True,
            "review_instructions": "Evaluate independently with relevant context; "
                                   "document reproduction and negative cases.",
        })
        key = (item["path"], item["line"])
        flagged = bool(predictions.get(key)) if item["public_stratum"] == "added" else None
        ledger_cases.append({
            "case_id": case_id, "path": item["path"], "line": item["line"],
            "stratum": item["stratum"],
            "within_diff_model_scope": item["public_stratum"] == "added",
            "model_flagged": flagged if report is not None else None,
            "model_rules": predictions.get(key, []) if report is not None else [],
        })
    public_population = {
        "eligible_nonblank_lines": len(records),
        "eligible_by_source_stratum": {
            name: public_counts[name] for name in PUBLIC_STRATA},
        "eligible_code_files": len(paths),
        "excluded_tracked_entries": excluded,
        "sampled_nonblank_lines": len(selected),
    }
    private_population = {
        **public_population,
        "eligible_by_model_stratum": {name: private_counts[name] for name in STRATA},
        "sampled_by_model_stratum": {
            name: sum(r["stratum"] == name for r in selected)
            for name in STRATA},
    }
    blind = {
        "format": BLIND, **identity, "source": "immutable_tracked_git_blobs",
        "sampling_unit": "nonblank_source_line_anchor_not_unique_defect",
        "population": public_population,
        "blinding": "distribute_only_blind_packet",
        "model_predictions_included": False,
        "cases": blind_cases, "status": "independent_human_labels_pending",
        "merge_action": "none", "github_publication": "none",
    }
    private = {
        "format": LEDGER, **identity, "blind_packet_sha256": sha256_json(blind),
        "model_report_sha256": sha256_json(report) if report is not None else None,
        "prediction_mode": report_mode, "population": private_population,
        "cases": ledger_cases, "promotion_eligible": False,
        "merge_action": "none", "github_publication": "none",
    }
    return {
        "format": FORMAT, "status": "real_source_opportunity_frame_not_labels",
        "blind_packet": blind, "private_ledger": private,
        "frame_sha256": sha256_json({"blind": blind, "private": private}),
        "sampling_design": "deterministic_model_stratified_nonprobability_line_sample",
        "defect_truth_claim": False, "population_accuracy_claim": False,
        "promotion_eligible": False, "merge_action": "none",
        "github_publication": "none",
    }


def write_opportunity_frame_files(frame: dict, blind_path: Path, ledger_path: Path) -> dict:
    """Reuse R8.04h's exclusive, owner-only output contract."""
    if (not isinstance(frame, dict) or frame.get("format") != FORMAT
            or frame.get("status") != "real_source_opportunity_frame_not_labels"):
        raise RealIntakeError("Invalid opportunity frame for export")
    wrapper = {
        "format": "daddy-reviews-real-repository-intake-v1",
        "status": "real_source_intake_not_ground_truth",
        "blind_packet": frame["blind_packet"],
        "private_ledger": frame["private_ledger"],
    }
    receipt = write_real_intake_files(wrapper, blind_path, ledger_path)
    return {
        **receipt, "format": FORMAT, "status": "opportunity_blind_packet_created",
        "sampling_design": frame["sampling_design"],
        "population": frame["private_ledger"]["population"],
        "defect_truth_claim": False, "population_accuracy_claim": False,
    }
