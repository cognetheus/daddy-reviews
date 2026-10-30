"""Explicit, fail-closed GitHub inline review publication.

Ordinary operation is offline dry-run. A human must curate and approve each
confirmed finding, then explicitly pass --apply and expected PR head SHA.
Never approves a PR, requests changes, or modifies repository content.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_POSTS = 20
MAX_PAGES = 10
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class PublicationError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class GithubAPI:
    def __init__(self, token: str, timeout: float = 15):
        if not token or not token.strip() or not 1 <= timeout <= 60:
            raise PublicationError("GitHub token and bounded timeout required")
        self._token = token
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def request(self, method: str, path: str, data: dict | None = None):
        if method not in {"GET", "POST"} or not path.startswith("/repos/"):
            raise PublicationError("Unsupported GitHub operation")
        url = "https://api.github.com" + path
        body = json.dumps(data).encode() if data is not None else None
        request = Request(url, data=body, method=method, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daddy-reviews",
            **({"Content-Type": "application/json"} if body is not None else {}),
        })
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                value = response.read(2_000_001)
        except (HTTPError, URLError, OSError) as exc:
            raise PublicationError("GitHub API request failed: " + type(exc).__name__) from exc
        if len(value) > 2_000_000:
            raise PublicationError("GitHub response exceeded size limit")
        try:
            return json.loads(value)
        except (ValueError, UnicodeError) as exc:
            raise PublicationError("Invalid GitHub response") from exc


def _safe_path(path):
    if not isinstance(path, str) or len(path) > 400 or "\\" in path:
        return False
    p = PurePosixPath(path)
    return (not p.is_absolute() and str(p) == path and
            all(part not in ("", ".", "..") for part in path.split("/")))


def _marker(finding: dict) -> str:
    # Persistent identity intentionally excludes line and commit: moving
    # unchanged findings must not create repeat comments on each rerun.
    key = "|".join(str(finding[k]).strip().lower() for k in ("rule", "path", "claim"))
    return "<!-- daddy-reviews:" + hashlib.sha256(key.encode()).hexdigest()[:24] + " -->"


def curate_findings(report: dict) -> dict:
    """Require independent verification and explicit per-finding human approval."""
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        raise PublicationError("Report requires a findings array")
    if len(report["findings"]) > 500:
        raise PublicationError("Report is too large")
    ready = []
    omitted = []
    seen = set()
    for index, f in enumerate(report["findings"]):
        if not isinstance(f, dict):
            raise PublicationError("Malformed finding object")
        eligible = (f.get("human_approved") is True
                    and f.get("verification") == "confirmed"
                    and f.get("changed") is True
                    and f.get("severity") in ("critical", "high", "medium", "low")
                    and all(isinstance(f.get(k), str) and 1 <= len(f[k].strip()) <= 2000
                            for k in ("rule", "claim", "evidence", "verification_artifact"))
                    and _safe_path(f.get("path"))
                    and type(f.get("line")) is int and 1 <= f["line"] <= 10_000_000)
        if not eligible:
            omitted.append(index)
            continue
        marker = _marker(f)
        if marker in seen:
            continue
        seen.add(marker)
        ready.append(f)
    if len(ready) > MAX_POSTS:
        raise PublicationError("More than 20 approved findings; curate before publishing")
    return {"eligible": ready, "omitted_indices": omitted}


def _added_lines(patch: str) -> set[int]:
    """Find only new-side added lines in GitHub's per-file hunk text."""
    if not isinstance(patch, str) or len(patch) > 500_000:
        return set()
    added = set()
    new_line = None
    for line in patch.splitlines():
        m = HUNK.match(line)
        if m:
            new_line = int(m.group(1))
        elif new_line is not None and line.startswith("+") and not line.startswith("+++"):
            added.add(new_line)
            new_line += 1
        elif new_line is not None and line.startswith(" "):
            new_line += 1
        elif line.startswith("-") or line.startswith("\\ No newline"):
            pass
        else:
            new_line = None
    return added


