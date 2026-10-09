"""`congoforce` command line. Orchestrator-facing commands print JSON."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys

from . import __version__
from . import config as cfgmod
from . import conductor as c
from . import standards as stdmod
from .presets import PLUGIN_ROOT
from .util import CFError


def _out(data, as_text=False) -> None:
    if as_text and isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2))


def _overrides(pairs) -> dict:
    return dict(cfgmod.parse_override(p) for p in (pairs or []))


def cmd_init(a):
    paths, cfg = c.context()
    _out(c.init(paths, a.preset, a.force))


def cmd_standards(a):
    paths, _ = c.context()
    if a.action == "approve":
        _out(stdmod.approve(paths))
    else:
        std = stdmod.parse(paths.standards)
        _out({"approved": stdmod.is_approved(paths), "commands": std["commands"], "package_dir": std["package_dir"],
              "freeze_globs": std["freeze_globs"], "freeze_keys": std["freeze_keys"], "docs": std["docs"]})


def cmd_new(a):
    paths, cfg = c.context(overrides=_overrides(a.set))
    _out(c.new_task(paths, cfg, source=a.source or "", text=a.text or "", assets=a.assets or "", base=a.base or "",
                    cls=a.cls or "", overrides=_overrides(a.set), auto_approve=a.auto_approve, task_id=a.id or ""))


def cmd_next(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.next_action(paths, cfg, t))


def cmd_complete(a):
    paths, cfg, t = c.task_context(a.task)
    qs = [q.strip() for q in (a.questions or "").split("||") if q.strip()]
    _out(c.complete(paths, cfg, t, a.stage, a.status, a.reason or "", a.tokens, a.summary or "", qs))


def cmd_gate(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.apply_gate(t, cfg, a.gate, a.choice, a.note or ""))


def cmd_answer(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.answer(t, a.text))


def cmd_advance(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.advance(paths, cfg, t))


def cmd_check(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.check_worktree(paths, cfg, t), as_text=True)


def cmd_try_tests(a):
    paths, cfg, t = c.task_context(a.task)
    _out(c.try_tests(paths, cfg, t), as_text=True)


def cmd_status(a):
    paths, _ = c.context()
    rows = c.status(paths)
    if a.json:
        _out(rows)
        return
    if not rows:
        print("No CongoForce tasks in this repo.")
        return
    cols = ["task", "stage", "class", "iteration", "branch", "base", "pr", "tokens"]
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in cols}
    print("  ".join(k.upper().ljust(widths[k]) for k in cols))
    for r in rows:
        print("  ".join(str(r[k]).ljust(widths[k]) for k in cols))


def cmd_clean(a):
    paths, _ = c.context()
    _out({"removed": c.clean(paths, a.task or "", a.merged)})


def cmd_map(a):
    from . import repomap
    paths, cfg = c.context()
    std = c.load_standards(paths)
    _out({"written": str(paths.repomap), "chars": len(repomap.write(paths, paths.root, std, cfg))})


def cmd_sync_user_config(a):
    _out(cfgmod.sync_user_config(a.pairs))


def cmd_doctor(a):
    checks = {"congoforce": __version__, "plugin_root": str(PLUGIN_ROOT), "python": platform.python_version()}
    git_v = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    checks["git"] = git_v or "MISSING"
    checks["gh"] = "present" if shutil.which("gh") else "missing (needed to open PRs; or set create_pr = false)"
    if shutil.which("gh"):
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        checks["gh_auth"] = "ok" if auth.returncode == 0 else "not logged in (run: gh auth login)"
    try:
        paths, cfg = c.context()
        checks["repo"] = str(paths.root)
        checks["standards"] = ("approved" if stdmod.is_approved(paths) else "draft (not approved)") if paths.standards.exists() else "missing (congoforce init)"
        checks["config"] = cfg
    except CFError as exc:
        checks["repo"] = str(exc)
    _out(checks)


def cmd_hook(a):
    from . import hooks
    sys.exit(hooks.main(a.name))


def build_parser():
    p = argparse.ArgumentParser(prog="congoforce", description="CongoForce helper: the deterministic conductor behind /congoforce:run.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="detect the stack, draft standards.md and config.toml")
    s.add_argument("--preset", default="")
    s.add_argument("--force", action="store_true", help="redraft standards.md even if it exists")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("standards", help="show or approve standards.md")
    s.add_argument("action", choices=["show", "approve"])
    s.set_defaults(fn=cmd_standards)

    s = sub.add_parser("new", help="start a task from a requirement file or text")
    s.add_argument("source", nargs="?", help="requirement file (.md, .txt, .html)")
    s.add_argument("--text", help="one-line requirement instead of a file")
    s.add_argument("--assets", help="folder of images or mock-ups to attach")
    s.add_argument("--base", help="branch to start from (stacked work), e.g. congoforce/other-task")
    s.add_argument("--class", dest="cls", choices=["feature", "task", "bug", "bootstrap"])
    s.add_argument("--id", help="task id (default: from the file name)")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="per-run config override")
    s.add_argument("--auto-approve", action="store_true", help="approve gates automatically (fixtures and evals only)")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("next", help="what the orchestrator should do next (JSON)")
    s.add_argument("task")
    s.set_defaults(fn=cmd_next)

    s = sub.add_parser("complete", help="report an agent/orchestrator stage as finished")
    s.add_argument("task")
    s.add_argument("stage")
    s.add_argument("--status", default="done", choices=["done", "blocked"])
    s.add_argument("--reason")
    s.add_argument("--tokens", type=int)
    s.add_argument("--summary")
    s.add_argument("--questions", help="open questions separated by ||")
    s.set_defaults(fn=cmd_complete)

    s = sub.add_parser("gate", help="record a human decision at a gate")
    s.add_argument("task")
    s.add_argument("gate")
    s.add_argument("choice")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_gate)

    s = sub.add_parser("answer", help="record a human answer and unblock the task")
    s.add_argument("task")
    s.add_argument("text")
    s.set_defaults(fn=cmd_answer)

    s = sub.add_parser("advance", help="run the current helper stage")
    s.add_argument("task")
    s.set_defaults(fn=cmd_advance)

    s = sub.add_parser("check", help="(agents) run the standards commands in the worktree; changes no state")
    s.add_argument("task")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("try-tests", help="(test-author) preview the red check; changes no state")
    s.add_argument("task")
    s.set_defaults(fn=cmd_try_tests)

    s = sub.add_parser("status", help="one line per task")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("clean", help="remove worktrees of finished tasks")
    s.add_argument("--task")
    s.add_argument("--merged", action="store_true", help="only tasks whose PR is merged or closed")
    s.set_defaults(fn=cmd_clean)

    s = sub.add_parser("map", help="regenerate .congoforce/repo-map.md from the main checkout")
    s.set_defaults(fn=cmd_map)

    s = sub.add_parser("sync-user-config", help="store plugin userConfig values (key=value ...)")
    s.add_argument("pairs", nargs="*")
    s.set_defaults(fn=cmd_sync_user_config)

    s = sub.add_parser("doctor", help="check prerequisites")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("hook", help="(internal) run a PreToolUse guard")
    s.add_argument("name", choices=["push-guard", "freeze-guard", "stage-guard", "context-guard"])
    s.set_defaults(fn=cmd_hook)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except CFError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 1
    return 0
