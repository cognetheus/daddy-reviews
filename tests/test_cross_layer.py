"""R7.05 contract/negative tests: literal HTTP -> FastAPI -> service -> DB/event."""
import json

import pytest

from daddy_reviews.cli import main
from daddy_reviews.cross_layer import (
    CrossLayerError, build_cross_layer, cross_layer_impact,
)
from daddy_reviews.cross_layer_js import extract_http_calls
from daddy_reviews.semantic_contracts import capture_worktree


def write(root, path, source):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")


def fixture(root):
    write(root, "app/api.py",
          "from fastapi import FastAPI\n"
          "from app.services import get_user\n"
          "app = FastAPI()\n"
          "@app.get('/api/users')\n"
          "def read_user():\n"
          "    return get_user()\n")
    write(root, "app/services.py",
          "from app.models import User\n"
          "def get_user():\n"
          "    user = db.query(User)\n"
          "    broker.publish('user.loaded')\n"
          "    return user\n")
    write(root, "app/models.py",
          "class User(Base):\n"
          "    __tablename__ = 'users'\n")
    write(root, "app/consumers.py",
          "@broker.subscribe('user.loaded')\n"
          "def on_user_loaded(message):\n"
          "    return message\n")
    write(root, "frontend/client.ts",
          "export async function load() {\n"
          "  return fetch('/api/users');\n"
          "}\n")


def edges(graph, kind):
    return [e for e in graph["edges"] if e["relationship"] == kind]


def test_full_cross_layer_chain_and_provenance(tmp_path):
    fixture(tmp_path)
    g = build_cross_layer(tmp_path)
    assert g["status"] == "complete", g["warnings"]
    assert len(edges(g, "literal_http_route_candidate")) == 1
    assert len(edges(g, "route_handler_candidate")) == 1
    assert len(edges(g, "python_function_call_candidate")) == 1
    assert len(edges(g, "orm_model_use_candidate")) == 1
    assert len(edges(g, "declares_table_candidate")) == 1
    assert len(edges(g, "event_publish_candidate")) == 1
    assert len(edges(g, "event_subscriber_candidate")) == 1
    for link in g["edges"]:
        proof = link["evidence"]
        assert proof["snapshot_id"] == g["snapshot_id"]
        assert proof["source_sha256"] in {
            x["source_sha256"] for x in (n["source"] for n in g["nodes"])
        }
        assert proof["certainty"] == "candidate"
    assert all(e["source"] != e["target"] for e in g["edges"])
    result = cross_layer_impact(g, ["app/services.py"], depth=5)
    inbound_paths = {x["path"] for x in result["inbound_dependents"]}
    outbound_kinds = {x["kind"] for x in result["outbound_dependencies"]}
    assert "app/api.py" in inbound_paths
    assert "frontend/client.ts" in inbound_paths
    assert "model" in outbound_kinds
    assert "table" in outbound_kinds
    assert "topic" in outbound_kinds
    assert "app/consumers.py" in {
        x["path"] for x in result["outbound_dependencies"]
    }
    assert result["classification"] == "source-backed_static_candidate_only"