def _pages(client, prefix: str, max_pages: int = MAX_PAGES):
    result = []
    for page in range(1, max_pages + 1):
        part = client.request("GET", f"{prefix}?per_page=100&page={page}")
        if not isinstance(part, list):
            raise PublicationError("GitHub paginated response was not an array")
        result.extend(part)
        if len(part) < 100:
            return result
    raise PublicationError("GitHub pagination budget exceeded; refusing incomplete check")


def publish(repo: str, number: int, report: dict, expected_head: str | None = None,
            apply: bool = False, token: str | None = None, client=None) -> dict:
    """Preview offline, or publish individually approved findings to a pinned PR.

    For apply, client is normally GithubAPI. Inject fake client in tests.
    Failure midway is surfaced; rerunning consults existing markers.
    """
    if not isinstance(repo, str) or not REPO.fullmatch(repo) or ".." in repo:
        raise PublicationError("Expected owner/repository GitHub name")
    if type(number) is not int or not 1 <= number <= 1_000_000_000:
        raise PublicationError("Invalid PR number")
    selection = curate_findings(report)
    eligible = selection["eligible"]
    summary = {
        "mode": "apply" if apply else "dry_run",
        "repo": repo, "pr": number,
        "eligible_count": len(eligible),
        "omitted_count": len(selection["omitted_indices"]),
        "posted": [], "skipped_existing": [],
        "merge_action": "none",
    }
    if not apply:
        summary["preview"] = [{"path": f["path"], "line": f["line"],
                               "severity": f["severity"], "marker": _marker(f)}
                              for f in eligible]
        return summary
    if not isinstance(expected_head, str) or not SHA.fullmatch(expected_head):
        raise PublicationError("Applying requires --expected-head-sha (40 lowercase hex chars)")
    if not eligible:
        raise PublicationError("No independently confirmed, human-approved findings to publish")
    if client is None:
        client = GithubAPI(token or os.getenv("GITHUB_TOKEN", ""))
    base = "/repos/" + repo + "/pulls/" + str(number)
    pr = client.request("GET", base)
    if not isinstance(pr, dict) or pr.get("state") != "open":
        raise PublicationError("Pull request must be open")
    sha = (pr.get("head") or {}).get("sha")
    if sha != expected_head:
        raise PublicationError("PR HEAD changed; rerun review before publishing")
    files = _pages(client, base + "/files")
    paths = {f.get("filename"): _added_lines(f.get("patch")) for f in files
             if isinstance(f, dict) and isinstance(f.get("filename"), str)}
    # Check *all* proposed comments before making any writes.
    for f in eligible:
        if f["line"] not in paths.get(f["path"], set()):
            raise PublicationError("Finding is not anchored to a currently added PR line: "
                                   + f["path"] + ":" + str(f["line"]))
    existing = _pages(client, base + "/comments")
    markers = {m.group(0) for item in existing if isinstance(item, dict)
               for m in re.finditer(r"<!-- daddy-reviews:[0-9a-f]{24} -->",
                                    str(item.get("body", "")))}
    for f in eligible:
        marker = _marker(f)
        if marker in markers:
            summary["skipped_existing"].append(marker)
            continue
        body = (f"**{f['severity'].upper()} · {f['rule']}** — {f['claim']}\n\n"
                f"Evidence: {f['evidence']}\n\n"
                f"Human verification artifact: {f['verification_artifact']}\n\n"
                f"{marker}")
        if len(body) > 10_000:
            raise PublicationError("Review comment exceeds message budget")
        result = client.request("POST", base + "/comments", {
            "body": body, "commit_id": expected_head,
            "path": f["path"], "line": f["line"], "side": "RIGHT",
        })
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            raise PublicationError("GitHub did not confirm comment creation")
        summary["posted"].append({"marker": marker, "id": result["id"]})
        markers.add(marker)
    return summary
