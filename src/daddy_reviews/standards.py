"""Repository-owned engineering standards with explicit applicability and evidence gates.

Rules are metadata for reviewers, *not* executable policy or automatically
proven violations. No user-controlled regex, code execution or network access.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
from typing import Iterable

POLICY_PATH = ".daddy-reviews/standards.json"
MAX_BYTES = 256_000
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
LEVELS = {"MUST", "SHOULD"}
STATES = {"advisory", "enforced"}


def _error(message: str) -> dict:
    return {
        "status": "invalid",
        "path": POLICY_PATH,
        "applicable_rules": [],
        "warnings": [message],
        "merge_enforcement": "disabled",
    }


def evaluate_standards(root: Path, changed_paths: Iterable[str]) -> dict:
    """Read a bounded local JSON rule catalog, returning guidance only.

    Rules marked 'enforced' still cannot block: a verified defect with a
    reachable consequence is needed before any future merge-enforcement layer.
    """
    root = root.resolve()
    policy = root / POLICY_PATH
    if policy.is_symlink():
        return _error("Standards file is a symlink; refusing to follow it")
    if not policy.exists():
        return {
            "status": "not_configured", "path": POLICY_PATH,
            "applicable_rules": [], "warnings": [],
            "merge_enforcement": "disabled",
        }
    try:
        candidate = policy.resolve(strict=True)
        candidate.relative_to(root)
        if not candidate.is_file() or candidate.stat().st_size > MAX_BYTES:
            return _error("Standards file is missing, not a regular file, or oversized")
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return _error(f"Cannot read standards: {type(exc).__name__}")

    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        return _error("Standards must be a JSON object with schema_version=1")
    rules = parsed.get("rules")
    if not isinstance(rules, list) or len(rules) > 100:
        return _error("Standards rules must be a list of at most 100 entries")
    validated = []
    seen = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            return _error(f"Rule {i} must be an object")
        rid = rule.get("id")
        patterns = rule.get("paths")
        if not isinstance(rid, str) or not ID_PATTERN.fullmatch(rid) or rid in seen:
            return _error(f"Rule {i} needs a unique upper-case ID")
        seen.add(rid)
        if rule.get("level") not in LEVELS or rule.get("state") not in STATES:
            return _error(f"Rule {rid} has unsupported level or state")
        if (not isinstance(patterns, list) or not patterns or len(patterns) > 20
                or any(not isinstance(p, str) or not p.strip() or len(p) > 180
                       or p.startswith("/") or ".." in p.split("/") for p in patterns)):
            return _error(f"Rule {rid} has invalid paths")
        for field in ("title", "source", "rationale"):
            value = rule.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 1200:
                return _error(f"Rule {rid} has invalid {field}")
        validated.append(rule)

    selected = []
    for rule in validated:
        affected = sorted({p.replace("\\", "/") for p in changed_paths
                           if any(fnmatchcase(p.replace("\\", "/"), pat) for pat in rule["paths"])})
        if affected:
            selected.append({
                "id": rule["id"], "title": rule["title"],
                "level": rule["level"], "state": rule["state"],
                "source": rule["source"], "rationale": rule["rationale"],
                "matched_paths": affected,
                "verification": "not_evaluated",
                "disposition": "guidance_only",
            })
    return {
        "status": "loaded", "path": POLICY_PATH,
        "catalog_size": len(validated), "applicable_rules": selected,
        "warnings": [],
        "merge_enforcement": "disabled",
        "limitations": [
            "Applicability is filename-glob matching, not proof of a violation.",
            "Rules and source citations must be verified independently by the reviewer.",
            "Even state=enforced is non-blocking until separate verified-evidence gating exists.",
        ],
    }
