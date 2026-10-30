"""R7.01: versioned, provenance-first contracts for future semantic adapters.

A worktree snapshot is a bounded *content-hash manifest*, not a Git commit
identity and not a promise that files remain unchanged after indexing.
Compiler/AST adapters in later phases must provide source-backed spans.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

from .inspect import EXCLUDE, SOURCES

FORMAT = "daddy-reviews-semantic-snapshot-v1"
MAX_FILES = 4000
MAX_FILE_BYTES = 350_000
MAX_TOTAL_BYTES = 24_000_000
MAX_MANIFEST_BYTES = 2_000_000
CONFIG = {"tsconfig.json", "jsconfig.json", "pyproject.toml", "go.mod", "pom.xml"}
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
ORIGINS = {"compiler", "language_server", "ast", "lexical", "manual", "test", "runtime"}
CERTAINTY = {"resolved", "candidate", "unknown"}


class SemanticContractError(ValueError):
    """Malformed, unsafe, stale or unsupported semantic evidence."""


def _safe_path(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > 1024:
        return False
    if "\\" in value or "\x00" in value or "\n" in value or "\r" in value:
        return False
    try:
        p = PurePosixPath(value)
        return (not p.is_absolute() and str(p) == value
                and all(part not in {".", "..", ""} for part in value.split("/")))
    except ValueError:
        return False


def _hash(value: str) -> bool:
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def _content_id(files: list[dict], complete: bool) -> str:
    data = json.dumps({"format": FORMAT, "files": files, "complete": complete},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(b"daddy-reviews-semantic-v1\0" + data).hexdigest()


def _line_count(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _source_file(path: str, data: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "line_count": _line_count(data)}


def _manifest(files: list[dict], warnings: list[str]) -> dict:
    ordered = sorted(files, key=lambda f: f["path"])
    complete = not warnings
    return {"format": FORMAT, "source_kind": "working_tree_manifest",
            "snapshot_id": _content_id(ordered, complete), "complete": complete,
            "files": ordered, "warnings": warnings[:50],
            "provenance": "local_filesystem_bytes_not_authenticated_git_tree"}


def capture_worktree(root: Path) -> dict:
    """Capture bounded bytes without following symlinks or running source code.

    Incomplete scans retain explicit warnings and cannot qualify for verified
    downstream analysis. No files or network resources are written.
    """
    root = root.resolve()
    if not root.is_dir():
        raise SemanticContractError("Snapshot root must be a directory")
    files: list[dict] = []
    warnings: list[str] = []
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            file = Path(directory) / name
            if file.suffix not in SOURCES and name not in CONFIG:
                continue
            rel = file.relative_to(root).as_posix()
            if not _safe_path(rel):
                warnings.append("Unsafe path was not indexed")
                continue
            if file.is_symlink():
                warnings.append(f"{rel}: source symlink not followed")
                continue
            try:
                before = file.stat()
                if not file.is_file():
                    continue
                if before.st_size > MAX_FILE_BYTES:
                    warnings.append(f"{rel}: exceeds per-file budget")
                    continue
                if len(files) >= MAX_FILES or total + before.st_size > MAX_TOTAL_BYTES:
                    warnings.append("Snapshot file or byte budget exhausted")
                    return _manifest(files, warnings)
                data = file.read_bytes()
                after = file.stat()
                if (len(data) != before.st_size or after.st_size != before.st_size
                        or after.st_mtime_ns != before.st_mtime_ns
                        or after.st_ino != before.st_ino):
                    warnings.append(f"{rel}: changed while scanning")
                    continue
            except OSError:
                warnings.append(f"{rel}: unreadable or changed while scanning")
                continue
            files.append(_source_file(rel, data))
            total += len(data)
    return _manifest(files, warnings)


def validate_snapshot(value: dict) -> dict:
    """Validate an untrusted manifest and reject forged IDs or path traversal."""
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise SemanticContractError("Unsupported source snapshot format")
    if value.get("source_kind") != "working_tree_manifest":
        raise SemanticContractError("R7.01 only supports worktree manifests")
    if value.get("provenance") != "local_filesystem_bytes_not_authenticated_git_tree":
        raise SemanticContractError("Snapshot provenance is missing")
    files, warnings = value.get("files"), value.get("warnings")
    if (not isinstance(files, list) or len(files) > MAX_FILES
            or not isinstance(warnings, list) or len(warnings) > 50
            or any(not isinstance(w, str) or len(w) > 1200 for w in warnings)):
        raise SemanticContractError("Invalid file inventory or warnings")
    if type(value.get("complete")) is not bool or value["complete"] != (len(warnings) == 0):
        raise SemanticContractError("Completeness contradicts warnings")
    previous = ""
    total = 0
    for f in files:
        if not isinstance(f, dict) or set(f) != {"path", "sha256", "size_bytes", "line_count"}:
            raise SemanticContractError("Invalid file record")
        name = f["path"]
        if not _safe_path(name) or name <= previous or not _hash(f["sha256"]):
            raise SemanticContractError("Unsafe, unsorted or duplicate source entry")
        size, count = f["size_bytes"], f["line_count"]
        if (type(size) is not int or not 0 <= size <= MAX_FILE_BYTES
                or type(count) is not int or not 0 <= count <= size + 1):
            raise SemanticContractError("Invalid source sizes or line counts")
        previous = name
        total += size
    if total > MAX_TOTAL_BYTES or value.get("snapshot_id") != _content_id(files, value["complete"]):
        raise SemanticContractError("Source manifest fingerprint mismatch")
    return value


def read_snapshot(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise SemanticContractError("Missing, symlinked or oversized snapshot manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SemanticContractError("Malformed snapshot JSON") from exc
    return validate_snapshot(value)


def verify_worktree(root: Path, previous: dict) -> dict:
    """Compare the whole manifest, including newly added and removed files."""
    validate_snapshot(previous)
    current = capture_worktree(root)
    before = {f["path"]: f["sha256"] for f in previous["files"]}
    after = {f["path"]: f["sha256"] for f in current["files"]}
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    modified = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    fresh = bool(previous["complete"] and current["complete"]
                 and previous["snapshot_id"] == current["snapshot_id"])
    return {"status": "fresh" if fresh else "stale_or_incomplete",
            "snapshot_id": previous["snapshot_id"],
            "current_snapshot_id": current["snapshot_id"],
            "added": added, "removed": removed, "modified": modified,
            "warnings": current["warnings"], "verified": fresh}


@dataclass(frozen=True)
class SourceSpan:
    snapshot_id: str
    path: str
    source_sha256: str
    start_line: int
    end_line: int
    origin: str
    certainty: str

    def __post_init__(self):
        if (not _hash(self.snapshot_id) or not _safe_path(self.path)
                or not _hash(self.source_sha256)
                or type(self.start_line) is not int or type(self.end_line) is not int
                or not 1 <= self.start_line <= self.end_line
                or self.origin not in ORIGINS or self.certainty not in CERTAINTY):
            raise SemanticContractError("Invalid or unproven source span")


def bound_span(snapshot: dict, path: str, start: int, end: int,
               origin: str, certainty: str) -> SourceSpan:
    validate_snapshot(snapshot)
    if not snapshot["complete"]:
        raise SemanticContractError("Incomplete snapshot cannot ground source evidence")
    by_path = {f["path"]: f for f in snapshot["files"]}
    entry = by_path.get(path)
    if entry is None or type(end) is not int or end > entry["line_count"]:
        raise SemanticContractError("Evidence location not present in snapshot manifest")
    return SourceSpan(snapshot["snapshot_id"], path, entry["sha256"],
                      start, end, origin, certainty)


@dataclass(frozen=True)
class SemanticSymbol:
    name: str
    kind: str
    location: SourceSpan

    def __post_init__(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 255:
            raise SemanticContractError("Invalid semantic symbol name")
        if not isinstance(self.kind, str) or not 1 <= len(self.kind) <= 80:
            raise SemanticContractError("Invalid semantic symbol kind")


@dataclass(frozen=True)
class SemanticReference:
    target_name: str
    relationship: str
    location: SourceSpan
    target_location: SourceSpan | None = None


@dataclass(frozen=True)
class ContextExcerpt:
    location: SourceSpan
    text: str
    purpose: str

    def __post_init__(self):
        if (not isinstance(self.text, str) or len(self.text) > 12_000
                or not isinstance(self.purpose, str) or not 1 <= len(self.purpose) <= 200):
            raise SemanticContractError("Invalid context excerpt")


def context_bundle(snapshot: dict, symbols: list[SemanticSymbol] | None = None,
                   references: list[SemanticReference] | None = None,
                   excerpts: list[ContextExcerpt] | None = None) -> dict:
    """Serialize provenance-bound evidence. No compiler claims are invented."""
    validate_snapshot(snapshot)
    if not snapshot["complete"]:
        raise SemanticContractError("Cannot trust references from incomplete snapshots")
    symbols, references, excerpts = symbols or [], references or [], excerpts or []
    if len(symbols) > 500 or len(references) > 2000 or len(excerpts) > 100:
        raise SemanticContractError("Evidence collection exceeds budget")
    files = {f["path"]: f["sha256"] for f in snapshot["files"]}
    spans = [s.location for s in symbols] + [r.location for r in references]
    spans += [r.target_location for r in references if r.target_location is not None]
    spans += [e.location for e in excerpts]
    if any(span.snapshot_id != snapshot["snapshot_id"]
           or files.get(span.path) != span.source_sha256 for span in spans):
        raise SemanticContractError("Stale or cross-snapshot evidence must be rejected")
    return {"format": "daddy-reviews-context-bundle-v1",
            "snapshot_id": snapshot["snapshot_id"],
            "symbols": [asdict(s) for s in symbols],
            "references": [asdict(r) for r in references],
            "excerpts": [asdict(e) for e in excerpts],
            "verified_runtime_calls": False,
            "limitations": ["Provenance asserts captured source bytes, not actual runtime reachability.",
                            "R7.01 contracts only; compiler and language-server adapters follow in R7.02–R7.04."]}
