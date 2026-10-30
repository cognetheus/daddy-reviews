"""R7.02 real compiler test coverage: barrel/alias/shadow/tsconfig/provenance."""
import json
from pathlib import Path

import pytest

from daddy_reviews.cli import main
from daddy_reviews.semantic_contracts import capture_worktree
from daddy_reviews.ts_semantic import (
    TS_INSTALL, TypeScriptSemanticError, index_typescript,
)

pytestmark = pytest.mark.skipif(
    not TS_INSTALL.exists(),
    reason="Optional pinned TypeScript compiler not installed; CI installs 6.0.3",
)


def write(root, name, value):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def test_typescript_barrel_reexport_resolves_real_call_identity(tmp_path):
    corpus = json.loads((Path(__file__).resolve().parents[1] /
                         "evals/r7_context_scenarios.json").read_text())
    scenario = next(x for x in corpus["cases"]
                    if x["id"] == "typescript-barrel-reexport")
    for name, source in scenario["files"].items():
        write(tmp_path, name, source)
    result = index_typescript(tmp_path, "src/core.ts", "calculateTax")
    assert result["status"] == "complete", result["warnings"]
    assert result["compiler_version"] == "6.0.3"
    assert result["definition"]["path"] == "src/core.ts"
    assert [(r["location"]["path"], r["location"]["start_line"]) for r in result["references"]] == [
        ("src/checkout.ts", 2)
    ]
    assert result["references"][0]["relationship"] == "direct_call"
    assert result["references"][0]["target_location"]["source_sha256"] == result["definition"]["source_sha256"]
    assert result["references"][0]["location"]["origin"] == "compiler"
    assert result["context_bundle"]["verified_runtime_calls"] is False


def test_shadowed_import_does_not_invent_external_caller(tmp_path):
    corpus = json.loads((Path(__file__).resolve().parents[1] /
                         "evals/r7_context_scenarios.json").read_text())
    scenario = next(x for x in corpus["cases"]
                    if x["id"] == "typescript-shadowed-local")
    for name, source in scenario["files"].items():
        write(tmp_path, name, source)
    result = index_typescript(tmp_path, "src/lib.ts", "authorize")
    assert result["status"] in {"complete", "partial"}
    assert not result["references"]


def test_direct_aliases_tsconfig_paths_and_unrelated_symbol(tmp_path):
    write(tmp_path, "tsconfig.json", json.dumps({
        "compilerOptions": {"baseUrl": ".", "paths": {"@core/*": ["src/core/*"]}}
    }))
    write(tmp_path, "src/core/security.ts",
          "export function authorize(id: string) { return id.length > 0; }\n")
    write(tmp_path, "src/routes/check.ts",
          "import { authorize as allow } from '@core/security';\n"
          "function authorize() { return false; }\n"
          "export const check = (n: string) => allow(n) && authorize();\n")
    result = index_typescript(tmp_path, "src/core/security.ts", "authorize")
    assert result["status"] == "complete", result["warnings"]
    assert [(r["location"]["path"], r["location"]["start_line"]) for r in result["references"]] == [
        ("src/routes/check.ts", 3)
    ]


def test_no_eval_of_malicious_import_or_project_scripts(tmp_path):
    write(tmp_path, "src/lib.ts", "export function safe() { return true; }\n")
    write(tmp_path, "src/consumer.ts",
          "import { safe } from './lib';\n"
          "const fs = require('fs');\n"
          "fs.writeFileSync('should-never-exist', 'oops');\n"
          "export const result = safe();\n")
    result = index_typescript(tmp_path, "src/lib.ts", "safe")
    assert result["status"] in {"complete", "partial"}
    assert len(result["references"]) == 1
    assert not (tmp_path / "should-never-exist").exists()


def test_snapshot_hash_rejects_changed_file_before_compiler(tmp_path):
    write(tmp_path, "src/module.ts", "export function run() { return 1; }\n")
    snapshot = capture_worktree(tmp_path)
    write(tmp_path, "src/module.ts", "export function run() { return 2; }\n")
    result = index_typescript(tmp_path, "src/module.ts", "run", snapshot=snapshot)
    assert result["status"] == "stale"
    assert result["references"] == []


def test_incomplete_source_set_never_claims_compiler_resolution(tmp_path):
    write(tmp_path, "src/module.ts", "export function run() { return true; }\n")
    write(tmp_path, "too_big.ts", "x" * 350_001)
    result = index_typescript(tmp_path, "src/module.ts", "run")
    assert result["status"] == "incomplete"
    assert result["context_bundle"] is None


