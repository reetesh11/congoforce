"""Task state: the only writer of state.json.

Stage names are a fixed enum and timestamps come from the clock. The
orchestrator asks `next` what to do, does it, and reports back through
`complete` (agent work) or `gate` (human decisions); helper stages run via
`advance`. Nothing else moves a task.
"""

from __future__ import annotations

from pathlib import Path

from .util import CFError, now, read_json, write_json

AGENT_STAGES = {
    "requirements": "requirements",
    "product_spec": "product-spec",
    "tech_spec": "tech-spec",
    "test_author": "test-author",
    "implement": "implementer",
    "review": "verifier",
}
HELPER_STAGES = {"prepare", "red_check", "freeze", "verify", "decide", "ship_prepare", "ship", "post_pr"}
GATE_STAGES = {"standards", "gate1", "split", "gate2", "ship_confirm", "escalated"}
ORCHESTRATOR_STAGES = {"map_summaries", "post_pr_skills", "retro"}
TERMINAL = {"done", "stopped"}
ALL_STAGES = set(AGENT_STAGES) | HELPER_STAGES | GATE_STAGES | ORCHESTRATOR_STAGES | TERMINAL

CLASSES = ("feature", "task", "bug", "bootstrap")
SIZES = ("small", "medium", "large")


def new_state(task: str, source: str, overrides: dict, auto_approve: bool, base: str) -> dict:
    return {
        "schema": 1,
        "task": task,
        "created": now(),
        "stage": "standards",
        "source": source,
        "class": None,
        "size": None,
        "title": None,
        "base_request": base,
        "base": None,
        "branch": None,
        "worktree": None,
        "gates": {},
        "iteration": 0,
        "max_iterations": None,
        "seen_signatures": [],
        "last_signatures": [],
        "frozen": False,
        "freeze_commit": None,
        "red_check_attempts": 0,
        "retries": {},
        "last_error": None,
        "blocked": None,
        "escalation": None,
        "auto_approve": bool(auto_approve),
        "overrides": overrides or {},
        "pr_url": None,
        "pr_number": None,
        "usage": {},
        "history": [],
    }


class Task:
    def __init__(self, paths, task: str):
        self.paths = paths
        self.task = task
        self.dir = paths.task_dir(task)
        self.file = paths.state_file(task)
        data = read_json(self.file)
        if data is None:
            raise CFError(f"no task {task!r} (looked in {self.dir})")
        self.s = data

    # -------------------------------------------------------------- basics
    @property
    def stage(self) -> str:
        return self.s["stage"]

    @property
    def wt(self) -> Path:
        return Path(self.s["worktree"]) if self.s.get("worktree") else self.paths.worktree(self.task)

    def save(self) -> None:
        write_json(self.file, self.s)

    def log(self, line: str) -> None:
        with (self.dir / "run-log.md").open("a") as fh:
            fh.write(f"- {now()} — {line}\n")

    def go(self, stage: str, note: str = "") -> None:
        if stage not in ALL_STAGES:
            raise CFError(f"internal: unknown stage {stage!r}")
        prev = self.s["stage"]
        self.s["stage"] = stage
        self.s["last_error"] = None
        entry = {"stage": stage, "at": now()}
        if note:
            entry["note"] = note
        self.s["history"].append(entry)
        self.save()
        self.log(f"{prev} → **{stage}**" + (f": {note}" if note else ""))

    def require_stage(self, *stages) -> None:
        if self.stage not in stages:
            raise CFError(f"task {self.task} is at stage {self.stage!r}, not {' or '.join(stages)}")

    def add_usage(self, stage: str, tokens) -> None:
        if tokens:
            usage = self.s.setdefault("usage", {})
            usage[stage] = int(usage.get(stage, 0)) + int(tokens)
            self.save()


def list_tasks(paths) -> list:
    if not paths.tasks.exists():
        return []
    out = []
    for d in sorted(paths.tasks.iterdir()):
        if d.is_dir() and (d / "state.json").exists():
            out.append(read_json(d / "state.json"))
    return out
