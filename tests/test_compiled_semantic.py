"""R7.04: real JDK javac and Roslyn symbol identity checks.

Compiler-dependent tests are skipped only on machines without the optional
toolchain; the full GitHub CI matrix installs and executes both toolchains.
"""
import json
import shutil
from pathlib import Path

import pytest

from daddy_reviews.compiled_semantic import (
    CS_HELPER, CompiledSemanticError, JAVA_HELPER, index_compiled,
)
from daddy_reviews.cli import main
from daddy_reviews.semantic_contracts import capture_worktree

JAVA_READY = shutil.which("java") is not None and JAVA_HELPER.exists()
CS_READY = shutil.which("dotnet") is not None and CS_HELPER.exists()


def write(root, path, source):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")


def locations(result):
    return {(r["location"]["path"], r["location"]["start_line"],
             r["relationship"]) for r in result["references"]}


@pytest.mark.skipif(not JAVA_READY, reason="JDK 17+ optional compiler unavailable")
def test_java_method_references_with_actual_javac_symbol_identity(tmp_path):
    write(tmp_path, "src/app/UserService.java",
          "package app;\n"
          "public class UserService {\n"
          "  public boolean authorize(String user) { return user.length()>0; }\n"
          "}\n")
    write(tmp_path, "src/app/Handler.java",
          "package app;\n"
          "public class Handler {\n"
          "  public boolean process(String user) {\n"
          "    UserService service = new UserService();\n"
          "    return service.authorize(user);\n"
          "  }\n"
          "  public boolean authorize(String user) { return false; }\n"
          "}\n")
    result=index_compiled(tmp_path,"java","src/app/UserService.java","UserService.authorize")
    assert result["status"] == "complete", result["warnings"]
    assert ("src/app/Handler.java",5,"method_call") in locations(result)
    assert all(r["location"]["origin"]=="compiler" for r in result["references"])
    assert result["definition"]["path"]=="src/app/UserService.java"
    assert result["runtime_calls_proven"] is False


@pytest.mark.skipif(not JAVA_READY, reason="JDK optional")
def test_java_constructor_and_type_references_and_nonmatching_names(tmp_path):
    write(tmp_path, "pkg/Store.java",
          "package pkg;\n"
          "public class Store { public Store() {} }\n")
    write(tmp_path, "pkg/Controller.java",
          "package pkg;\n"
          "public class Controller {\n"
          "  public Store create() { return new Store(); }\n"
          "}\n")
    result=index_compiled(tmp_path,"java","pkg/Store.java","Store")
    assert result["status"]=="complete",result["warnings"]
    assert ("pkg/Controller.java",3,"constructor_call") in locations(result)


@pytest.mark.skipif(not CS_READY, reason="Roslyn optional dotnet tool not built")
def test_roslyn_method_symbol_and_shadowed_same_name(tmp_path):
    write(tmp_path, "src/UserService.cs",
          "namespace Demo {\n"
          "  public class UserService {\n"
          "    public bool Authorize(string user) => user.Length>0;\n"
          "  }\n"
          "}\n")
    write(tmp_path, "src/Controller.cs",
          "using Demo;\n"
          "namespace App {\n"
          "  public class Controller {\n"
          "    public bool Execute(string user) {\n"
          "      var svc = new UserService();\n"
          "      return svc.Authorize(user);\n"
          "    }\n"
          "    public bool Authorize(string user) => false;\n"
          "  }\n"
          "}\n")
    result=index_compiled(tmp_path,"csharp","src/UserService.cs","UserService.Authorize")
    assert result["status"]=="complete",result["warnings"]
    assert ("src/Controller.cs",6,"method_call") in locations(result)
    assert len([r for r in result["references"] if r["relationship"]=="method_call"])==1
    assert result["definition"]["origin"]=="compiler"


@pytest.mark.skipif(not CS_READY, reason="Roslyn optional dotnet tool not built")
def test_roslyn_constructor_and_type_reference(tmp_path):
    write(tmp_path, "Model.cs",
          "namespace Shop { public class Model { public int Id; } }\n")
    write(tmp_path, "Consumer.cs",
          "using Shop;\n"
          "public class Consumer { public Model Make() { return new Model(); } }\n")
    result=index_compiled(tmp_path,"csharp","Model.cs","Model")
    assert result["status"]=="complete",result["warnings"]
    assert ("Consumer.cs",2,"constructor_call") in locations(result)