def test_compiler_missing_dependency_abstains(tmp_path, monkeypatch):
    import daddy_reviews.ts_semantic as module
    write(tmp_path, "src/module.ts", "export function run() { return true; }\n")
    monkeypatch.setattr(module, "TS_INSTALL", tmp_path / "missing-package.json")
    result = index_typescript(tmp_path, "src/module.ts", "run")
    assert result["status"] == "unavailable"
    assert not result["references"]


def test_malformed_target_and_missing_declaration_are_not_fabricated(tmp_path):
    write(tmp_path, "a.ts", "export const f = () => true;\n")
    with pytest.raises(TypeScriptSemanticError):
        index_typescript(tmp_path, "../a.ts", "f")
    result = index_typescript(tmp_path, "a.ts", "nonexistent")
    assert result["status"] == "unresolved"
    assert not result["references"]


def test_ts_semantic_cli_outputs_compiler_provenance(tmp_path, capsys):
    write(tmp_path, "a.ts", "export const f = () => true;\n")
    write(tmp_path, "b.ts", "import { f } from './a';\nexport const z = f();\n")
    main(["ts-semantic", "--root", str(tmp_path), "--changed", "a.ts", "--symbol", "f"])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "complete", result["warnings"]
    assert result["references"][0]["location"]["path"] == "b.ts"
    assert result["compiler_version"] == "6.0.3"


def test_typescript_interface_type_and_heritage_references(tmp_path):
    write(tmp_path, "src/contracts.ts",
          "export interface Authenticator { check(token: string): boolean; }\n")
    write(tmp_path, "src/service.ts",
          "import type { Authenticator } from './contracts';\n"
          "export class Service implements Authenticator {\n"
          "  check(token: string): boolean { return token.length > 0; }\n"
          "}\n"
          "export const use = (a: Authenticator) => a.check('ok');\n")
    result = index_typescript(tmp_path, "src/contracts.ts", "Authenticator")
    assert result["status"] == "complete", result["warnings"]
    refs = {(r["relationship"], r["location"]["path"],
             r["location"]["start_line"]) for r in result["references"]}
    assert ("heritage_reference", "src/service.ts", 2) in refs
    assert ("type_reference", "src/service.ts", 5) in refs
    assert all(r["location"]["origin"] == "compiler" for r in result["references"])


def test_constructor_and_member_method_references(tmp_path):
    write(tmp_path, "src/processor.ts",
          "export class Processor {\n"
          "  run(input: number) { return input + 1; }\n"
          "}\n")
    write(tmp_path, "src/main.ts",
          "import { Processor as Handler } from './processor';\n"
          "const worker = new Handler();\n"
          "export const result = worker.run(1);\n")
    ctor = index_typescript(tmp_path, "src/processor.ts", "Processor")
    method = index_typescript(tmp_path, "src/processor.ts", "run")
    assert ctor["status"] == "complete", ctor["warnings"]
    assert method["status"] == "complete", method["warnings"]
    assert [(r["relationship"], r["location"]["start_line"])
            for r in ctor["references"]] == [("constructor_call", 2)]
    assert [(r["relationship"], r["location"]["start_line"])
            for r in method["references"]] == [("member_call", 3)]


def test_unresolved_import_causes_partial_coverage_not_false_completeness(tmp_path):
    write(tmp_path, "src/core.ts", "export function process() { return 1; }\n")
    write(tmp_path, "src/consumer.ts",
          "import { process } from './core';\n"
          "import { missing } from './absent';\n"
          "export const result = process();\n")
    result = index_typescript(tmp_path, "src/core.ts", "process")
    assert result["status"] == "partial"
    assert any("unresolved" in w.lower() for w in result["warnings"])
    assert result["references"][0]["location"]["path"] == "src/consumer.ts"


def test_unsupported_typescript_major_version_fails_closed(tmp_path, monkeypatch):
    import daddy_reviews.ts_semantic as adapter
    write(tmp_path, "src/core.ts", "export function f() { return 1; }\n")
    fake_package = tmp_path / "compiler-version.json"
    fake_package.write_text('{"version": "7.0.2"}')
    monkeypatch.setattr(adapter, "TS_INSTALL", fake_package)
    result = index_typescript(tmp_path, "src/core.ts", "f")
    assert result["status"] == "unavailable"
    assert result["references"] == []
