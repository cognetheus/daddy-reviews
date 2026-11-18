"""R8.04k: GitHub-hosted registration/reviewer commitment chronology regressions.

Synthetic runs and test-only signed labels; only live API fetching makes an
observed GitHub timestamp externally authenticated in production.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest

from daddy_reviews import cli
from daddy_reviews.human_attestation import HumanVerificationError, sha256_json
from daddy_reviews.study_github_chronology import (
    FORMAT, MANIFEST, RUN_NAME, WORKFLOW_PATH,
    create_study_github_enrollment, write_study_enrollment,
    reviewer_receipt_sha256, verify_study_anchor_responses,
    verify_live_study_anchors,
)
from test_study_protocol import material


REPO = "cognetheus/daddy-reviews"
REPO_ID = 81236124
SOURCE_SHA = "a" * 40
WF_ID = 673329901
REG_DATE = "2026-11-09T13:00:00Z"
REVIEW_DATE = "2026-11-11T17:00:00Z"


def anchor_manifest(s, *, reviewers=True):
    pair = s["plan"]["frozen_reviewer_ids"]
    enrollment = create_study_github_enrollment(
        registration=s["registration"],
        expected_registration_sha256=s["registration_hash"],
        registrar_actor_id=101,
        reviewer_actor_ids={pair[0]:102, pair[1]:103},
        anchor_repository=REPO,anchor_repository_id=REPO_ID,
        workflow_id=WF_ID,head_branch="main")
    return {
        "format": MANIFEST,
        "enrollment":enrollment,
        "anchor_repository": REPO,
        "anchor_repository_id": REPO_ID,
        "workflow_id": WF_ID,
        "head_branch": "main",
        "registration": {
            "run_id": 9178, "actor_id": 101, "head_sha": SOURCE_SHA,
        },
        "reviewers": [
            {"reviewer_id": pair[0], "run_id": 9179,
             "actor_id": 102, "head_sha": SOURCE_SHA},
            {"reviewer_id": pair[1], "run_id": 9180,
             "actor_id": 103, "head_sha": SOURCE_SHA},
        ] if reviewers else [],
    }


def run_record(manifest, entry, *, kind, study_sha, payload, created):
    return {
        "id": entry["run_id"], "run_attempt": 1,
        "status": "completed", "conclusion": "success",
        "event": "workflow_dispatch",
        "workflow_id": manifest["workflow_id"],
        "head_sha": entry["head_sha"],
        "head_branch": manifest["head_branch"],
        "path": WORKFLOW_PATH + "@main",
        "display_title": f"{RUN_NAME} | {kind} | {study_sha} | {payload}",
        "repository": {
            "id": manifest["anchor_repository_id"],
            "full_name": manifest["anchor_repository"],
        },
        "head_repository": {"id": manifest["anchor_repository_id"]},
        "actor": {"id": entry["actor_id"], "type": "User"},
        "triggering_actor": {"id": entry["actor_id"], "type": "User"},
        "created_at": created,
    }


def server_runs(s, manifest, *, reviewers=True):
    sha = s["registration_hash"]
    runs = [
        run_record(manifest, manifest["registration"], kind="registration",
                   study_sha=sha, payload=sha256_json(manifest["enrollment"]), created=REG_DATE)
    ]
    if reviewers:
        for entry in manifest["reviewers"]:
            payload = reviewer_receipt_sha256(
                s["plan"], s["labels"], entry["reviewer_id"])
            runs.append(run_record(
                manifest, entry, kind="reviewer", study_sha=sha,
                payload=payload, created=REVIEW_DATE))
    return runs


def check(s, manifest=None, runs=None, *, reviewers=True):
    m = manifest if manifest is not None else anchor_manifest(s, reviewers=reviewers)
    rr = runs if runs is not None else server_runs(s, m, reviewers=reviewers)
    return verify_study_anchor_responses(
        registration=s["registration"], labels=s["labels"] if reviewers else [],
        anchor_manifest=m, runs=rr,
        expected_registration_sha256=s["registration_hash"],
        require_reviewers=reviewers)


def test_two_independent_github_accounts_and_timestamped_receipts_bind_study(tmp_path):
    s = material(tmp_path)
    result = check(s)
    assert result["format"] == FORMAT
    assert result["status"] == "github_registration_and_two_receipts_matched"
    assert result["github_hosted_chronological_order_verified"] is True
    assert result["externally_authenticated_GitHub_run_metadata"] is False
    assert result["defect_truth_proven"] is False
    assert result["human_identity_independently_proven"] is False
    assert result["github_publication"] == result["merge_action"] == "none"
    assert [x["run_id"] for x in result["server_observed_commitments"]] == [
        9178, 9179, 9180,
    ]
    assert len({x["actor_numeric_id"] for x in
                result["server_observed_commitments"]}) == 3


def test_registration_can_be_verified_before_labels_exist(tmp_path):
    s = material(tmp_path)
    result = check(s, reviewers=False)
    assert result["status"] == "github_registration_anchor_matched"
    assert result["github_hosted_chronological_order_verified"] is False
    assert len(result["server_observed_commitments"]) == 1


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(run_attempt=2),
    lambda x: x.update(status="in_progress"),
    lambda x: x.update(conclusion="failure"),
    lambda x: x.update(event="push"),
    lambda x: x.update(path=".github/workflows/evil.yml@main"),
    lambda x: x.update(display_title="changed-title"),
    lambda x: x.update(head_sha="b" * 40),
    lambda x: x.update(head_branch="malicious"),
    lambda x: x.update(workflow_id=11),
    lambda x: x.update(actor={"id": 999, "type": "User"}),
    lambda x: x.update(triggering_actor={"id": 999, "type": "User"}),
    lambda x: x.update(actor={"id": 101, "type": "Bot"}),
    lambda x: x["repository"].update(id=1),
    lambda x: x["head_repository"].update(id=1),
    lambda x: x.update(created_at="2030-11-09T13:00:00Z"),
])
def test_forged_server_run_status_identity_and_commitment_fail_closed(tmp_path, mutate):
    s = material(tmp_path)
    m = anchor_manifest(s)
    records = server_runs(s, m)
    mutate(records[0])
    with pytest.raises(HumanVerificationError):
        check(s, m, records)


@pytest.mark.parametrize("tamper", [
    lambda m: m["reviewers"][0].update(actor_id=101),
    lambda m: m["reviewers"][0].update(actor_id=103),
    lambda m: m["reviewers"][0].update(run_id=9178),
    lambda m: m["reviewers"][0].update(reviewer_id="not-enrolled"),
    lambda m: m.update(workflow_id=True),
    lambda m: m["registration"].update(run_id=True),
])
def test_manifest_requires_distinct_immutable_actor_and_run_id(tmp_path, tamper):
    s = material(tmp_path)
    m = anchor_manifest(s)
    records = server_runs(s, m)
    tamper(m)
    with pytest.raises(HumanVerificationError):
        check(s, m, records)


def test_observation_receipts_must_follow_registration_and_label_signing(tmp_path):
    s = material(tmp_path)
    m = anchor_manifest(s)
    records = server_runs(s, m)
    records[1]["created_at"] = "2026-11-09T12:00:00Z"
    with pytest.raises(HumanVerificationError):
        check(s, m, records)
    records = server_runs(s, m)
    records[1]["created_at"] = "2026-11-10T12:00:00Z"
    with pytest.raises(HumanVerificationError):
        check(s, m, records)


def test_mutated_signed_label_bundle_cannot_reuse_github_receipt(tmp_path):
    s = material(tmp_path)
    m = anchor_manifest(s)
    records = server_runs(s, m)
    mutated = copy.deepcopy(s["labels"])
    mutated[0]["rationale"] = "altered later"
    with pytest.raises(HumanVerificationError):
        verify_study_anchor_responses(
            registration=s["registration"],labels=mutated,
            anchor_manifest=m,runs=records,
            expected_registration_sha256=s["registration_hash"],
            require_reviewers=True)


def test_unexpected_extra_reviewer_label_rejected(tmp_path):
    s = material(tmp_path)
    m = anchor_manifest(s)
    records = server_runs(s, m)
    extra = copy.deepcopy(s["labels"][0])
    extra["reviewer_id"] = "stranger"
    with pytest.raises(HumanVerificationError):
        verify_study_anchor_responses(
            registration=s["registration"],labels=[*s["labels"],extra],
            anchor_manifest=m,runs=records,
            expected_registration_sha256=s["registration_hash"],
            require_reviewers=True)


def test_live_gh_api_is_read_only_three_exact_run_ids_and_sealed_token(tmp_path,monkeypatch):
    s = material(tmp_path)
    m = anchor_manifest(s)
    runs = server_runs(s, m)
    observed = []
    from daddy_reviews import study_github_chronology as subject
    monkeypatch.setattr(subject, "_verified_executable", lambda p,d: Path(p))
    def fake_run(argv, **opts):
        observed.append((argv, opts))
        return subprocess.CompletedProcess(argv, 0, json.dumps(
            runs[len(observed)-1]).encode(), b"")
    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    token = "read-only-test-token-123456789"
    result = verify_live_study_anchors(
        gh_binary=Path("/usr/bin/gh"),gh_binary_sha256="a"*64,
        api_token=token,registration=s["registration"],
        labels=s["labels"],anchor_manifest=m,
        expected_registration_sha256=s["registration_hash"],
        require_reviewers=True)
    assert result["externally_authenticated_GitHub_run_metadata"] is True
    assert len(observed) == 3
    for idx,(argv, opts) in enumerate(observed):
        assert argv[-1] == f"/repos/{REPO}/actions/runs/{9178+idx}"
        assert argv[1:4] == ["api","--method","GET"]
        assert token not in str(argv)
        assert opts["env"]["GH_TOKEN"] == token
        assert opts["env"]["GH_CONFIG_DIR"] == opts["env"]["HOME"]
        assert opts["env"]["GH_HOST"] == "github.com"
        assert opts["check"] is False


def test_missing_explicit_token_and_failed_api_never_authenticates(tmp_path,monkeypatch):
    s = material(tmp_path)
    m = anchor_manifest(s)
    from daddy_reviews import study_github_chronology as subject
    observed = []
    monkeypatch.setattr(subject, "_verified_executable", lambda p,d: Path(p))
    monkeypatch.setattr(subject.subprocess, "run",
                        lambda args,**kw: observed.append(args) or
                        subprocess.CompletedProcess(args,1,b"{}",b"unauthorized"))
    args = dict(
        gh_binary=Path("/usr/bin/gh"),gh_binary_sha256="a"*64,
        registration=s["registration"],labels=s["labels"],anchor_manifest=m,
        expected_registration_sha256=s["registration_hash"],
        require_reviewers=True)
    with pytest.raises(HumanVerificationError):
        verify_live_study_anchors(**args,api_token=None)
    assert not observed
    with pytest.raises(HumanVerificationError):
        verify_live_study_anchors(**args,api_token="operator-test-token-123456")


def test_standalone_reviewer_digest_cli_never_claims_signatures_verified(
        tmp_path,capsys):
    s = material(tmp_path)
    reg = tmp_path/"registration.json"
    labels = tmp_path/"labels.json"
    reg.write_text(json.dumps(s["registration"]))
    labels.write_text(json.dumps(s["labels"]))
    person = s["plan"]["frozen_reviewer_ids"][0]
    cli.main([
        "study-review-receipt","--root",str(tmp_path),
        "--study-registration-file",str(reg),
        "--study-registration-sha256",s["registration_hash"],
        "--label-attestations-file",str(labels),
        "--study-reviewer-id",person,
    ])
    result=json.loads(capsys.readouterr().out)
    assert result["reviewer_id"] == person
    assert result["payload_sha256"] == reviewer_receipt_sha256(
        s["plan"],s["labels"],person)
    assert result["signatures_verified_by_this_command"] is False
    assert result["github_anchored"] is False


def test_registration_live_verification_cli_does_not_need_human_results(
        tmp_path,monkeypatch,capsys):
    s=material(tmp_path)
    reg=tmp_path/"reg.json"
    manifest=tmp_path/"anchor.json"
    reg.write_text(json.dumps(s["registration"]))
    manifest.write_text(json.dumps(anchor_manifest(s,reviewers=False)))
    monkeypatch.setenv("GH_TOKEN","operator-github-read-token-00001")
    invoked=[]
    def verify(**kwargs):
        invoked.append(kwargs)
        return {"status":"github_registration_anchor_matched",
                "externally_authenticated_GitHub_run_metadata":True,
                "github_publication":"none","merge_action":"none"}
    monkeypatch.setattr(cli,"verify_live_study_anchors",verify)
    cli.main([
        "study-anchor-verify","--root",str(tmp_path),
        "--study-registration-file",str(reg),
        "--study-registration-sha256",s["registration_hash"],
        "--study-anchor-manifest-file",str(manifest),
        "--gh-binary","/usr/bin/gh","--gh-binary-sha256","a"*64,
    ])
    result=json.loads(capsys.readouterr().out)
    assert result["status"]=="github_registration_anchor_matched"
    assert invoked[0]["require_reviewers"] is False
    assert invoked[0]["api_token"] == "operator-github-read-token-00001"


def _audit_cli_args(tmp_path,s):
    folder = tmp_path / "audit-private"
    folder.mkdir(mode=0o700)
    files = {
        "registration": folder / "registration.json",
        "blind": folder / "blind.json",
        "ledger": folder / "ledger.json",
        "labels": folder / "labels.json",
        "registrar": folder / "registrar.json",
        "adjudicator": folder / "adjudicator.json",
        "model": folder / "report.json",
        "manifest": folder / "anchors.json",
        "evidence": folder / "evidence",
    }
    files["evidence"].mkdir(mode=0o700)
    objects = {
        "registration": s["registration"],
        "blind": s["frame"]["blind_packet"],
        "ledger": s["frame"]["private_ledger"],
        "labels": s["labels"],
        "registrar": s["registrar_keys"],
        "adjudicator": s["adjudicator_keys"],
        "model": s["opts"]["report"],
        "manifest": anchor_manifest(s),
    }
    for name,obj in objects.items():
        files[name].write_text(json.dumps(obj))
    files["registrar"].chmod(0o600)
    files["adjudicator"].chmod(0o600)
    for digest,payload in s["evidence"].items():
        (files["evidence"]/digest).write_bytes(payload)
    o=s["opts"]
    return [
        "study-audit","--root",str(s["root"]),
        "--attestation-repo",o["repository"],
        "--attestation-repo-id",str(o["repository_id"]),
        "--base",o["base_commit"],"--head",o["head_commit"],
        "--real-sample-seed",o["seed"],
        "--real-sample-max-cases",str(o["max_cases"]),
        "--real-model-report",str(files["model"]),
        "--real-blind-file",str(files["blind"]),
        "--real-private-file",str(files["ledger"]),
        "--study-registration-file",str(files["registration"]),
        "--study-registration-sha256",s["registration_hash"],
        "--study-registrar-keys-file",str(files["registrar"]),
        "--label-attestations-file",str(files["labels"]),
        "--label-trust-keys-file",str(files["adjudicator"]),
        "--label-evidence-dir",str(files["evidence"]),
        "--study-anchor-manifest-file",str(files["manifest"]),
        "--gh-binary","/usr/bin/gh",
        "--gh-binary-sha256","a"*64,
        "--require-live-study-anchors",
    ]


def test_combined_human_signatures_and_external_github_time_gate(
        tmp_path,monkeypatch,capsys):
    s=material(tmp_path)
    args=_audit_cli_args(tmp_path,s)
    monkeypatch.setenv("GH_TOKEN","read-only-audit-token-12345678")
    def fake_verify(**kwargs):
        assert kwargs["require_reviewers"] is True
        assert len(kwargs["labels"])==2*len(s["plan"]["cases"])
        assert kwargs["api_token"]=="read-only-audit-token-12345678"
        return {
            "status":"github_registration_and_two_receipts_matched",
            "github_hosted_chronological_order_verified":True,
            "externally_authenticated_GitHub_run_metadata":True,
            "defect_truth_proven":False,
            "github_publication":"none","merge_action":"none",
        }
    monkeypatch.setattr(cli,"verify_live_study_anchors",fake_verify)
    cli.main(args)
    result=json.loads(capsys.readouterr().out)
    assert result["preregistration_chronology_independently_proven"] is True
    assert result["external_chronology"]["status"]=="github_registration_and_two_receipts_matched"
    assert result["sample_observations"]["biased_stratified_line_sample"]
    assert result["factual_defect_truth_proven"] is False
    assert result["promotion_eligible"] is False


def test_combined_study_audit_fails_closed_on_missing_github_chronology(
        tmp_path,monkeypatch,capsys):
    s=material(tmp_path)
    args=_audit_cli_args(tmp_path,s)
    monkeypatch.delenv("GH_TOKEN",raising=False)
    def no_github(**kwargs):
        raise HumanVerificationError("Cannot verify GitHub-hosted preregistration")
    monkeypatch.setattr(cli,"verify_live_study_anchors",no_github)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code==2
    assert "Cannot verify GitHub" in capsys.readouterr().err


def test_precommitted_enrollment_freezes_github_accounts_before_run(tmp_path):
    s=material(tmp_path)
    manifest=anchor_manifest(s)
    enrollment=manifest["enrollment"]
    assert enrollment["registrar_actor_id"]==101
    assert [x["actor_id"] for x in enrollment["reviewer_actors"]]==[102,103]
    assert enrollment["workflow_id"]==WF_ID
    assert enrollment["anchor_repository"]==REPO
    assert enrollment["study_registration_sha256"]==s["registration_hash"]
    report=check(s,manifest)
    assert report["server_observed_commitments"][0]["payload_sha256"]==sha256_json(enrollment)


@pytest.mark.parametrize("modified",[
    lambda m: m["enrollment"]["reviewer_actors"][0].update(actor_id=888),
    lambda m: m["enrollment"].update(registrar_actor_id=777),
    lambda m: m["enrollment"].update(anchor_repository="attacker/repo"),
    lambda m: m["enrollment"].update(workflow_id=5),
    lambda m: m["enrollment"].update(head_branch="evil"),
    lambda m: m["enrollment"].update(study_registration_sha256="0"*64),
])
def test_posthoc_enrollment_identity_changes_fail_closed(tmp_path,modified):
    s=material(tmp_path)
    manifest=anchor_manifest(s)
    runs=server_runs(s,manifest)
    modified(manifest)
    with pytest.raises(HumanVerificationError):
        check(s,manifest,runs)


def test_enrollment_cli_saves_owner_only_digest_without_github_write(tmp_path,capsys):
    s=material(tmp_path)
    folder=tmp_path/"private-enrollment"
    folder.mkdir(mode=0o700)
    registration=folder/"registration.json"
    enrollment=folder/"enrollment.json"
    registration.write_text(json.dumps(s["registration"]))
    pair=s["plan"]["frozen_reviewer_ids"]
    cli.main([
        "study-enrollment","--root",str(tmp_path),
        "--study-registration-file",str(registration),
        "--study-registration-sha256",s["registration_hash"],
        "--study-anchor-repository",REPO,
        "--study-anchor-repository-id",str(REPO_ID),
        "--study-anchor-workflow-id",str(WF_ID),
        "--study-anchor-branch","main",
        "--study-registrar-actor-id","101",
        "--study-reviewer-actors",f"{pair[0]}:102,{pair[1]}:103",
        "--study-enrollment-output",str(enrollment),
    ])
    summary=json.loads(capsys.readouterr().out)
    assert summary["status"]=="enrollment_digest_ready_not_github_anchored"
    assert summary["enrollment_sha256"]==sha256_json(anchor_manifest(s)["enrollment"])
    assert summary["registered_on_github"] is False
    assert enrollment.stat().st_mode & 0o077 == 0
    with pytest.raises(HumanVerificationError):
        write_study_enrollment(anchor_manifest(s)["enrollment"],enrollment)
