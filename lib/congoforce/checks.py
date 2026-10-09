"""Run the standards.md commands in a worktree and read the results.

Used by Baseline, Red check, Verify, and the read-only `check` / `try-tests`
commands agents call to test their own work.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from . import junit, runner

ORDER = ["lint", "typecheck", "build", "test", "e2e"]
_ERR = re.compile(r"(error|✖|✗|\bFAIL\b|\bE\s{2,}|failed)", re.I)


def error_lines(output: str) -> list:
    out = []
    for line in output.splitlines():
        if _ERR.search(line):
            norm = junit.normalise(line)
            if norm:
                out.append(norm)
    return sorted(set(out))[:400]


def _fmt(cmd: str, junit_path: Path, files=None) -> str:
    cmd = cmd.replace("{junit}", shlex.quote(str(junit_path)))
    if "{files}" in cmd:
        cmd = cmd.replace("{files}", " ".join(shlex.quote(str(f)) for f in (files or [])))
    return cmd


def run_tests(wt: Path, std: dict, timeout: int, out_dir: Path, label: str, files=None, kind="test") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    template = std["commands"].get("test_files" if files else kind, "")
    if not template:
        return {"skipped": True, "reason": f"no {('test_files' if files else kind)} command in standards.md", "cases": []}
    junit_path = out_dir / f"junit-{label}.xml"
    if junit_path.exists():
        junit_path.unlink()
    abs_files = [str((Path(wt) / f).resolve()) for f in (files or [])]
    cmd = _fmt(template, junit_path, abs_files)
    res = runner.run(cmd, wt, timeout, log_path=out_dir / f"{label}.log")
    cases = junit.parse(junit_path)
    res.pop("output", None)
    res["junit"] = str(junit_path)
    res["cases"] = [c.to_dict() for c in cases]
    res["summary"] = junit.summarise(cases)
    res["no_report"] = not cases
    return res


def run_command(wt: Path, std: dict, name: str, timeout: int, out_dir: Path, label: str) -> dict:
    cmd = std["commands"].get(name, "")
    if not cmd:
        return {"skipped": True}
    res = runner.run(cmd, wt, timeout, log_path=out_dir / f"{label}-{name}.log")
    res["errors"] = error_lines(res.pop("output", ""))
    return res


def run_suite(wt: Path, std: dict, cfg: dict, out_dir: Path, label: str) -> dict:
    timeout = int(cfg.get("command_timeout", 600))
    result = {"commands": {}, "tests": None}
    for name in ORDER:
        if name == "e2e" and not cfg.get("e2e"):
            continue
        if name in ("test", "e2e"):
            res = run_tests(wt, std, timeout, out_dir, f"{label}-{name}", kind=name)
            if name == "test":
                result["tests"] = res
            else:
                result["commands"]["e2e"] = res
        else:
            result["commands"][name] = run_command(wt, std, name, timeout, out_dir, label)
    return result


def case_map(test_result) -> dict:
    if not test_result or test_result.get("skipped"):
        return {}
    return {c["id"]: c for c in test_result.get("cases", [])}


def short(result: dict) -> str:
    """One-screen summary for agents calling `congoforce check`."""
    lines = []
    for name, res in result["commands"].items():
        if res.get("skipped"):
            continue
        state = "TIMED OUT" if res.get("timed_out") else ("ok" if res.get("ok") else f"FAILED (exit {res.get('exit')})")
        lines.append(f"{name}: {state}")
        if not res.get("ok"):
            lines.append("  " + "\n  ".join(res.get("tail", "").splitlines()[-25:]))
    t = result.get("tests")
    if t and not t.get("skipped"):
        s = t.get("summary", {})
        lines.append(f"test: {s.get('passed', 0)} passed, {s.get('failed', 0) + s.get('error', 0)} failed, {s.get('skipped', 0)} skipped"
                     + (" (TIMED OUT)" if t.get("timed_out") else "") + (" (no JUnit report produced!)" if t.get("no_report") else ""))
        for c in t.get("cases", []):
            if c["status"] in ("failed", "error"):
                lines.append(f"  ✗ {c['id']}: {junit.normalise(c['message'])}")
        if t.get("no_report"):
            lines.append("  " + "\n  ".join(t.get("tail", "").splitlines()[-25:]))
    elif t:
        lines.append(f"test: skipped ({t.get('reason')})")
    return "\n".join(lines)
