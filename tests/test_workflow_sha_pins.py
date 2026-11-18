"""R8.05a: reject mutable action versions and unauthorized GitHub dependencies."""
from pathlib import Path
import re

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
TRUSTED = {
  "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
  "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
  "actions/setup-dotnet": "67a3573c9a986a3f9c594539f4ab511d57bb3ce9",
  "actions/setup-java": "cf277c60eb25467037889841efdb72551f06f6c3",
  "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
  "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
  "actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093",
  "actions/attest": "1e69f48acb82d1966a394da916b4c1698aa569d6"
}
REFERENCE = re.compile(r"^\s*-\s*uses:\s*(\S+)", re.MULTILINE)


def test_every_action_is_pinned_to_vetted_40_char_commit():
    count = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for action in REFERENCE.findall(path.read_text(encoding="utf-8")):
            assert "@" in action, (path, action)
            name, ref = action.split("@", 1)
            assert re.fullmatch(r"[a-f0-9]{40}", ref), (path, action)
            assert TRUSTED.get(name) == ref, (path, action)
            count += 1
    assert count >= 20


def test_mutable_refs_are_unacceptable_even_when_official():
    for name, ref in (
        ("actions/checkout", "v4"),
        ("actions/checkout", "main"),
        ("actions/checkout", "deadbee"),
        ("unknown/action", "a" * 40),
    ):
        assert not (re.fullmatch(r"[a-f0-9]{40}", ref)
                    and TRUSTED.get(name) == ref)