@pytest.mark.parametrize("language,extension", [("java",".java"),("csharp",".cs")])
def test_snapshot_changes_prevent_compiler_from_claiming_resolution(tmp_path,language,extension):
    write(tmp_path,"src/Target"+extension,
          "public class Target {}\n")
    prior=capture_worktree(tmp_path)
    write(tmp_path,"src/Target"+extension,
          "public class Target { }\n")
    result=index_compiled(tmp_path,language,"src/Target"+extension,"Target",prior)
    assert result["status"]=="stale"
    assert result["references"]==[]


@pytest.mark.parametrize("language,extension", [("java",".java"),("csharp",".cs")])
def test_invalid_paths_and_unsupported_symbols_are_rejected(tmp_path,language,extension):
    with pytest.raises(CompiledSemanticError):
        index_compiled(tmp_path,language,"../secret"+extension,"Target")
    with pytest.raises(CompiledSemanticError):
        index_compiled(tmp_path,language,"Valid"+extension,"A.B.C")


@pytest.mark.parametrize("language,extension", [("java",".java"),("csharp",".cs")])
def test_incomplete_manifest_prevents_forged_coverage(tmp_path,language,extension):
    write(tmp_path,"src/Target"+extension,"public class Target {}\n")
    write(tmp_path,"giant.py","x"*350001)
    result=index_compiled(tmp_path,language,"src/Target"+extension,"Target")
    assert result["status"]=="incomplete"
    assert result["context_bundle"] is None


@pytest.mark.skipif(not JAVA_READY,reason="JDK optional")
def test_java_unresolved_dependency_results_in_partial_not_clean(tmp_path):
    write(tmp_path,"src/A.java",
          "public class A { public boolean run(){return true;} }\n")
    write(tmp_path,"src/B.java",
          "import missing.dependency.Unknown;\n"
          "public class B { public boolean check(){return new A().run();} }\n")
    result=index_compiled(tmp_path,"java","src/A.java","A.run")
    assert result["status"]=="partial",result["warnings"]
    assert ("src/B.java",2,"method_call") in locations(result)


@pytest.mark.skipif(not CS_READY,reason="Roslyn optional")
def test_roslyn_unresolved_reference_results_in_partial(tmp_path):
    write(tmp_path,"A.cs",
          "public class A { public bool Run(){return true;} }\n")
    write(tmp_path,"B.cs",
          "using Unknown.Namespace;\n"
          "public class B { public bool Go(){return new A().Run();} }\n")
    result=index_compiled(tmp_path,"csharp","A.cs","A.Run")
    assert result["status"]=="partial",result["warnings"]


@pytest.mark.skipif(not JAVA_READY,reason="JDK optional")
def test_java_semantic_cli_reports_valid_snapshot_provenance(tmp_path,capsys):
    write(tmp_path,"A.java","public class A { public boolean go(){return true;} }\n")
    write(tmp_path,"B.java","public class B { boolean check(){return new A().go();} }\n")
    main(["java-semantic","--root",str(tmp_path),"--changed","A.java","--symbol","A.go"])
    result=json.loads(capsys.readouterr().out)
    assert result["status"]=="complete"
    assert result["references"][0]["target_location"]["source_sha256"]==result["definition"]["source_sha256"]


@pytest.mark.skipif(not CS_READY,reason="Roslyn optional")
def test_cs_semantic_cli_reports_valid_snapshot_provenance(tmp_path,capsys):
    write(tmp_path,"A.cs","public class A { public bool Go(){return true;} }\n")
    write(tmp_path,"B.cs","public class B { bool Check(){return new A().Go();} }\n")
    main(["cs-semantic","--root",str(tmp_path),"--changed","A.cs","--symbol","A.Go"])
    result=json.loads(capsys.readouterr().out)
    assert result["status"]=="complete"
    assert result["references"][0]["target_location"]["source_sha256"]==result["definition"]["source_sha256"]
