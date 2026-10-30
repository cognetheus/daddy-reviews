"""Deterministic, advisory review tiering and context triage.

Cloudflare's risk-tier idea adapted for an offline, evidence-first review engine.
No LLMs are invoked, no source is skipped from the existing analyzers, and
tiering never constitutes a security finding or a merge decision.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from fnmatch import fnmatchcase
from .diff import FileDiff

SECURITY_PARTS = frozenset({
    "auth", "authentication", "authorization", "authorisation", "crypto",
    "cryptography", "security", "permissions", "secrets", "identity",
    "iam", "access-control", "acl", "rbac", "oauth",
})
CRITICAL_PARTS = frozenset({
    "migrations", "migration", "payment", "payments", "billing",
    "tenant", "tenants", "terraform", "kubernetes", "helm", "policies",
})
LOCK_FILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "cargo.lock", "poetry.lock", "pipfile.lock", "go.sum", "flake.lock",
})
MINIFIED_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".map")
GENERATED_MARKERS = ("@generated", "code generated", "do not edit", "auto-generated")
REVIEWERS = {
    "trivial": ("code-quality",),
    "lite": ("code-quality", "documentation", "standards"),
    "full": ("code-quality", "security", "documentation", "standards", "release", "performance"),
}

@dataclass(frozen=True)
class ReviewTier:
    tier: str
    changed_files: int
    changed_lines: int
    reasons: tuple[str, ...]
    recommended_reviewers: tuple[str, ...]
    context_only_files: tuple[str, ...]
    review_required_files: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _parts(path: str) -> set[str]:
    # Only exact path components count as security-sensitive: avoid substring
    # matches such as "author" being mistaken for "auth".
    return set(path.replace("\\", "/").lower().split("/"))


def _is_migration(path: str) -> bool:
    segments = _parts(path)
    return bool(segments & {"migration", "migrations", "schema", "schemas"})


def _priority(path: str) -> str | None:
    parts = _parts(path)
    name = path.replace("\\", "/").lower().split("/")[-1]
    if parts & SECURITY_PARTS or name.startswith(("auth_", "security_", "permissions_")):
        return "security-sensitive"
    if parts & CRITICAL_PARTS or _is_migration(path):
        return "high-impact-boundary"
    if name in ("dockerfile", "agents.md") or path.lower().startswith(".github/workflows/"):
        return "operational-boundary"
    return None


def _generated(root: Path, path: str) -> bool:
    # Optional only: never read arbitrary absolute paths or symlink targets.
    candidate = root / path
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
        if resolved.stat().st_size > 256_000:
            return False
        with resolved.open("r", encoding="utf-8", errors="replace") as source:
            header = "".join(source.readline() for _ in range(6)).lower()
    except (OSError, ValueError):
        return False
    return any(marker in header for marker in GENERATED_MARKERS)


def _context_only(root: Path, path: str) -> str | None:
    norm = path.replace("\\", "/").lower()
    name = norm.split("/")[-1]
    if _priority(norm) or _is_migration(norm):
        return None  # Never suppress migration or trust-boundary review.
    if name in LOCK_FILES:
        return "lockfile (review dependency metadata separately)"
    if name.endswith(MINIFIED_SUFFIXES):
        return "minified or sourcemap asset"
    if set(norm.split("/")) & {"vendor", "vendored", "node_modules", "dist"}:
        return "vendored or build artifact"
    if _generated(root, path):
        return "generated source (manual source-of-truth review may be needed)"
    return None


def assess_review_tier(root: Path, changes: list[FileDiff]) -> dict:
    """Return routing *advice* without disabling review or deciding approval."""
    reasons = []
    context_only = []
    required = []
    warnings = []
    lines = sum(len(c.added_lines) + len(c.deleted_lines) for c in changes)
    for change in changes:
        path = change.new_path or change.old_path
        boundary = _priority(path)
        if boundary:
            reasons.append(f"{boundary}: {path}")
        noise = _context_only(root, path)
        if noise:
            context_only.append(path)
            warnings.append(f"{path}: {noise}; file remains in evidence packet")
        else:
            required.append(path)
        if change.binary:
            warnings.append(f"{path}: binary change requires independent review")
    if not changes:
        tier = "lite"  # An empty/unparsable diff must not be passed off as reviewed.
        warnings.append("No parsed file changes; check supplied diff and revision selection")
    elif any(_priority(c.new_path or c.old_path) for c in changes):
        tier = "full"
    elif len(changes) > 20 or lines > 100:
        tier = "full"
    elif len(changes) <= 20 and lines <= 10:
        tier = "trivial"
    else:
        tier = "lite"
    if not reasons:
        reasons.append(f"diff size: {len(changes)} files, {lines} changed lines")
    return ReviewTier(
        tier=tier,
        changed_files=len(changes),
        changed_lines=lines,
        reasons=tuple(dict.fromkeys(reasons)),
        recommended_reviewers=REVIEWERS[tier],
        context_only_files=tuple(dict.fromkeys(context_only)),
        review_required_files=tuple(dict.fromkeys(required)),
        warnings=tuple(dict.fromkeys(warnings)),
    ).as_dict()