def test_unmatched_and_duplicate_routes_do_not_invent_http_edges(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/duplicate.py",
          "from fastapi import FastAPI\n"
          "app = FastAPI()\n"
          "@app.get('/api/users')\n"
          "def other(): return 1\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "literal_http_route_candidate")
    assert any(x["reason"] == "ambiguous_http_route" for x in g["abstentions"])
    write(tmp_path, "frontend/client.ts", "fetch('/api/unknown');\n")
    g = build_cross_layer(tmp_path)
    assert any(x["reason"] == "unmatched_http_route" for x in g["abstentions"])
    assert not edges(g, "literal_http_route_candidate")


def test_dynamic_http_and_dynamic_topics_abstain(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "frontend/client.ts", "fetch(dynamicUrl);\n")
    write(tmp_path, "app/services.py",
          "def get_user():\n"
          "    broker.publish(topic_from_config)\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "literal_http_route_candidate")
    assert not edges(g, "event_publish_candidate")
    assert {x["reason"] for x in g["abstentions"]} >= {
        "dynamic_event_topic", "dynamic_or_unsupported_http_call"
    }


def test_shadowed_service_import_does_not_prove_call(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/api.py",
          "from fastapi import FastAPI\n"
          "from app.services import get_user\n"
          "app=FastAPI()\n"
          "@app.get('/api/users')\n"
          "def read_user():\n"
          "    get_user = lambda: 'other'\n"
          "    return get_user()\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "python_function_call_candidate")


def test_orm_same_class_name_without_import_does_not_link(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/services.py",
          "def get_user():\n"
          "    return db.query(User)\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "orm_model_use_candidate")
    assert any(x["reason"] == "orm_receiver_or_model_unresolved"
               for x in g["abstentions"])


def test_duplicate_import_target_is_ambiguous_not_resolved(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/api.py",
          "from fastapi import FastAPI\n"
          "from app.services import get_user\n"
          "from app.other import get_user\n"
          "app=FastAPI()\n"
          "@app.get('/api/users')\n"
          "def read_user(): return get_user()\n")
    write(tmp_path, "app/other.py", "def get_user(): return False\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "python_function_call_candidate")


def test_unsupported_dynamic_fastapi_prefix_does_not_match(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/api.py",
          "from fastapi import APIRouter\n"
          "router = APIRouter(prefix='/api')\n"
          "@router.get('/users')\n"
          "def read_user(): return True\n")
    g = build_cross_layer(tmp_path)
    assert not edges(g, "literal_http_route_candidate")
    assert any(x["reason"] == "unmatched_http_route" for x in g["abstentions"])


def test_js_comments_and_strings_not_mistaken_for_http_calls():
    code = (
        "// fetch('/api/false');\n"
        "const text = \"axios.get('/api/alsofalse')\";\n"
        "fetch('/api/real', {method: 'POST'});\n"
        "axios.delete('/api/other');\n"
        "fetch('/api/dynamic', {method: getMethod()});\n"
    )
    calls, absent = extract_http_calls("web/client.ts", code)
    assert {(x["line"], x["method"], x["url"]) for x in calls} == {
        (3, "POST", "/api/real"), (4, "DELETE", "/api/other")
    }
    assert len(absent) == 1
    assert absent[0]["line"] == 5


def test_snapshot_drift_returns_no_edges(tmp_path):
    fixture(tmp_path)
    snap = capture_worktree(tmp_path)
    write(tmp_path, "app/services.py", "def get_user(): return 1\n")
    result = build_cross_layer(tmp_path, snap)
    assert result["status"] == "stale"
    assert result["edges"] == []


def test_invalid_python_is_partial_not_clean_coverage(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "app/broken.py", "def bad(:\n")
    g = build_cross_layer(tmp_path)
    assert g["status"] == "partial"
    assert any("syntax error" in x for x in g["warnings"])


def test_cli_graph_and_impact_are_json_and_read_only(tmp_path, capsys):
    fixture(tmp_path)
    main(["cross-layer", "--root", str(tmp_path), "--changed", "app/services.py",
          "--max-depth", "5"])
    data = json.loads(capsys.readouterr().out)
    assert data["graph"]["status"] == "complete"
    assert "frontend/client.ts" in {
        x["path"] for x in data["impact"]["inbound_dependents"]
    }
    assert not any(x.name.endswith(".json") for x in tmp_path.iterdir())


def test_bad_paths_and_depth_are_rejected(tmp_path):
    fixture(tmp_path)
    g = build_cross_layer(tmp_path)
    with pytest.raises(CrossLayerError):
        cross_layer_impact(g, ["../../secret"], depth=4)
    with pytest.raises(CrossLayerError):
        cross_layer_impact(g, ["app/services.py"], depth=99)


def test_empty_repo_has_no_fabricated_references(tmp_path):
    g = build_cross_layer(tmp_path)
    assert g["status"] == "complete"
    assert not g["nodes"] and not g["edges"]
