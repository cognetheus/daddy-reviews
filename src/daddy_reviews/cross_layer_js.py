"""R7.05: bounded JS/TS literal HTTP call candidates.

Only simple, literal, relative URL calls are matched. This is not TS compiler
resolution, runtime HTTP evidence, or a general JavaScript parser.
"""
from __future__ import annotations

import re
from .js_graph import _mask_noncode

_HTTP = re.compile(
    r'''(?<![\w.$])(?P<callee>fetch|axios\.(?:get|post|put|patch|delete))\s*'''
    r'''\(\s*(?P<quote>['"])(?P<url>/[^'"\n]{0,300})(?P=quote)'''
    r'''(?P<rest>\s*(?:,\s*\{[^{}]{0,350}\}\s*)?)\)''',
    re.IGNORECASE,
)
_METHOD = re.compile(r'''(?:^|,)\s*method\s*:\s*(?P<q>['"])(?P<method>[A-Za-z]+)(?P=q)\s*(?:,|$)''', re.I)
_FETCH_TOKEN = re.compile(r'(?<![\w.$])fetch\s*\(')
_AXIOS_TOKEN = re.compile(r'(?<![\w.$])axios\.(?:get|post|put|patch|delete)\s*\(', re.I)
_ALLOWED = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def extract_http_calls(path: str, source: str) -> tuple[list[dict], list[dict]]:
    """Return source-grounded candidates and unsupported/dynamic call records."""
    masked = _mask_noncode(source)
    calls: list[dict] = []
    matched_starts = set()
    for m in _HTTP.finditer(source):
        start = m.start()
        if not re.match(r"(?:fetch|axios\.)", masked[start:start + 7]):
            continue
        callee = m.group("callee")
        method = "GET" if callee.lower() == "fetch" else callee.rsplit(".", 1)[1].upper()
        rest = m.group("rest").strip()
        if callee.lower() == "fetch" and rest:
            opts = rest.lstrip(",").strip()
            if not opts.startswith("{") or not opts.endswith("}"):
                continue
            body = opts[1:-1].strip()
            if not body:
                pass
            else:
                match = _METHOD.search(body)
                # A nonliteral or unknown method is not assumed to be GET.
                if match is None or match.group("method").upper() not in _ALLOWED:
                    continue
                method = match.group("method").upper()
        url = m.group("url")
        # Static query parameters are not stripped: matching must be exact.
        if not url or not url.startswith("/") or url.startswith("//") or any(
            c in url for c in "{}$?\\\r"
        ):
            continue
        matched_starts.add(start)
        calls.append({"path": path, "line": source.count("\n", 0, start) + 1,
                      "method": method, "url": url, "kind": "js_literal_http_call"})
    abstentions: list[dict] = []
    for regex in (_FETCH_TOKEN, _AXIOS_TOKEN):
        for m in regex.finditer(masked):
            if m.start() in matched_starts:
                continue
            abstentions.append({"path": path, "line": source.count("\n", 0, m.start()) + 1,
                               "reason": "dynamic_or_unsupported_http_call"})
    return calls, abstentions
