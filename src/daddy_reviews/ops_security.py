"""R8.05d.04: static security preflight of pinned workflow sources.

No network, GitHub writes, scripts, mutable checkout or package installations.
Static content is not a substitute for a live authenticated branch audit,
upstream artifact hashes or a real independent human evaluation.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .operator_artifacts import _safe_regular_read
from .human_attestation import HumanVerificationError
from .ops_telemetry import OperationalError

FORMAT = "daddy-reviews-ops-static-security-v1"
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
SHA_ACTION = re.compile(r"actions/[a-zA-Z0-9_-]+@[a-f0-9]{40}\Z")
MAX_WORKFLOWS = 24


def static_security_preflight(root: Path) -> dict:
    if not isinstance(root, Path) or not root.is_dir():
        raise OperationalError("Repository directory missing")
    checks = {}
    try:
        owners = _safe_regular_read(root / ".github/CODEOWNERS", 16_384).decode("utf-8")
        checks["codeowners_declared"] = (
            "* @cognetheus" in owners
            and "/.github/workflows/ @cognetheus" in owners)
    except (HumanVerificationError, UnicodeError):
        checks["codeowners_declared"] = False
    try:
        constraints = _safe_regular_read(root / "ci/requirements-constraints.txt",
                                         64_000).decode("utf-8")
        checks["python_version_constraints"] = (
            "cryptography==" in constraints and "pytest==" in constraints
            and "cffi==" in constraints)
    except (HumanVerificationError, UnicodeError):
        checks["python_version_constraints"] = False
    try:
        ts_lock = json.loads(_safe_regular_read(
            root / "tooling/typescript/package-lock.json", 128_000))
        indexer = ts_lock["packages"]["node_modules/typescript"]
        checks["typescript_integrity_lock"] = (
            ts_lock.get("lockfileVersion") == 3
            and indexer.get("version") == "6.0.3"
            and isinstance(indexer.get("integrity"), str)
            and indexer["integrity"].startswith("sha512-"))
    except (HumanVerificationError, ValueError, KeyError, TypeError):
        checks["typescript_integrity_lock"] = False
    try:
        sdk = json.loads(_safe_regular_read(
            root / "tooling/dotnet/global.json", 8_192))["sdk"]
        checks["dotnet_exact_sdk"] = (
            sdk.get("version") == "8.0.428"
            and sdk.get("rollForward") == "disable")
    except (HumanVerificationError, ValueError, KeyError, TypeError):
        checks["dotnet_exact_sdk"] = False
    directory = root / ".github/workflows"
    workflows = sorted(directory.glob("*.yml")) if directory.is_dir() and not directory.is_symlink() else []
    checks["bounded_workflow_inventory"] = 8 <= len(workflows) <= MAX_WORKFLOWS
    checks["sha_pinned_official_actions"] = bool(workflows)
    checks["no_privileged_pr_target"] = bool(workflows)
    checks["checkout_credentials_not_persisted"] = bool(workflows)
    checks["explicit_workflow_permissions"] = bool(workflows)
    checks["oidc_signers_contain_only_actions"] = bool(workflows)
    for path in workflows[:MAX_WORKFLOWS]:
        try:
            content = _safe_regular_read(path, 128_000).decode("utf-8")
        except (HumanVerificationError, UnicodeError):
            for name in (
                "sha_pinned_official_actions", "no_privileged_pr_target",
                "checkout_credentials_not_persisted", "explicit_workflow_permissions",
                "oidc_signers_contain_only_actions",
            ):
                checks[name] = False
            continue
        refs = USES.findall(content)
        if not all(SHA_ACTION.fullmatch(ref) for ref in refs):
            checks["sha_pinned_official_actions"] = False
        if ("pull_request_target" in content or "permissions: write-all" in content
                or "secrets." in content):
            checks["no_privileged_pr_target"] = False
        if (len(re.findall(r"uses:\s*actions/checkout@[a-f0-9]{40}", content))
                != len(re.findall(r"^\s*persist-credentials:\s*false$",
                                  content, re.MULTILINE))
                or "persist-credentials: true" in content):
            checks["checkout_credentials_not_persisted"] = False
        if not re.search(r"^permissions:\n\s+contents:\s+read\b",
                         content, re.MULTILINE):
            checks["explicit_workflow_permissions"] = False
        # Split top-level job blocks only; the signing job must not execute
        # a shell or load source code once it has OIDC permission.
        active = "\n".join(line for line in content.splitlines()
                           if not line.lstrip().startswith("#"))
        sections = re.split(r"(?=^  [a-zA-Z0-9_-]+:\s*$)", active, flags=re.MULTILINE)
        for section in sections:
            if "id-token: write" not in section:
                continue
            if (re.search(r"^\s+run:", section, re.MULTILINE)
                    or re.search(r"^\s+env:", section, re.MULTILINE)
                    or "actions/checkout@" in section
                    or "actions/setup-python@" in section
                    or "actions/setup-node@" in section
                    or "actions/setup-dotnet@" in section
                    or "actions/setup-java@" in section):
                checks["oidc_signers_contain_only_actions"] = False
    failures = sorted(name for name, verified in checks.items() if not verified)
    return {
        "format": FORMAT,
        "status": ("local_static_security_checks_passed"
                   if not failures else "local_static_security_checks_failed"),
        "checks": checks,
        "failed_checks": failures,
        "workflow_count": len(workflows),
        "live_github_branch_protection_verified": False,
        "upstream_action_identity_independently_verified": False,
        "runtime_secret_absence_proven": False,
        "release_authorized": False,
        "github_publication": "none", "merge_action": "none",
    }
