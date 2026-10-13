"""PreToolUse guards. Each reads the hook JSON on stdin and either stays
silent (no decision) or prints a deny decision.

- push-guard:    no push to protected branches, no force push (any session).
- freeze-guard:  no edits to frozen acceptance tests/test config, to helper-owned
                 state files, or (for subagents) to standards.md / config.toml.
- stage-guard:   a CongoForce agent may only start when state.json expects it.
- context-guard: the test-author never reads tech.md (tests stay blind to the plan).

Guards must never break unrelated work: any unexpected error means "no decision".
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

from .freeze import is_frozen_path
from .paths import CF_DIR, locate_from_path
from .state import AGENT_STAGES
from .util import read_json

HELPER_OWNED = {"state.json", "frozen.json", "checks.json", "baseline.json", "red.json"}
FORCE_FLAGS = {"--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d"}
DEFAULT_PROTECTED = ["main", "master", "develop", "release"]


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": f"CongoForce: {reason}"}}))


# ---------------------------------------------------------------- push guard

def _segments(cmd: str) -> list:
    """Split a shell command into simple commands on ; && || | and newlines (quote-aware)."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|\n")
        lex.whitespace_split = True
        lex.whitespace = " \t\r"
        tokens = list(lex)
    except ValueError:
        tokens = cmd.split()
    segs, cur = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|\n"):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def _git_push_args(seg: list):
    """Arguments after `push` when the segment is a git push, else None."""
    i = 0
    while i < len(seg) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]):
        i += 1  # env assignments
    if i < len(seg) and seg[i] in ("sudo", "command", "env", "exec", "nohup", "time"):
        i += 1
    if i >= len(seg) or Path(seg[i]).name != "git":
        return None
    i += 1
    while i < len(seg) and seg[i].startswith("-"):
        if seg[i] in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(seg):
            i += 2
        else:
            i += 1
    if i < len(seg) and seg[i] == "push":
        return seg[i + 1:]
    return None


def check_push(cmd: str, current_branch: str = "", protected=None) -> str:
    """Return a deny reason, or '' when the command is allowed."""
    protected = protected or DEFAULT_PROTECTED
    for seg in _segments(cmd):
        args = _git_push_args(seg)
        if args is None:
            continue
        positional = []
        for a in args:
            if a in FORCE_FLAGS or a.startswith("--force") or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a):
                return f"force pushes and branch deletions are blocked ({a}). Run it outside Claude Code if you really mean it."
            if a.startswith("-"):
                continue
            positional.append(a)
        refspecs = positional[1:] if positional else []
        for ref in refspecs:
            if ref.startswith("+"):
                return f"force pushes are blocked (+refspec {ref})."
            if ref.startswith(":"):
                return "deleting a remote branch is blocked."
            target = ref.split(":", 1)[1] if ":" in ref else ref
            target = target.replace("refs/heads/", "")
            if target in protected:
                return f"pushes to {target} are blocked; push a feature branch and open a PR."
        if not refspecs and current_branch in protected:
            return f"you are on {current_branch}; pushing it directly is blocked. Push a feature branch and open a PR."
    return ""


def _protected_branches(cwd: str):
    """protected_branches from the layered config of the repo at cwd; None means the defaults."""
    try:
        from . import config as cfgmod
        from .paths import Paths, find_repo_root
        return cfgmod.load(Paths(find_repo_root(cwd))).get("protected_branches") or None
    except Exception:
        return None


def push_guard(data: dict) -> None:
    cmd = (data.get("tool_input") or {}).get("command", "")
    if "push" not in cmd:
        return
    branch = ""
    try:
        import subprocess
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=data.get("cwd") or ".",
                                capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        pass
    reason = check_push(cmd, branch, _protected_branches(data.get("cwd") or "."))
    if reason:
        _deny(reason)


# ---------------------------------------------------------------- freeze guard

def _task_state(root: Path, task: str) -> dict:
    return read_json(Path(root) / CF_DIR / "tasks" / task / "state.json", {}) or {}


def _frozen(root: Path, task: str) -> dict:
    return read_json(Path(root) / CF_DIR / "tasks" / task / "frozen.json", {}) or {}


def check_file_write(path: str, is_subagent: bool) -> str:
    p = Path(path)
    parts = p.parts
    # Helper-owned state files: nobody edits them by hand.
    if CF_DIR in parts and "tasks" in parts and p.name in HELPER_OWNED:
        return f"{p.name} is owned by the congoforce helper; change state with congoforce commands."
    root, task = locate_from_path(path)
    if root is not None:
        st = _task_state(root, task)
        if st.get("frozen"):
            fz = _frozen(root, task)
            rel = Path(*parts[len(Path(root).parts) + 3:]).as_posix()
            if fz and is_frozen_path(rel, fz):
                return f"{rel} is frozen (acceptance test or test config approved at Gate 2). Fix the code, not the test; if the test is wrong, report it and the human can unfreeze."
        rel_in_wt = Path(*parts[len(Path(root).parts) + 3:]).as_posix()
        if is_subagent and rel_in_wt in (f"{CF_DIR}/standards.md", f"{CF_DIR}/config.toml"):
            if not (rel_in_wt.endswith("standards.md") and st.get("class") == "bootstrap" and st.get("stage") == "implement"):
                return "standards.md and config.toml belong to the human; propose changes in your report instead."
        return ""
    if is_subagent and len(parts) >= 2 and parts[-2] == CF_DIR and p.name in ("standards.md", "config.toml"):
        return "standards.md and config.toml belong to the human; propose changes in your report instead."
    return ""


