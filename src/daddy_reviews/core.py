"""Deterministic task routing, blast-radius indicators, and finding calibration.

The rules here deliberately abstain from interpreting semantic correctness.
They provide evidence and scope to a human or higher-level reviewer.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
import hashlib
import re
from typing import Iterable

class Severity(str, Enum):
    CRITICAL = 'critical'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    SUGGESTION = 'suggestion'

class Verification(str, Enum):
    CONFIRMED = 'confirmed'
    UNVERIFIED = 'unverified'
    REFUTED = 'refuted'

class Disposition(str, Enum):
    BLOCK = 'block'
    INVESTIGATE = 'investigate'
    DEFER = 'defer'
    ACCEPT = 'accept'
    DISMISS = 'dismiss'

@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    claim: str
    evidence: str
    severity: Severity
    verification: Verification = Verification.UNVERIFIED
    changed: bool | None = None
    mitigation: str = ''
    recommendation: str = ''
    def fingerprint(self) -> str:
        normalized = f'{self.rule}|{self.path}|{self.claim.strip().lower()}'
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    def disposition(self) -> Disposition:
        if self.verification == Verification.REFUTED:
            return Disposition.DISMISS
        if self.verification != Verification.CONFIRMED:
            return Disposition.INVESTIGATE
        if self.severity in {Severity.CRITICAL, Severity.HIGH} and self.changed is True:
            return Disposition.BLOCK
        if self.severity in {Severity.MEDIUM, Severity.LOW}:
            return Disposition.DEFER
        return Disposition.ACCEPT
    def to_dict(self) -> dict:
        return {**asdict(self), 'severity': self.severity.value, 'verification': self.verification.value,
                'disposition': self.disposition().value, 'fingerprint': self.fingerprint()}

@dataclass(frozen=True)
class ReviewPlan:
    mode: str
    depth: int
    reasons: tuple[str, ...]
    dimensions: tuple[str, ...]

SENSITIVE = {
    'auth': ('security', 'integration'), 'permission': ('security',),
    'tenant': ('security', 'data-contract'), 'migration': ('database', 'infrastructure'),
    'schema': ('data-contract',), 'docker': ('infrastructure',),
    'workflow': ('infrastructure',), 'queue': ('messaging', 'reliability'),
    'event': ('messaging',), 'payment': ('security', 'data-contract'),
    'worker': ('messaging', 'reliability'), 'state': ('frontend',),
}

def plan_review(task: str, paths: Iterable[str]) -> ReviewPlan:
    task_lower = task.lower()
    mode = next((key for key, terms in (
        ('incident', ('incident', 'outage', 'production down')),
        ('dependency-upgrade', ('dependency upgrade', 'upgrade dependencies', 'package upgrade')),
        ('refactor', ('refactor', 'restructure')),
        ('bug', ('debug', 'fix bug', 'bug investigation')),
        ('architecture', ('architecture', 'system design')),
        ('feature', ('implement', 'new feature', 'build feature')),
        ('repository-audit', ('full audit', 'whole repo', 'repository audit')),
        ('pr', ('pr', 'pull request', 'review')),
    ) if any(term in task_lower for term in terms)), 'pr')
    files = tuple(p.lower().replace('\\', '/') for p in paths)
    reasons = []
    dims = {'functionality', 'tests', 'maintainability'}
    depth = 1
    if len(files) > 12:
        depth = 2
        reasons.append('multiple changed files require dependency sampling')
    for p in files:
        if any(part in p for part in ('contract', 'proto/', 'openapi', 'migrations/', 'terraform', 'helm/')):
            depth = 3
            reasons.append(f'contract or deployment boundary: {p}')
        for token, extra in SENSITIVE.items():
            if token in p:
                dims.update(extra)
                if token in {'auth', 'permission', 'tenant', 'payment', 'migration', 'schema'}:
                    depth = 3
                    reasons.append(f'high impact boundary: {p}')
                else:
                    depth = max(depth, 2)
    if mode in {'incident','architecture','repository-audit'}:
        depth = 3
        reasons.append(f'explicit {mode} task')
    if mode == 'dependency-upgrade':
        dims.update({'dependencies', 'security', 'integration'})
    if not reasons:
        reasons.append('localized changes; expand only if evidence warrants it')
    return ReviewPlan(mode, depth, tuple(dict.fromkeys(reasons)), tuple(sorted(dims)))

def deduplicate(findings: Iterable[Finding]) -> list[Finding]:
    by_key = {}
    for f in findings:
        key = f.fingerprint()
        old = by_key.get(key)
        if old is None or (old.verification != Verification.CONFIRMED and f.verification == Verification.CONFIRMED):
            by_key[key] = f
    return list(by_key.values())
