"""R7.03 AST semantic indexing: precision, provenance and abstention fixtures."""
import json

import pytest

from daddy_reviews.cli import main
from daddy_reviews.py_semantic import PythonSemanticError, index_python
from daddy_reviews.semantic_contracts import capture_worktree


def write(root, path, source):
    f = root / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(source, encoding="utf-8")


def positions(result):
    return {(r["location"]["path"], r["location"]["start_line"],
             r["relationship"]) for r in result["references"]}


def test_import_bound_function_and_async_calls_with_provenance(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/auth.py",
          "async def authorize(user):\n    return bool(user)\n")
    write(tmp_path, "pkg/api.py",
          "from .auth import authorize as allow\n"
          "async def load(user):\n"
          "    return await allow(user)\n")
    result = index_python(tmp_path, "pkg/auth.py", "authorize")
    assert result["status"] == "complete", result["warnings"]
    assert ("pkg/api.py", 3, "direct_call_candidate") in positions(result)
    assert result["references"][0]["location"]["origin"] == "ast"
    assert result["references"][0]["location"]["certainty"] == "candidate"
    assert result["context_bundle"]["verified_runtime_calls"] is False
    assert result["snapshot_id"] == result["definition"]["snapshot_id"]


def test_unconditional_barrel_reexport_chain(tmp_path):
    write(tmp_path, "pkg/auth.py",
          "def authorize(user):\n    return bool(user)\n")
    write(tmp_path, "pkg/__init__.py",
          "from .auth import authorize as check\n")
    write(tmp_path, "src/consumer.py",
          "from pkg import check as allow\n"
          "value = allow('user')\n")
    result = index_python(tmp_path, "pkg/auth.py", "authorize")
    assert result["status"] == "complete", result["warnings"]
    assert ("src/consumer.py", 2, "direct_call_candidate") in positions(result)


def test_module_import_alias_and_unrelated_spelling(tmp_path):
    write(tmp_path, "pkg/checks.py", "def verify(): return True\n")
    write(tmp_path, "main.py",
          "import pkg.checks as checks\n"
          "checks.verify()\n"
          "def verify(): return False\n"
          "verify()\n")
    result = index_python(tmp_path, "pkg/checks.py", "verify")
    assert result["status"] == "complete"
    assert positions(result) == {("main.py", 2, "direct_call_candidate")}


def test_lexical_shadowing_and_duplicate_imports_do_not_claim_calls(tmp_path):
    write(tmp_path, "pkg/auth.py", "def verify(): return True\n")
    write(tmp_path, "consumer.py",
          "from pkg.auth import verify\n"
          "def run(verify):\n"
          "    verify()\n"
          "def other():\n"
          "    verify = lambda: False\n"
          "    return verify()\n")
    result = index_python(tmp_path, "pkg/auth.py", "verify")
    assert result["status"] == "complete"
    assert result["references"] == []


def test_constructor_and_typed_receiver_method_call(tmp_path):
    write(tmp_path, "services/client.py",
          "class Client:\n"
          "    def submit(self, request):\n"
          "        return request\n")
    write(tmp_path, "api.py",
          "from services.client import Client as ApiClient\n"
          "client = ApiClient()\n"
          "client.submit('payload')\n"
          "def route(client: ApiClient):\n"
          "    return client.submit('request')\n"
          "def unrelated(other):\n"
          "    return other.submit('guess')\n")
    result = index_python(tmp_path, "services/client.py", "Client.submit")
    assert result["status"] == "complete", result["warnings"]
    assert ("api.py", 3, "member_call_candidate") in positions(result)
    assert ("api.py", 5, "member_call_candidate") in positions(result)
    assert all(r["location"]["start_line"] != 7 for r in result["references"])


def test_constructor_reference_for_imported_class(tmp_path):
    write(tmp_path, "src/model.py", "class Model:\n    pass\n")
    write(tmp_path, "app.py",
          "from src.model import Model as M\n"
          "instance = M()\n")
    result = index_python(tmp_path, "src/model.py", "Model")
    assert result["status"] == "complete"
    assert ("app.py", 2, "constructor_candidate") in positions(result)