_WRITE_RX = re.compile(r"(>|>>|\btee\b|\bsed\s+-i|\bperl\s+-p?i|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bgit\s+(checkout|restore|rm|mv)\b|\bpatch\b|\bdd\b)")


def check_bash_write(cmd: str, cwd: str) -> str:
    if not _WRITE_RX.search(cmd):
        return ""
    # Find frozen tasks under the repo this command runs in. Inside a task worktree,
    # another task's frozen files only count when the command names them by their
    # worktree path: stacked tasks share file paths but not frozen sets.
    start = Path(cwd or ".")
    root, cur_task = locate_from_path(str(start))
    if cur_task is None:
        # `cd <worktree> && ...` or `git -C <worktree> ...` from the repo root.
        named = set(re.findall(rf"{re.escape(CF_DIR)}/worktrees/([^/\s'\"]+)", cmd))
        if len(named) == 1:
            cur_task = named.pop()
    if root is None:
        cur = start.resolve()
        for cand in [cur, *cur.parents]:
            if (cand / CF_DIR / "tasks").is_dir():
                root = cand
                break
    if root is None:
        return ""
    tasks_dir = Path(root) / CF_DIR / "tasks"
    for d in tasks_dir.iterdir() if tasks_dir.is_dir() else []:
        if not d.is_dir():
            continue
        st = read_json(d / "state.json", {}) or {}
        if not st.get("frozen"):
            continue
        fz = read_json(d / "frozen.json", {}) or {}
        own = cur_task is None or d.name == cur_task
        for rel in fz.get("files", {}):
            if (rel in cmd) if own else (f"worktrees/{d.name}/{rel}" in cmd):
                return f"{rel} is frozen; shell writes to it are blocked too (and would fail the hash check)."
    if re.search(r"\.congoforce/tasks/[^\s]+/(state|frozen|checks|baseline|red)\.json", cmd) and re.search(r"(>|\btee\b|\bsed\s+-i|\brm\b|\bmv\b|\bcp\b)", cmd):
        return "helper-owned state files can only be changed with congoforce commands."
    return ""


def freeze_guard(data: dict) -> None:
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    is_subagent = bool(data.get("agent_id"))
    if tool == "Bash":
        reason = check_bash_write(ti.get("command", ""), data.get("cwd", ""))
    else:
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        reason = check_file_write(path, is_subagent) if path else ""
    if reason:
        _deny(reason)


# ---------------------------------------------------------------- stage guard

def stage_guard(data: dict) -> None:
    ti = data.get("tool_input") or {}
    agent = ti.get("subagent_type", "") or ""
    if not agent.startswith("congoforce:"):
        return
    role = agent.split(":", 1)[1]
    prompt = ti.get("prompt", "") or ""
    m = re.search(r"CONGOFORCE_TASK:\s*(\S+)", prompt)
    if not m:
        _deny(f"{agent} must be started with the prompt from `congoforce next <task>` (it carries CONGOFORCE_TASK).")
        return
    task = m.group(1)
    cwd = Path(data.get("cwd") or ".").resolve()
    root = None
    for cand in [cwd, *cwd.parents]:
        if (cand / CF_DIR / "tasks" / task / "state.json").exists():
            root = cand
            break
    if root is None:
        _deny(f"no CongoForce task {task!r} found from {cwd}.")
        return
    st = _task_state(root, task)
    expected = AGENT_STAGES.get(st.get("stage", ""))
    if st.get("blocked"):
        _deny(f"task {task} is blocked at {st['blocked'].get('stage')}: {st['blocked'].get('reason')}. Ask the human and run `congoforce answer`.")
    elif expected != role:
        _deny(f"task {task} is at stage {st.get('stage')!r}; it expects {('congoforce:' + expected) if expected else 'no agent'}, not {agent}. Run `congoforce next {task}`.")


# ---------------------------------------------------------------- context guard

def context_guard(data: dict) -> None:
    agent = data.get("agent_type", "") or ""
    if not agent.endswith("test-author"):
        return
    path = (data.get("tool_input") or {}).get("file_path", "") or ""
    if f"/{CF_DIR}/tasks/" in path and path.endswith("/tech.md"):
        _deny("the test-author works from interface-contract.md only, so acceptance tests stay independent of the implementation plan.")


GUARDS = {"push-guard": push_guard, "freeze-guard": freeze_guard, "stage-guard": stage_guard, "context-guard": context_guard}


def main(name: str) -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    try:
        GUARDS[name](data)
    except Exception as exc:  # never break unrelated work
        print(f"congoforce {name}: ignored error {exc}", file=sys.stderr)
    return 0
