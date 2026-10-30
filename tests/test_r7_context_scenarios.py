"""R7.01 CLI and synthetic-fixture contract regression tests."""
import json
from pathlib import Path

import pytest

from daddy_reviews.cli import main
from daddy_reviews.semantic_contracts import capture_worktree, bound_span, context_bundle


def test_snapshot_cli_round_trip_and_stale_exit(tmp_path, capsys):
    (tmp_path / "main.py").write_text("answer = 42\n", encoding="utf-8")
    main(["snapshot", "--root", str(tmp_path)])
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["complete"] is True
    outfile = tmp_path / "snapshot.json"
    outfile.write_text(json.dumps(snapshot), encoding="utf-8")
    main(["snapshot-verify", "--root", str(tmp_path), "--snapshot-file", str(outfile)])
    checked = json.loads(capsys.readouterr().out)
    assert checked["status"] == "fresh"
    (tmp_path / "main.py").write_text("answer = 43\n", encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main(["snapshot-verify", "--root", str(tmp_path),
              "--snapshot-file", str(outfile)])
    assert failure.value.code == 2
    stale = json.loads(capsys.readouterr().out)
    assert stale["modified"] == ["main.py"]
    assert stale["verified"] is False


def test_synthetic_context_scenarios_have_valid_grounding(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "evals" / "r7_context_scenarios.json"
    corpus = json.loads(fixture.read_text(encoding="utf-8"))
    assert corpus["format"] == "daddy-reviews-r7-synthetic-scenarios-v1"
    assert corpus["label_status"] == "synthetic_specification_not_human_verified"
    assert len(corpus["cases"]) >= 4
    ids = set()
    for case in corpus["cases"]:
        assert case["id"] not in ids
        ids.add(case["id"])
        root = tmp_path / case["id"]
        root.mkdir()
        for path, source in case["files"].items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        snapshot = capture_worktree(root)
        assert snapshot["complete"]
        symbol_file = case["query"]["path"]
        assert case["query"]["symbol"] in case["files"][symbol_file]
        source_file = {f["path"]: f for f in snapshot["files"]}
        for reference in case["expected_reference_candidates"]:
            item = source_file[reference["path"]]
            location = bound_span(snapshot, reference["path"], reference["line"],
                                  reference["line"], "manual", "candidate")
            assert location.source_sha256 == item["sha256"]
            assert context_bundle(snapshot, excerpts=[])["snapshot_id"] == snapshot["snapshot_id"]
        for path in case["expected_test_candidates"]:
            assert path in source_file
        for abstention in case["expected_abstentions"]:
            assert abstention["path"] in source_file
