"""R8.02: specialist tool-call harness, evidence joins, loop limits and real local transport."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from daddy_reviews.agents import AgentRuntimeError
from daddy_reviews.investigative_agents import (
    FORMAT, investigate_with_specialists, local_investigation_provider,
)


PATCH = (
    "diff --git a/src/auth.py b/src/auth.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n+++ b/src/auth.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def authorize(user):\n"
    "+    return bool(user)\n"
)


def seed(root):
    path = root / "src/auth.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def authorize(user):\n    return bool(user)\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_auth.py").write_text(
        "from src.auth import authorize\n"
        "def test_auth(): assert authorize('ok')\n", encoding="utf-8")


def read_call():
    return {"kind": "tool", "call": {
        "tool": "read_file", "path": "src/auth.py",
        "start_line": 1, "end_line": 2,
    }}


def finding(citations=None, line=1):
    return {"rule": "AUTH-TEST", "path": "src/auth.py", "line": line,
            "claim": "Investigate whether empty user values should be permitted.",
            "evidence": "The return expression passes Boolean truthiness through directly.",
            "severity": "medium", "citations": citations if citations is not None else ["E1"]}


def test_actual_investigation_turns_join_source_and_changed_lines(tmp_path):
    seed(tmp_path)
    calls = []
    def provider(reviewer, messages):
        calls.append((reviewer, messages))
        if len(messages) == 1:
            assert "granted_read_only_tools" in json.loads(messages[0]["content"])
            return read_call()
        observed = json.loads(messages[-1]["content"])
        assert observed["tool_result"]["status"] == "complete"
        assert observed["host_evidence_ids"]["E1"]["path"] == "src/auth.py"
        return {"kind": "final", "findings": [finding()]}
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("code-quality",), max_workers=1,
    )
    assert len(calls) == 2
    assert report["format"] == FORMAT and report["status"] == "complete"
    assert report["model_findings"][0]["verification"] == "unverified"
    assert report["model_findings"][0]["changed"] is True
    assert report["model_findings"][0]["citations"] == ["E1"]
    assert report["model_findings"][0]["source_evidence"][0]["source"]["source_sha256"]
    assert report["model_findings"][0]["source_evidence"][0]["source"]["snapshot_id"] == report["snapshot_id"]
    assert report["adjudication"]["merge_action"] == "none"
    assert report["merge_action"] == report["github_publication"] == "none"
    assert report["reviewer_runs"][0]["audit"][0]["status"] == "complete"


def test_no_citation_id_from_model_counts_as_evidence(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        return read_call() if len(messages) == 1 else {
            "kind": "final", "findings": [finding(["E999"])]
        }
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert report["model_findings"] == []
    assert report["reviewer_runs"][0]["status"] == "failed"


def test_missing_tool_citation_rejects_issue_even_on_changed_line(tmp_path):
    seed(tmp_path)
    report = investigate_with_specialists(
        tmp_path, PATCH, lambda r, m: {"kind":"final","findings":[finding()]},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert not report["model_findings"]


def test_wrong_line_not_rescued_by_related_source_citation(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        if len(messages) == 1:
            return {"kind": "tool", "call": {
                "tool": "read_file", "path": "src/auth.py",
                "start_line": 1, "end_line": 1,
            }}
        return {"kind": "final", "findings": [finding(line=2)]}
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert not report["model_findings"]


def test_unmodified_line_is_rejected_even_with_valid_citation(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        return read_call() if len(messages) == 1 else {
            "kind": "final", "findings": [finding(line=3)]
        }
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert not report["model_findings"]


def test_denied_tool_does_not_execute_and_cannot_create_false_clean(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        if len(messages) == 1:
            return read_call()
        assert json.loads(messages[-1]["content"])["tool_result"]["status"] == "denied"
        return {"kind":"final","findings":[]}
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools=(), reviewers=("security",),
    )
    assert report["reviewer_runs"][0]["audit"][0]["status"] == "denied"
    assert report["status"] == "incomplete"
    assert report["reviewer_runs"][0]["reason"] == "tool_denied"
    assert report["merge_action"] == "none"
    assert report["model_findings"] == []


def test_unknown_tool_and_extra_model_parameters_fail_closed(tmp_path):
    seed(tmp_path)
    for payload in (
        {"kind":"tool","call":{"tool":"run_shell","path":"src/auth.py"}},
        {"kind":"tool","call":{"tool":"read_file","path":"src/auth.py","command":"rm -rf ."}},
        {"kind":"tool","call":{"tool":"read_file","path":"../private.py"}},
        {"kind":"tool","call":{"tool":"read_file","path":"src/auth.py"},"approval": True},
    ):
        report = investigate_with_specialists(
            tmp_path, PATCH, lambda r, m: payload,
            allowed_tools={"read_file"}, reviewers=("security",),
        )
        assert report["status"] == "incomplete"
        assert report["model_findings"] == []


def test_models_cannot_self_confirm_merge_block_or_publish(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        if len(messages) == 1: return read_call()
        bad = dict(finding(), verification="confirmed")
        return {"kind":"final","findings":[bad]}
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert not report["model_findings"]
    assert report["merge_action"] == "none"
    assert report["github_publication"] == "none"


def test_exhausted_rounds_and_tool_budget_never_fabricate_completion(tmp_path):
    seed(tmp_path)
    report = investigate_with_specialists(
        tmp_path, PATCH, lambda r, m: read_call(),
        allowed_tools={"read_file"}, reviewers=("security",),
        max_rounds=2, max_tools_per_reviewer=1,
    )
    assert report["status"] == "incomplete"
    assert report["reviewer_runs"][0]["reason"] == "tool_budget_exhausted"
    assert len(report["reviewer_runs"][0]["audit"]) == 2


def test_model_failure_preserved_in_multi_specialist_summary(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        if reviewer == "security":
            raise TimeoutError("external provider slow")
        return {"kind":"final","findings":[]}
    result = investigate_with_specialists(
        tmp_path, PATCH, provider, reviewers=("security","code-quality"),
        max_workers=2,
    )
    assert result["status"] == "incomplete"
    assert result["model_findings"] == []
    assert [x["reviewer"] for x in result["reviewer_runs"]] == ["security", "code-quality"]
    assert result["merge_action"] == "none"


def test_parallel_specialists_have_isolated_evidence_ids(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        if len(messages) == 1: return read_call()
        return {"kind":"final","findings":[finding()]}
    result = investigate_with_specialists(
        tmp_path, PATCH, provider, reviewers=("security", "code-quality"),
        allowed_tools={"read_file"}, max_workers=2,
    )
    assert result["status"] == "complete"
    assert len(result["model_findings"]) == 2
    assert all(x["citations"] == ["E1"] for x in result["model_findings"])
    assert all(x["verification"] == "unverified" for x in result["model_findings"])
    assert result["adjudication"]["merge_action"] == "none"


def test_empty_findings_are_valid_but_not_a_clean_code_guarantee(tmp_path):
    seed(tmp_path)
    result = investigate_with_specialists(
        tmp_path, PATCH, lambda r, m: {"kind":"final","findings":[]},
        reviewers=("code-quality",),
    )
    assert result["status"] == "complete"
    assert result["model_findings"] == []
    assert result["evidence_policy"] == "host_issued_source_spans_on_added_lines_unverified_defects"


def test_diff_and_worktree_mismatch_abstains_before_provider_invocation(tmp_path):
    seed(tmp_path)
    wrong = PATCH.replace("+    return bool(user)", "+    return True")
    called = []
    def provider(reviewer, messages):
        called.append(1)
        return {"kind":"final","findings":[]}
    with pytest.raises(AgentRuntimeError):
        investigate_with_specialists(tmp_path, wrong, provider)
    assert called == []


def test_incomplete_source_snapshot_abstains_before_model_call(tmp_path):
    seed(tmp_path)
    (tmp_path / "huge.py").write_text("a"*360_000)
    called = []
    with pytest.raises(AgentRuntimeError):
        investigate_with_specialists(tmp_path, PATCH, lambda r, m: called.append(m))
    assert not called


def test_bad_reviewer_and_limits_refused(tmp_path):
    seed(tmp_path)
    def provider(r,m): return {"kind":"final","findings":[]}
    for kwargs in (
        {"reviewers":("unknown-agent",)},
        {"reviewers":("security","security")},
        {"max_rounds":0},
        {"max_tools_per_reviewer":99},
        {"max_workers":0},
        {"allowed_tools":{"write_file"}},
    ):
        with pytest.raises(AgentRuntimeError):
            investigate_with_specialists(tmp_path, PATCH, provider, **kwargs)


def test_real_local_ollama_wire_protocol_no_redirect_or_remote_endpoint(tmp_path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length","0"))
            body = json.loads(self.rfile.read(size))
            requests.append(body)
            if body["model"] == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/receive")
                self.end_headers()
                return
            payload = json.dumps({
                "message": {"content": json.dumps({"kind":"final","findings":[]})},
                "prompt_eval_count": 27, "eval_count": 11,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self,*args): pass
    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        provider = local_investigation_provider("test-local",url,3)
        result = provider("security",[{"role":"user","content":"source context"}])
        assert result == {"kind":"final","findings":[],
                          "_usage":{"input_tokens":27,"output_tokens":11}}
        assert requests[0]["stream"] is False and requests[0]["format"] == "json"
        assert requests[0]["messages"][0]["role"] == "system"
        assert "READ-ONLY" in requests[0]["messages"][0]["content"]
        with pytest.raises(AgentRuntimeError):
            local_investigation_provider("redirect",url,3)(
                "security",[{"role":"user","content":"untrusted"}])
        with pytest.raises(AgentRuntimeError):
            local_investigation_provider("x","https://example.invalid",3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cli_local_model_two_turn_investigation_and_permissions(tmp_path, capsys):
    from daddy_reviews.cli import main

    seed(tmp_path)
    patch_file = tmp_path / "incoming.diff"
    patch_file.write_text(PATCH, encoding="utf-8")
    incoming = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(size))
            incoming.append(req)
            if len(req["messages"]) == 2:
                parsed = read_call()
            else:
                tool_message = json.loads(req["messages"][-1]["content"])
                assert tool_message["host_evidence_ids"]["E1"]["path"] == "src/auth.py"
                parsed = {"kind": "final", "findings": [finding()]}
            response = json.dumps({"message": {"content": json.dumps(parsed)}}).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        def log_message(self,*args): pass

    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        args = ["ai-investigate", "--root", str(tmp_path), "--diff-file", str(patch_file),
                "--model", "test-model", "--ollama-url",
                f"http://127.0.0.1:{server.server_port}",
                "--agent-timeout","3", "--investigation-reviewers", "1",
                "--agent-parallel", "1", "--allow-tool", "read_file"]
        main(args)
        body = json.loads(capsys.readouterr().out)
        assert body["status"] == "complete"
        assert len(body["reviewer_runs"]) == 1
        assert len(body["model_findings"]) == 1
        assert body["model_findings"][0]["citations"] == ["E1"]
        assert len(incoming) == 2
        assert body["github_publication"] == "none"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cli_rejects_missing_model_before_loading_any_diff(tmp_path):
    from daddy_reviews.cli import main
    seed(tmp_path)
    with pytest.raises(SystemExit) as e:
        main(["ai-investigate","--root",str(tmp_path),"--allow-tool","read_file"])
    assert e.value.code == 2


def test_reviewer_number_cap_is_enforced_in_python_api(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        return {"kind":"final","findings":[]}
    report = investigate_with_specialists(
        tmp_path,PATCH,provider,max_reviewers=1,
    )
    assert report["status"] == "complete"
    assert len(report["reviewer_runs"]) == 1


def test_forged_tool_source_hash_is_not_registered_as_host_evidence(tmp_path, monkeypatch):
    import daddy_reviews.investigative_agents as harness
    seed(tmp_path)
    original = harness.InvestigationSession.execute
    def corrupted(self, req):
        response = original(self, req)
        if response["status"] == "complete" and response["evidence"]:
            response["evidence"][0]["source_sha256"] = "0" * 64
        return response
    monkeypatch.setattr(harness.InvestigationSession, "execute", corrupted)
    def provider(reviewer, messages):
        if len(messages) == 1:
            return read_call()
        return {"kind":"final","findings":[finding()]}
    report = investigate_with_specialists(
        tmp_path, PATCH, provider, allowed_tools={"read_file"},
        reviewers=("security",),
    )
    assert report["status"] == "incomplete"
    assert report["model_findings"] == []
    assert report["reviewer_runs"][0]["reason"] == "AgentRuntimeError"


def test_forged_tool_snapshot_id_and_line_range_are_rejected(tmp_path, monkeypatch):
    import daddy_reviews.investigative_agents as harness
    seed(tmp_path)
    original = harness.InvestigationSession.execute
    for invalid in ("snapshot_id", "end_line"):
        def corrupted(self, req):
            response = original(self, req)
            if response["status"] == "complete" and response["evidence"]:
                response["evidence"][0][invalid] = (
                    "bad_snapshot" if invalid == "snapshot_id" else 999999
                )
            return response
        monkeypatch.setattr(harness.InvestigationSession, "execute", corrupted)
        report = investigate_with_specialists(
            tmp_path, PATCH,
            lambda r,m: read_call(),
            allowed_tools={"read_file"},reviewers=("security",),
        )
        assert report["status"] == "incomplete"
        assert report["model_findings"] == []


def test_model_turn_recording_is_opt_in_and_omits_tool_payloads(tmp_path):
    seed(tmp_path)
    def provider(reviewer, messages):
        return read_call() if len(messages) == 1 else {
            "kind": "final", "findings": [finding()],
            "_usage": {"input_tokens": 12, "output_tokens": 8},
        }
    opts = dict(allowed_tools={"read_file"}, reviewers=("security",))
    default = investigate_with_specialists(tmp_path, PATCH, provider, **opts)
    assert default["model_turn_recording"] == "disabled"
    assert "recorded_model_turns" not in default["reviewer_runs"][0]

    captured = investigate_with_specialists(
        tmp_path, PATCH, provider, record_model_turns=True, **opts,
    )
    assert captured["status"] == "complete"
    assert captured["model_turn_recording"] == "opt_in_model_json_only"
    recorded = captured["reviewer_runs"][0]["recorded_model_turns"]
    assert recorded == [read_call(), {"kind": "final", "findings": [finding()]}]
    assert "tool_result" not in json.dumps(recorded)
    assert "source_sha256" not in json.dumps(recorded)
    assert "_usage" not in json.dumps(recorded)
    assert captured["reviewer_runs"][0]["usage"]["input_tokens"] == 12


def test_recorded_provider_timeout_has_replay_fault_marker(tmp_path):
    seed(tmp_path)
    report = investigate_with_specialists(
        tmp_path, PATCH, lambda reviewer, messages: (_ for _ in ()).throw(TimeoutError()),
        reviewers=("security",), record_model_turns=True,
    )
    assert report["status"] == "incomplete"
    assert report["reviewer_runs"][0]["recorded_model_turns"] == [
        {"kind":"transport_error","error":"TimeoutError"},
    ]


def test_recorded_turns_replay_through_same_source_and_citations(tmp_path):
    from daddy_reviews.investigation_eval import evaluate_replay, read_replay_dataset
    seed(tmp_path)
    report = investigate_with_specialists(
        tmp_path, PATCH,
        lambda reviewer, messages: read_call() if len(messages) == 1 else {
            "kind":"final","findings":[finding()],
        },
        allowed_tools={"read_file"}, reviewers=("security",),
        record_model_turns=True,
    )
    corpus = read_replay_dataset(
        Path(__file__).resolve().parents[1] / "evals/investigation_replay_synthetic.json"
    )
    case = next(c for c in corpus["cases"] if c["id"] == "synthetic-matched-defect")
    case["reviewers"][0]["turns"] = report["reviewer_runs"][0]["recorded_model_turns"]
    corpus["cases"] = [case]
    evaluated = evaluate_replay(corpus)
    assert evaluated["status"] == "evaluated"
    assert evaluated["cases"][0]["tp"] == 1
