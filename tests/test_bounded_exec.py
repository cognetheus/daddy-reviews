"""R8.05c.02 real subprocess overload, deadline and token-isolation regressions."""
import base64
from pathlib import Path
import subprocess
import sys
from time import monotonic

import pytest

from daddy_reviews.bounded_exec import run_bounded
from daddy_reviews import test_execution as subject

ROOT = Path(__file__).resolve().parents[1]
REPO = "cognetheus/daddy-reviews"
COMMIT = "a" * 40
WF = REPO + "/.github/workflows/attested-test-execution.yml"


def run_child(source, *, max_output=4096, timeout=4):
    return run_bounded(
        [sys.executable, "-c", source], cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        timeout=timeout, max_output=max_output)


def test_real_subprocess_stdout_flood_has_hard_memory_limit():
    started = monotonic()
    result = run_child("import sys; sys.stdout.buffer.write(b'x' * 1048576)")
    assert not result.output_complete
    assert not result.timeout_expired
    assert len(result.stdout) == 4096
    assert len(result.stderr) <= 4096
    assert result.returncode != 0
    assert monotonic() - started < 4


def test_real_subprocess_stderr_flood_has_hard_memory_limit():
    result = run_child("import sys; sys.stderr.buffer.write(b'E' * 1048576)")
    assert not result.output_complete
    assert len(result.stdout) <= 4096
    assert len(result.stderr) == 4096
    assert result.returncode != 0


def test_real_subprocess_deadline_kills_sleeping_child():
    started = monotonic()
    result = run_child("import time; time.sleep(12)", timeout=1)
    assert result.timeout_expired
    assert result.output_complete is False
    assert result.returncode == 124
    assert monotonic() - started < 4


def test_normal_two_pipe_output_is_complete_and_correct():
    result = run_child(
        "import sys;sys.stdout.buffer.write(b'hello');"
        "sys.stderr.buffer.write(b'warning')"
    )
    assert result.returncode == 0
    assert result.output_complete is True
    assert result.timeout_expired is False
    assert result.stdout == b"hello"
    assert result.stderr == b"warning"


@pytest.mark.parametrize("kwargs", [
    {"timeout": True},
    {"timeout": 0},
    {"timeout": 121},
    {"max_output": 0},
    {"max_output": 65537},
])
def test_invalid_process_budgets_cannot_launch(kwargs):
    arguments = {
        "cwd": ROOT, "env": {"PATH": "/usr/bin:/bin"},
        "timeout": 2, "max_output": 1024,
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        run_bounded([sys.executable, "-c", "pass"], **arguments)


def test_suite_runner_exposes_only_explicit_non_secret_environment(monkeypatch):
    observed = []
    def fake_run(*args, **kwargs):
        observed.append(kwargs)
        return subprocess.CompletedProcess(args, 0, b"5 passed in 0.2s\n", b"")
    monkeypatch.setenv("MY_COMPANY_PRIVATE_API_KEY", "do-not-inherit")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "/dont/import/this")
    monkeypatch.setattr(subject, "run_bounded", fake_run)
    result = subject.capture_fixed_ci_test(
        ROOT, repository=REPO, commit=COMMIT, workflow=WF,
        run_id=42, attempt=1, timeout=60)
    assert result["outcome"] == "passed"
    assert len(observed) == 1
    child_env = observed[0]["env"]
    assert set(child_env) == {
        "PATH", "HOME", "TMPDIR", "LANG", "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE", "PYTHONHASHSEED",
    }
    assert child_env["PYTHONNOUSERSITE"] == "1"
    assert child_env["PYTHONHASHSEED"] == "0"
    assert "PRIVATE" not in str(child_env)
    assert "AWS" not in str(child_env)
    assert "PYTHONPATH" not in child_env
    assert len(observed[0]["timeout"].__str__()) > 0


def test_fixed_suite_marks_bounded_timeout_as_failed_not_attestable(monkeypatch):
    from daddy_reviews.bounded_exec import BoundedResult
    monkeypatch.setattr(subject, "run_bounded",
                        lambda *args, **kwargs: BoundedResult(
                            returncode=124, stdout=b"", stderr=b"timeout",
                            output_complete=False, timeout_expired=True,
                            elapsed_ms=1000))
    record = subject.capture_fixed_ci_test(
        ROOT, repository=REPO, commit=COMMIT,
        workflow=WF, run_id=42, attempt=1)
    assert record["outcome"] == "failed"
    assert record["exit_code"] == 124
    assert record["output_complete"] is False
    assert base64.b64decode(record["stderr_b64"]) == b"timeout"
