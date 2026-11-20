"""R8.05c: locked compiler inputs and constrained Python verification dependencies."""
import base64
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
TS = ROOT / "tooling/typescript"


def test_typescript_version_and_sha512_integrity_are_frozen():
    package = json.loads((TS / "package.json").read_text())
    lock = json.loads((TS / "package-lock.json").read_text())
    assert package["dependencies"] == {"typescript": "6.0.3"}
    assert lock["lockfileVersion"] == 3
    assert set(lock["packages"]) == {"", "node_modules/typescript"}
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    compiler = lock["packages"]["node_modules/typescript"]
    assert compiler["version"] == "6.0.3"
    assert compiler["resolved"] == "https://registry.npmjs.org/typescript/-/typescript-6.0.3.tgz"
    assert compiler["integrity"] == (
        "sha512-y2TvuxSZPDyQakkFRPZHKFm+KKVqIisdg9/CZwm9ftvKXLP8NRWj38/ODjNbr43SsoXqNuAisEf1GdCxqWcdBw=="
    )
    assert len(base64.b64decode(compiler["integrity"].split("-", 1)[1], validate=True)) == 64
    assert "typescript" not in lock.get("dependencies", {})  # npm lockfile v3


def test_npm_ci_refuses_scripts_and_unlocked_install():
    workflow = CI.read_text()
    assert "npm ci --prefix tooling/typescript --ignore-scripts --no-audit --no-fund" in workflow
    assert "npm install --prefix tooling/typescript" not in workflow
    assert "--no-package-lock" not in workflow
    npmrc = (TS / ".npmrc").read_text()
    assert "ignore-scripts=true" in npmrc
    assert "engine-strict=true" in npmrc


def test_dotnet_sdk_patch_is_exact_and_fallback_forbidden():
    sdk = json.loads((ROOT / "tooling/dotnet/global.json").read_text())["sdk"]
    assert sdk == {
        "version": "8.0.428", "rollForward": "disable", "allowPrerelease": False,
    }
    workflow = CI.read_text()
    assert "dotnet-version: '8.0.428'" in workflow
    assert 'test "$(dotnet --version)" = \'8.0.428\'' in workflow
    csproj = (ROOT / "tooling/dotnet/DaddySemanticIndexer.csproj").read_text()
    assert "<PackageReference " not in csproj
    assert "$(MSBuildSDKsPath)/../Roslyn/bincore/" in csproj


def test_all_workflow_verification_installs_use_same_version_constraints():
    constraints = (ROOT / "ci/requirements-constraints.txt").read_text()
    versions = {
        "cryptography": "47.0.0", "cffi": "2.1.1",
        "pytest": "9.2.0", "iniconfig": "2.3.1",
        "packaging": "26.3", "pluggy": "1.7.0", "pygments": "2.21.0",
    }
    for package, version in versions.items():
        assert re.search(r"^" + re.escape(package + "==" + version) + r"$",
                         constraints, re.MULTILINE)
    assert 'pycparser==3.11; python_version < "3.11"' in constraints
    assert 'pycparser==3.12; python_version >= "3.11"' in constraints
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'requires = ["setuptools==80.9.0"]' in pyproject
    assert '"cryptography>=43,<48"' in pyproject
    total = 0
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        data = path.read_text()
        lines = (line.strip() for line in data.splitlines())
        for line in lines:
            if "python -m pip install" in line and not line.startswith("#"):
                if path.name == "advisory-pr-pilot.yml":
                    assert "--constraint daddy-tools/ci/requirements-constraints.txt" in line
                    assert "-e './daddy-tools[verification]'" in line
                    assert "-e ./pr-source" not in line
                else:
                    assert "--constraint ci/requirements-constraints.txt" in line, path
                total += 1
    assert total >= 6
