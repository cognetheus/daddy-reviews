"""R8.06a: authenticated GET-only live PR verification against adversarial API inputs.

All Github API responses in this file are synthetic fixtures. No actual PR
or human-quality result is fabricated.
"""
import copy
import json
from pathlib import Path

import pytest

from daddy_reviews import pr_pilot as subject
from daddy_reviews.bounded_exec import BoundedResult


REPO="cognetheus/daddy-reviews"
REPO_ID=1431087545
HEAD="a"*40
BASE="b"*40


def pr():
    return {
        "number":17,"state":"open","changed_files":1,
        "head":{"sha":HEAD}, "base":{"sha":BASE,
            "repo":{"id":REPO_ID,"full_name":REPO}}
    }


def files():
    return [{"filename":"app.py","status":"modified",
             "additions":1,"deletions":1,"changes":2,
             "patch":"@@ -1 +1 @@\n-old\n+new\n"}]


def setup_live(monkeypatch, *, pr_before=None, file_data=None, pr_after=None):
    calls=[]
    first=pr() if pr_before is None else pr_before
    batch=files() if file_data is None else file_data
    last=copy.deepcopy(first) if pr_after is None else pr_after
    payloads=[first,batch,last]
    monkeypatch.setattr(subject,"pinned_local_head",lambda root: HEAD)
    monkeypatch.setattr(subject,"_verified_executable",lambda path,sha: Path(path))
    monkeypatch.setattr(subject,"review_patch",
                        lambda root,patch: {"findings":[{"rule":"foo","path":"app.py"}]})
    def fake_run(argv, **kwargs):
        calls.append((argv,kwargs))
        value=payloads[len(calls)-1]
        return BoundedResult(
            returncode=0,stdout=json.dumps(value).encode(),
            stderr=b"",output_complete=True,timeout_expired=False,elapsed_ms=3)
    monkeypatch.setattr(subject,"run_bounded",fake_run)
    return calls


def call(root):
    return subject.capture_live_pr(
        root=root,repository=REPO,repository_id=REPO_ID,
        number=17,expected_head=HEAD,token="read-only-test-token-123456",
        gh_binary=Path("/usr/bin/gh"),gh_binary_sha256="f"*64)


def test_real_source_pinned_api_protocol_is_read_only_and_source_free(monkeypatch,tmp_path):
    calls=setup_live(monkeypatch)
    result=call(tmp_path)
    safe=result["summary"]
    private=result["private"]
    assert safe["format"]==subject.FORMAT
    assert safe["pr_number"]==17 and safe["head_commit"]==HEAD
    assert safe["base_commit"]==BASE
    assert safe["changed_file_count"]==1
    assert safe["added_lines"]==1 and safe["deleted_lines"]==1
    assert safe["candidate_findings"]==1
    assert safe["model_used"] is False
    assert safe["verified_defects"]==0
    assert safe["pr_comments_posted"]==0
    assert safe["merge_action"]=="none"
    assert safe["production_approval_granted"] is False
    assert safe["human_findings_verified"] is False
    assert "app.py" not in json.dumps(safe)
    assert "foo" not in json.dumps(safe)
    assert private["review_packet"]["findings"][0]["rule"]=="foo"
    assert len(calls)==3
    assert [c[0][-1] for c in calls]==[
        f"/repos/{REPO}/pulls/17",
        f"/repos/{REPO}/pulls/17/files?per_page=10&page=1",
        f"/repos/{REPO}/pulls/17",
    ]
    for argv,kwargs in calls:
        assert argv[1:4]==["api","--method","GET"]
        assert "POST" not in str(argv)
        assert "read-only-test-token-123456" not in str(argv)
        assert kwargs["env"]["GH_TOKEN"]=="read-only-test-token-123456"
        assert kwargs["env"]["GH_CONFIG_DIR"]==kwargs["env"]["HOME"]
        assert kwargs["max_output"]==65536
        assert kwargs["timeout"]==20


def test_source_HEAD_mismatch_cannot_start_API(monkeypatch,tmp_path):
    monkeypatch.setattr(subject,"pinned_local_head",lambda root: "9"*40)
    with pytest.raises(subject.PilotError,match="HEAD"):
        call(tmp_path)


@pytest.mark.parametrize("mod",[
    lambda p: p.update(state="closed"),
    lambda p: p.update(number=99),
    lambda p: p.update(changed_files=41),
    lambda p: p.update(changed_files=0),
    lambda p: p["head"].update(sha="c"*40),
    lambda p: p["base"]["repo"].update(id=1),
    lambda p: p["base"]["repo"].update(full_name="other/repo"),
])
def test_wrong_pr_identity_or_changed_scope_rejected(monkeypatch,tmp_path,mod):
    metadata=pr()
    mod(metadata)
    setup_live(monkeypatch,pr_before=metadata)
    with pytest.raises(subject.PilotError):
        call(tmp_path)


def test_pr_force_push_between_file_download_and_final_query_refused(monkeypatch,tmp_path):
    last=pr()
    last["head"]["sha"]="f"*40
    setup_live(monkeypatch,pr_after=last)
    with pytest.raises(subject.PilotError,match="mismatched"):
        call(tmp_path)


@pytest.mark.parametrize("mod",[
    lambda x: x.update(patch=None),
    lambda x: x.update(patch="@@ -1 +1 @@\n-old\n"),
    lambda x: x.update(patch="@@ -1 +1 @@\n-old\n+new\n",additions=2),
    lambda x: x.update(filename="../secrets.py"),
    lambda x: x.update(filename="app.py\nmalicious"),
    lambda x: x.update(filename="/etc/passwd"),
    lambda x: x.update(status="copied"),
    lambda x: x.update(additions=True),
])
def test_missing_truncated_malicious_paths_and_counts_abstain(monkeypatch,tmp_path,mod):
    items=files()
    mod(items[0])
    setup_live(monkeypatch,file_data=items)
    with pytest.raises(subject.PilotError):
        call(tmp_path)


def test_more_than_one_fake_diff_header_inside_api_patch_is_rejected():
    evil=files()
    evil[0]["patch"]+=(
        "diff --git a/evil.py b/evil.py\n"
        "--- a/evil.py\n+++ b/evil.py\n@@ -1 +1 @@\n-a\n+b\n")
    with pytest.raises(subject.PilotError):
        subject._patch_from_files(evil)


def test_private_report_is_owner_only_nonoverwrite_and_absent_from_public_summary(
        monkeypatch,tmp_path):
    setup_live(monkeypatch)
    data=call(tmp_path)
    target=tmp_path/"private.json"
    receipt=subject.write_private_pilot_report(target,data["private"])
    assert receipt["private_evidence_saved"] is True
    assert len(receipt["private_evidence_sha256"])==64
    assert target.stat().st_mode & 0o077 == 0
    assert json.loads(target.read_text())["format"]==subject.PRIVATE_FORMAT
    with pytest.raises((subject.PilotError,ValueError)):
        subject.write_private_pilot_report(target,data["private"])
