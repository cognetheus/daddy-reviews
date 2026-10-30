"""Read-only deterministic repository reconnaissance. Not a semantic analyzer."""
from __future__ import annotations
import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from .core import Finding, Severity, Verification

EXCLUDE = {'.git','.venv','venv','node_modules','dist','build','coverage','__pycache__','.next','obj','bin'}
SOURCES = {'.py', '.ts', '.tsx', '.js', '.jsx', '.cs', '.java'}
@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    line: int

def walk(root: Path):
    for p in root.rglob('*'):
        if any(part in EXCLUDE for part in p.relative_to(root).parts):
            continue
        if p.is_symlink():
            continue
        try:
            if p.is_file() and p.suffix in SOURCES and p.stat().st_size < 500_000:
                yield p
        except OSError:
            continue

def inventory(root: Path) -> dict:
    root = root.resolve()
    symbols = []
    counts = {}
    for path in walk(root):
        counts[path.suffix] = counts.get(path.suffix,0) + 1
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(asdict(Symbol(node.name, type(node).__name__, path.relative_to(root).as_posix(),node.lineno)))
    return {'languages_by_extension': counts, 'python_symbols': symbols, 'files_examined':sum(counts.values())}

def investigate_python(root: Path, changed_paths: set[str] | None = None) -> list[Finding]:
    """Only candidate detections; never label these as confirmed or critical."""
    findings=[]
    for path in walk(root):
        if path.suffix != '.py':
            continue
        rel=path.relative_to(root).as_posix()
        try:
            source=path.read_text(encoding='utf-8')
            tree=ast.parse(source)
        except (SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node,ast.ExceptHandler) and len(node.body)==1 and isinstance(node.body[0],ast.Pass):
                findings.append(Finding('PY-SILENT-EXCEPT',rel,node.body[0].lineno,
                    'Exception is silently discarded',f'Bare pass in except handler at line {node.body[0].lineno}',
                    Severity.LOW,Verification.UNVERIFIED,
                    changed=(rel in changed_paths) if changed_paths is not None else None,
                    recommendation='Determine whether ignoring this failure is intentional; preserve context or handle at the correct boundary.'))
    return findings
