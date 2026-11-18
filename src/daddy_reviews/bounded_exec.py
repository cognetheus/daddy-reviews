"""R8.05c.02 — bounded output/deadline subprocess for trusted fixed-suite CI.

Do not use as arbitrary untrusted code sandbox. It runs a preselected test
command inside an unprivileged GitHub-hosted job. It prevents unbounded
PIPE-memory growth and terminates the process group on timeout/output flood.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import selectors
import signal
import subprocess
from time import monotonic


@dataclass(frozen=True)
class BoundedResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    output_complete: bool
    timeout_expired: bool
    elapsed_ms: int


def _stop_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def run_bounded(argv: list[str], *, cwd: Path, env: dict[str, str],
                timeout: int, max_output: int) -> BoundedResult:
    """Drain both pipes without buffering more than max_output per pipe.

    - Fixed argv only; no shell, shell expansion or inherited stdin.
    - Exact monotonic deadline and output-size cap; fail closed on overrun.
    - Kill subprocess group on timeout/flood, close pipes and reap child.
    """
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 12
            or any(not isinstance(arg, str) or not arg or "\0" in arg
                   for arg in argv)
            or not isinstance(cwd, Path) or not cwd.is_dir()
            or not isinstance(env, dict)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in env.items())
            or type(timeout) is not int or not 1 <= timeout <= 120
            or type(max_output) is not int or not 1 <= max_output <= 65536):
        raise ValueError("Invalid bounded subprocess invocation")
    started = monotonic()
    deadline = started + timeout
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, start_new_session=(os.name == "posix"))
    except OSError:
        raise
    collected = {process.stdout: bytearray(), process.stderr: bytearray()}
    output_complete = True
    timed_out = False
    try:
        with selectors.DefaultSelector() as poller:
            for stream in (process.stdout, process.stderr):
                if stream is None:
                    raise OSError("Missing captured child output pipe")
                os.set_blocking(stream.fileno(), False)
                poller.register(stream, selectors.EVENT_READ)
            while poller.get_map():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    timed_out = True
                    output_complete = False
                    break
                for key, _ in poller.select(min(remaining, 0.2)):
                    stream = key.fileobj
                    try:
                        data = os.read(stream.fileno(), 4096)
                    except BlockingIOError:
                        continue
                    if not data:
                        poller.unregister(stream)
                        stream.close()
                        continue
                    bounded = collected[stream]
                    room = max_output - len(bounded)
                    if len(data) > room:
                        bounded.extend(data[:max(0, room)])
                        output_complete = False
                        break
                    bounded.extend(data)
                if not output_complete:
                    break
        if output_complete:
            try:
                process.wait(timeout=max(0, deadline - monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                output_complete = False
        if not output_complete:
            _stop_group(process)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _stop_group(process)
                raise OSError("Test child refused termination")
    finally:
        if process.poll() is None:
            _stop_group(process)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    return BoundedResult(
        returncode=124 if timed_out else int(process.returncode if process.returncode is not None else 125),
        stdout=bytes(collected[process.stdout]),
        stderr=bytes(collected[process.stderr]),
        output_complete=output_complete,
        timeout_expired=timed_out,
        elapsed_ms=round((monotonic() - started) * 1000),
    )