def test_decorator_and_class_heritage_are_candidates(tmp_path):
    write(tmp_path, "pkg/base.py",
          "def decorated(f): return f\n"
          "class Service:\n"
          "    pass\n")
    write(tmp_path, "other.py",
          "from pkg.base import decorated, Service as Parent\n"
          "@decorated\n"
          "def do(): return 1\n"
          "class Child(Parent):\n"
          "    pass\n")
    decorator = index_python(tmp_path, "pkg/base.py", "decorated")
    owner = index_python(tmp_path, "pkg/base.py", "Service")
    assert ("other.py", 2, "decorator_reference") in positions(decorator)
    assert ("other.py", 4, "heritage_reference") in positions(owner)


def test_stale_snapshot_abstains_before_reading_changes(tmp_path):
    write(tmp_path, "pkg/auth.py", "def authorize(): return True\n")
    snapshot = capture_worktree(tmp_path)
    write(tmp_path, "pkg/auth.py", "def authorize(): return False\n")
    result = index_python(tmp_path, "pkg/auth.py", "authorize", snapshot=snapshot)
    assert result["status"] == "stale"
    assert result["references"] == []


def test_missing_duplicate_and_conflicting_target_abstain(tmp_path):
    write(tmp_path, "duplicate.py",
          "def f(): pass\n"
          "def f(): pass\n")
    result = index_python(tmp_path, "duplicate.py", "f")
    assert result["status"] == "ambiguous"
    write(tmp_path, "a.py", "x=1\n")
    assert index_python(tmp_path, "a.py", "absent")["status"] == "unresolved"
    with pytest.raises(PythonSemanticError):
        index_python(tmp_path, "../private.py", "f")


def test_unparseable_other_module_is_partial_with_no_verified_coverage(tmp_path):
    write(tmp_path, "a.py", "def run(): return True\n")
    write(tmp_path, "bad.py", "def syntax(:\n")
    result = index_python(tmp_path, "a.py", "run")
    assert result["status"] == "partial"
    assert any("malformed" in w for w in result["warnings"])


def test_no_inference_from_dynamic_method_or_star_import(tmp_path):
    write(tmp_path, "core.py",
          "class Service:\n"
          "    def execute(self): return True\n")
    write(tmp_path, "other.py",
          "from core import *\n"
          "def call(x): return x.execute()\n")
    result = index_python(tmp_path, "core.py", "Service.execute")
    assert result["references"] == []


def test_py_semantic_cli_reports_source_hashes(tmp_path, capsys):
    write(tmp_path, "src/core.py", "def build(): return True\n")
    write(tmp_path, "main.py",
          "from src.core import build\n"
          "answer = build()\n")
    main(["py-semantic", "--root", str(tmp_path),
          "--changed", "src/core.py", "--symbol", "build"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete", payload["warnings"]
    assert payload["definition"]["path"] == "src/core.py"
    assert payload["references"][0]["target_location"]["source_sha256"] == payload["definition"]["source_sha256"]
    assert payload["runtime_calls_proven"] is False


def test_receiver_reassigned_inside_branch_does_not_stay_bound_to_class(tmp_path):
    write(tmp_path, "src/client.py",
          "class Client:\n"
          "    def submit(self): return True\n")
    write(tmp_path, "other.py",
          "from src.client import Client as C\n"
          "client = C()\n"
          "if flag:\n"
          "    client = object()\n"
          "client.submit()\n")
    result = index_python(tmp_path, "src/client.py", "Client.submit")
    assert result["status"] == "complete"
    assert result["references"] == []


def test_local_import_before_call_is_candidate_but_earlier_call_abstains(tmp_path):
    write(tmp_path, "src/service.py", "def run(): return True\n")
    write(tmp_path, "app.py",
          "def caller():\n"
          "    run()\n"
          "    from src.service import run\n"
          "    return run()\n")
    result = index_python(tmp_path, "src/service.py", "run")
    assert result["status"] == "complete"
    assert positions(result) == {("app.py", 4, "direct_call_candidate")}


def test_duplicate_local_import_name_never_inherits_parent_symbol(tmp_path):
    write(tmp_path, "src/one.py", "def run(): return True\n")
    write(tmp_path, "src/two.py", "def run(): return False\n")
    write(tmp_path, "app.py",
          "from src.one import run\n"
          "def caller():\n"
          "    from src.two import run\n"
          "    return run()\n")
    result = index_python(tmp_path, "src/one.py", "run")
    assert result["references"] == []
