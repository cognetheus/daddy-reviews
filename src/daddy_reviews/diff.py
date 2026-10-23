"""Deterministic unified Git diff parsing (read-only, independent of GitHub APIs)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import shlex
import subprocess
from pathlib import Path

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
MAX_PATCH_BYTES = 8_000_000


class DiffError(ValueError):
    """Invalid, unsupported or unsafe diff input."""


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    status: str = "modified"
    hunks: list[Hunk] = field(default_factory=list)
    added_lines: list[int] = field(default_factory=list)
    deleted_lines: list[int] = field(default_factory=list)
    binary: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _path(raw: str, prefix: str = "") -> str:
    """Decode Git's quotes and remove the a/ or b/ diff prefix."""
    raw = raw.strip()
    try:
        fields = shlex.split(raw)
    except ValueError as exc:
        raise DiffError(f"Invalid quoted Git path: {raw!r}") from exc
    if len(fields) != 1:
        raise DiffError(f"Ambiguous Git path: {raw!r}")
    value = fields[0]
    if value == "/dev/null":
        return ""
    if prefix and value.startswith(prefix):
        return value[len(prefix):]
    return value


def parse_diff(patch: str) -> list[FileDiff]:
    """Parse changed lines and file status without making claims about behavior.

    Only actual '+'/'-' lines are counted, not hunk context or header lines.
    FileDiff line numbers refer to the new file for additions and old for removals.
    """
    if len(patch.encode('utf-8')) > MAX_PATCH_BYTES:
        raise DiffError("Patch exceeds safety limit")
    results: list[FileDiff] = []
    current: FileDiff | None = None
    old_line = new_line = 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith('diff --git '):
            try:
                parts = shlex.split(line[len('diff --git '):])
            except ValueError as exc:
                raise DiffError('Malformed diff header') from exc
            if len(parts) != 2 or not parts[0].startswith('a/') or not parts[1].startswith('b/'):
                raise DiffError(f"Malformed diff header: {line}")
            current = FileDiff(parts[0][2:], parts[1][2:])
            results.append(current)
            in_hunk = False
            continue
        if current is None:
            continue
        if line.startswith('new file mode '):
            current.status = 'added'
        elif line.startswith('deleted file mode '):
            current.status = 'deleted'
        elif line.startswith('rename from '):
            current.status = 'renamed'
            current.old_path = _path(line[len('rename from '):])
        elif line.startswith('rename to '):
            current.new_path = _path(line[len('rename to '):])
        elif line.startswith('Binary files ') or line == 'GIT binary patch':
            current.binary = True
            in_hunk = False
        elif line.startswith('--- '):
            current.old_path = _path(line[4:], 'a/')
        elif line.startswith('+++ '):
            current.new_path = _path(line[4:], 'b/')
        elif (match := HUNK.match(line)):
            old_line = int(match[1])
            new_line = int(match[3])
            current.hunks.append(Hunk(old_line, int(match[2] or 1), new_line, int(match[4] or 1)))
            in_hunk = True
        elif in_hunk:
            if line.startswith('+'):
                current.added_lines.append(new_line)
                new_line += 1
            elif line.startswith('-'):
                current.deleted_lines.append(old_line)
                old_line += 1
            elif line.startswith(' '):
                old_line += 1
                new_line += 1
            elif line.startswith('\\ No newline at end of file'):
                continue
            else:
                in_hunk = False
    return results


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(['git', '-C', str(root), *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DiffError(f'Git unavailable or timed out: {type(exc).__name__}') from exc
    if result.returncode != 0:
        raise DiffError(f"Git command failed: {result.stderr.strip()[:400]}")
    if len(result.stdout.encode('utf-8')) > MAX_PATCH_BYTES:
        raise DiffError('Git output exceeds safety limit')
    return result.stdout.strip() if args and args[0]=='rev-parse' else result.stdout


def git_diff(root: Path, base: str = 'HEAD~1', head: str = 'HEAD') -> str:
    """Read diff between revisions. No shell execution, network, or Git writes."""
    for ref in (base, head):
        if not ref or ref.startswith('-') or '\x00' in ref:
            raise DiffError('Invalid revision')
    root = root.resolve()
    base_sha = _git(root, 'rev-parse', '--verify', '--end-of-options', base + '^{commit}')
    head_sha = _git(root, 'rev-parse', '--verify', '--end-of-options', head + '^{commit}')
    return _git(root, '-c', 'core.quotePath=false', 'diff', '--no-ext-diff',
                '--no-textconv', '--find-renames', '--unified=0',
                f'{base_sha}...{head_sha}', '--')
