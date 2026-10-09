"""Run shell commands with a hard time limit.

Every command the helper runs goes through here, so a hung test runner or
install becomes a timed-out failure with its own signature instead of a
stalled session.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from .util import tail


def run(cmd: str, cwd: Path, timeout: int, log_path: Path = None, env: dict = None) -> dict:
    started = time.time()
    full_env = dict(os.environ)
    full_env.update(env or {})
    full_env.setdefault("CI", "1")  # keeps watch modes and interactive prompts off
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        env=full_env,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = proc.communicate()
    duration = round(time.time() - started, 1)
    out = out or ""
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(f"$ {cmd}\n(cwd {cwd}, exit {proc.returncode}, {duration}s{', TIMED OUT' if timed_out else ''})\n\n{out}")
    return {
        "command": cmd,
        "exit": None if timed_out else proc.returncode,
        "ok": (not timed_out) and proc.returncode == 0,
        "timed_out": timed_out,
        "duration": duration,
        "output": out,
        "tail": tail(out, 40),
    }
