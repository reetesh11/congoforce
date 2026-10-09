"""The conductor: what happens next, and every helper stage.

Flow (class decides which spec stages run):

  standards → requirements → [split] → gate1 → prepare (worktree, install,
  baseline, repo map) → [map_summaries] → product_spec → tech_spec →
  test_author → red_check → gate2 → freeze → implement → verify → [review]
  → decide → (implement | escalated | ship_prepare) → [ship_confirm] → ship
  → post_pr → [post_pr_skills] → [retro] → done
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import checks as chk
from . import config as cfgmod
from . import freeze, gitops, junit, packets, presets, prompts, repomap, runner
from . import standards as stdmod
from .paths import Paths, find_repo_root
from .state import (AGENT_STAGES, CLASSES, GATE_STAGES, HELPER_STAGES, SIZES, Task, list_tasks, new_state)
from .util import CFError, md_section, now, parse_frontmatter, read_json, slugify, write_json, write_text

LONG_STAGES = {"prepare", "red_check", "verify", "ship"}
GATE_QUESTIONS = {
    "standards": ("Approve standards.md? Agents follow it and the helper runs its commands.", [
        ("approve", "Approve", "Use these standards and commands (edit the file first if needed)."),
        ("stop", "Stop", "End here; edit standards.md and run again."),
    ]),
    "gate1": ("Gate 1: approve these requirements?", [
        ("approve", "Approve", "Requirements are right; prepare the worktree and write the specs."),
        ("revise", "Revise", "Send them back with your note."),
        ("stop", "Stop", "End the run."),
    ]),
    "split": ("This task is too large for one loop. What now?", [
        ("stop", "Stop and split", "End here; turn the suggested split into separate requirement files."),
        ("proceed", "Proceed anyway", "Treat it as medium and continue to Gate 1."),
    ]),
    "gate2": ("Gate 2: approve the specs and freeze the acceptance tests?", [
        ("approve", "Approve and freeze", "Freeze the tests and start implementing."),
        ("revise-tech", "Revise tech spec", "Send tech.md back with your note (tests are rewritten after)."),
        ("revise-tests", "Revise tests", "Send the acceptance tests back with your note."),
        ("revise-product", "Revise product spec", "Send product-spec.md back with your note (feature only)."),
        ("stop", "Stop", "End the run."),
    ]),
    "ship_confirm": ("Push the branch and open this PR?", [
        ("approve", "Push and open PR", "Push the task branch and open the PR."),
        ("stop", "Don't push", "Keep the branch locally; end the run."),
    ]),
    "escalated": ("The loop stopped. How should it continue?", [
        ("code", "Fix the code", "The tests are right; 2 more iterations with your note."),
        ("spec", "Revisit the spec", "Unfreeze and revise tech.md, then tests and Gate 2."),
        ("test", "Revisit a test", "Unfreeze and revise the acceptance tests, then Gate 2."),
        ("stop", "Stop", "End the run; the branch stays for manual work."),
    ]),
}


# ------------------------------------------------------------------ context

def context(start=None, overrides=None):
    root = find_repo_root(start)
    base_paths = Paths(root)
    cfg = cfgmod.load(base_paths, overrides)
    paths = Paths(root, cfg.get("worktree_dir", ""))
    return paths, cfg


def task_context(task: str, start=None):
    paths, _ = context(start)
    t = Task(paths, task)
    _, cfg = context(start, t.s.get("overrides"))
    return paths, cfg, t


def load_standards(paths, task: str = "") -> dict:
    return stdmod.parse(paths.standards_for(task))


# ------------------------------------------------------------------ init

def init(paths, preset: str = "", force: bool = False) -> dict:
    paths.cf.mkdir(parents=True, exist_ok=True)
    paths.tasks.mkdir(parents=True, exist_ok=True)
    paths.ensure_excludes()
    created = []
    if not paths.config.exists():
        write_text(paths.config, cfgmod.CONFIG_TEMPLATE)
        created.append(str(paths.config))
    detected = presets.detect(paths.root)
    if paths.standards.exists() and not force:
        return {"ok": True, "created": created, "standards": str(paths.standards), "detected": detected, "note": "standards.md already exists"}
    chosen = preset or (detected[0] if detected else "")
    if not chosen:
        raise CFError("could not detect the stack; choose a preset: " + ", ".join(presets.available()) + " (congoforce init --preset <name>)")
    draft = presets.draft(paths.root, chosen)
    write_text(paths.standards, presets.render_standards(paths.root, draft))
    created.append(str(paths.standards))
    return {"ok": True, "created": created, "preset": chosen, "detected": detected, "standards": str(paths.standards),
            "notes": draft.get("notes", []), "commands": draft["commands"]}


# ------------------------------------------------------------------ new task

_REF_RX = re.compile(r"(?:\]\(|src=[\"'])([^)\"'\s#?]+)")


def _unique_task_id(paths, base: str) -> str:
    tid = base
    n = 2
    while paths.task_dir(tid).exists():
        tid = f"{base}-{n}"
        n += 1
    return tid


def new_task(paths, cfg, source: str = "", text: str = "", assets: str = "", base: str = "",
             cls: str = "", overrides: dict = None, auto_approve: bool = False, task_id: str = "") -> dict:
    if not source and not text:
        raise CFError("give a requirement file or --text")
    if cls and cls not in CLASSES:
        raise CFError(f"--class must be one of {', '.join(CLASSES)}")
    if not paths.standards.exists():
        init(paths)
    paths.ensure_excludes()
    src = Path(source).expanduser().resolve() if source else None
    if src and not src.exists():
        raise CFError(f"{source} not found")
    stem = src.stem if src else " ".join(text.split()[:6])
    tid = _unique_task_id(paths, slugify(task_id or stem))
    d = paths.task_dir(tid)
    d.mkdir(parents=True)
    asset_dir = d / "assets"
    if src:
        raw = src.read_text(errors="replace")
        if src.suffix.lower() in (".html", ".htm"):
            asset_dir.mkdir(exist_ok=True)
            shutil.copy2(src, asset_dir / src.name)
            body = f"# Requirement: {src.stem}\n\nThe requirement is the HTML document `assets/{src.name}` (a mock-up or spec). Read it in full.\n"
        else:
            body = raw
        # Copy files the requirement links to (images, mock-ups) next to it.
        for ref in _REF_RX.findall(raw):
            if "://" in ref or ref.startswith(("/", "data:", "mailto:")):
                continue
            p = (src.parent / ref).resolve()
            if p.is_file():
                target = asset_dir / ref
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
        for cand in (src.parent / f"{src.stem}.assets", src.parent / f"{src.stem}_assets", src.parent / f"{src.stem}-assets"):
            if cand.is_dir():
                shutil.copytree(cand, asset_dir, dirs_exist_ok=True)
        write_text(d / "input.md", f"<!-- source: {src} -->\n" + body)
    else:
        write_text(d / "input.md", f"# Requirement\n\n{text.strip()}\n")
    if assets:
        a = Path(assets).expanduser().resolve()
        if not a.is_dir():
            raise CFError(f"--assets {assets} is not a directory")
        shutil.copytree(a, asset_dir, dirs_exist_ok=True)
    s = new_state(tid, str(src) if src else "text", overrides or {}, auto_approve, base)
    if cls:
        s["class"] = cls
        s["class_override"] = cls
    write_json(d / "state.json", s)
    t = Task(paths, tid)
    t.log(f"task created from {s['source']}")
    if stdmod.is_approved(paths):
        t.go("requirements", "standards already approved")
    else:
        _enter_gate(t, cfg, "standards")
    return {"task": tid, "dir": str(d), "stage": t.stage}


# ------------------------------------------------------------------ next

def next_action(paths, cfg, t: Task) -> dict:
    s = t.s
    stage = t.stage
    base = {"task": t.task, "stage": stage}
    if s.get("blocked"):
        b = s["blocked"]
        return {**base, "kind": "blocked", "reason": b.get("reason"),
                "question": f"{b.get('stage')} is blocked: {b.get('reason')}",
                "then": f"congoforce answer {t.task} \"<the human's answer>\"  (re-runs {b.get('stage')})"}
    if stage in AGENT_STAGES:
        std_path = paths.standards_for(t.task)
        p = prompts.build(t, cfg, std_path)
        return {**base, "kind": "agent", **p,
                "background": cfg.get("run_mode") == "background" and stage in ("implement", "review"),
                "then": f"congoforce complete {t.task} {stage} --status done|blocked [--reason ...] [--tokens N] [--questions ...]"}
    if stage in HELPER_STAGES:
        return {**base, "kind": "helper", "command": f"congoforce advance {t.task}", "long": stage in LONG_STAGES}
    if stage in GATE_STAGES:
        packet = _packet_for(t, stage)
        question, options = GATE_QUESTIONS[stage]
        if stage == "gate2" and s.get("class") != "feature":
            options = [o for o in options if o[0] != "revise-product"]
        return {**base, "kind": "gate", "gate": stage, "packet": str(packet) if packet else None, "question": question,
                "options": [{"choice": c, "label": l, "description": d} for c, l, d in options],
                "then": f"congoforce gate {t.task} {stage} <choice> [--note \"...\"]"}
    if stage == "map_summaries":
        return {**base, "kind": "explore", "modules": s.get("stale_modules", []),
                "write": str(t.dir / "map-summaries.json"),
                "instructions": "Spawn ONE Explore agent (thoroughness: quick) to summarise each listed module of the worktree in 2-4 sentences: purpose, main files, how it is used. Write {\"<module>\": \"<summary>\"} JSON to the `write` path, then complete.",
                "worktree": str(t.wt),
                "then": f"congoforce complete {t.task} map_summaries --status done"}
    if stage == "post_pr_skills":
        return {**base, "kind": "skills", "skills": s.get("post_pr_skills", []), "pr_url": s.get("pr_url"),
                "then": f"congoforce complete {t.task} post_pr_skills --status done --summary \"<verdicts>\""}
    if stage == "retro":
        return {**base, "kind": "retro", "inputs": [str(t.dir / "run-log.md"), str(t.dir / "checks.md")] + ([str(t.dir / "escalation.md")] if (t.dir / "escalation.md").exists() else []),
                "standards": str(paths.standards), "write": str(t.dir / "retro.md"),
                "then": f"congoforce complete {t.task} retro --status done --summary \"applied|skipped\""}
    if stage in ("done", "stopped"):
        return {**base, "kind": stage, "pr_url": s.get("pr_url"), "branch": s.get("branch"), "worktree": str(t.wt) if s.get("worktree") else None,
                "summary": _final_summary(t)}
    raise CFError(f"internal: no action for stage {stage}")


def _final_summary(t: Task) -> str:
    s = t.s
    last = s["history"][-1].get("note", "") if s["history"] else ""
    total = sum(int(v) for v in (s.get("usage") or {}).values())
    parts = [f"{t.task}: {t.stage}"]
    if s.get("pr_url"):
        parts.append(f"PR {s['pr_url']}")
    elif s.get("branch"):
        parts.append(f"branch {s['branch']}")
    if s.get("iteration"):
        parts.append(f"{s['iteration']} iteration(s)")
    if total:
        parts.append(f"{total:,} tokens")
    if last:
        parts.append(last)
    return " · ".join(parts)


def _packet_for(t: Task, stage: str):
    d = t.dir
    if stage == "standards":
        return t.paths.standards
    if stage == "gate1":
        return packets.gate1(t)
    if stage == "split":
        return d / "req.md"
    if stage == "gate2":
        return packets.gate2(t, read_json(d / "red.json", {"skipped": True, "reason": "not run"}))
    if stage == "ship_confirm":
        return d / "pr-body.md"
    if stage == "escalated":
        return d / "escalation.md"
    return None


# ------------------------------------------------------------------ gates

def _append_answer(t: Task, heading: str, text: str) -> None:
    if not text:
        return
    with (t.dir / "answers.md").open("a") as fh:
        fh.write(f"\n## {heading} ({now()})\n\n{text.strip()}\n")


def _enter_gate(t: Task, cfg, gate: str, note: str = "") -> None:
    t.go(gate, note)
    if t.s.get("auto_approve"):
        if gate in ("split", "escalated"):
            t.go("stopped", f"auto-approve does not decide {gate}: {note}")
            return
        t.log(f"auto-approved {gate}")
        apply_gate(t, cfg, gate, "approve", "")


def apply_gate(t: Task, cfg, gate: str, choice: str, note: str) -> dict:
    t.require_stage(gate)
    valid = [c for c, _, _ in GATE_QUESTIONS[gate][1]]
    if choice not in valid:
        raise CFError(f"{gate} choices: {', '.join(valid)}")
    t.s["gates"][gate] = {"choice": choice, "at": now(), "note": note}
    t.save()
    _append_answer(t, f"{gate}: {choice}", note)
    if choice == "stop":
        t.go("stopped", f"stopped at {gate}" + (f": {note}" if note else ""))
        return {"stage": t.stage}
    if gate == "standards":
        stdmod.approve(t.paths)
        t.go("requirements", "standards approved")
    elif gate == "gate1":
        if choice == "approve":
            t.go("prepare", "requirements approved")
        else:
            t.s["retries"]["requirements"] = 0
            t.go("requirements", "requirements sent back")
    elif gate == "split":
        t.s["size"] = "medium"
        t.s["size_override"] = True
        _enter_gate(t, cfg, "gate1", "split declined; treating as medium")
    elif gate == "gate2":
        if choice == "approve":
            t.go("freeze", "specs approved; freezing acceptance tests")
        else:
            target = {"revise-tech": "tech_spec", "revise-tests": "test_author", "revise-product": "product_spec"}[choice]
            t.s["retries"][target] = 0
            t.s["red_check_attempts"] = 0
            t.go(target, f"Gate 2 sent back to {target}")
    elif gate == "ship_confirm":
        t.go("ship", "push confirmed")
    elif gate == "escalated":
        repeated = set((t.s.get("escalation") or {}).get("signatures", []))
        if choice == "code":
            t.s["max_iterations"] = int(t.s.get("max_iterations") or cfg["max_iterations"]) + 2
            t.s["seen_signatures"] = [x for x in t.s["seen_signatures"] if x not in repeated]
            t.s["iteration"] += 1
            _write_feedback(t, note_prefix=note)
            t.s["iter_start"] = gitops.head(t.wt)
            t.go("implement", f"human: fix the code ({t.s['max_iterations']} iterations allowed)")
        else:
            _unfreeze(t)
            target = "tech_spec" if choice == "spec" else "test_author"
            t.s["iteration"] = 0
            t.s["seen_signatures"] = []
            t.s["red_check_attempts"] = 0
            t.go(target, f"human: revisit the {choice}")
    return {"stage": t.stage}


def _unfreeze(t: Task) -> None:
    t.s["frozen"] = False
    t.s["max_iterations"] = None
    t.save()
    t.log("acceptance tests unfrozen")


def answer(t: Task, text: str) -> dict:
    _append_answer(t, f"answer at {t.stage}", text)
    if t.s.get("blocked"):
        stage = t.s["blocked"].get("stage")
        t.s["blocked"] = None
        t.s["retries"][stage] = 0
        t.save()
        t.log(f"unblocked {stage} with a human answer")
    return {"stage": t.stage}


# ------------------------------------------------------------------ complete (agent stages)

def complete(paths, cfg, t: Task, stage: str, status: str = "done", reason: str = "", tokens=None,
             summary: str = "", questions=None) -> dict:
    t.require_stage(stage)
    t.add_usage(stage, tokens)
    if summary:
        t.log(f"{stage}: {summary}")
    if questions:
        qs = [q for q in questions if q and q.strip().lower() not in ("none", "- none")]
        if qs:
            t.s.setdefault("questions", {})[stage] = qs
            t.save()
    if status == "blocked":
        t.s["blocked"] = {"stage": stage, "reason": reason or "agent reported blocked", "at": now()}
        t.save()
        t.log(f"{stage} blocked: {reason}")
        return {"stage": stage, "blocked": True}
    try:
        nxt = _validate_and_route(paths, cfg, t, stage)
    except CFError as exc:
        msg = str(exc)
        retries = t.s["retries"].get(stage, 0) + 1
        t.s["retries"][stage] = retries
        t.s["last_error"] = msg
        if retries > int(cfg.get("agent_retries", 2)):
            t.s["blocked"] = {"stage": stage, "reason": f"output rejected {retries} times: {msg}", "at": now()}
        t.save()
        t.log(f"{stage} output rejected ({retries}): {msg}")
        raise CFError(f"{stage} output rejected: {msg}" + (" — re-run the agent (next shows the error)" if retries <= int(cfg.get('agent_retries', 2)) else " — blocked; ask the human"))
    return {"stage": t.stage, **(nxt or {})}


def _req_meta(t: Task) -> tuple:
    p = t.dir / "req.md"
    if not p.exists():
        raise CFError(f"{p} was not written")
    meta, body = parse_frontmatter(p.read_text())
    return meta, body


def _spec_stage_after_prepare(t: Task) -> str:
    return "product_spec" if t.s.get("class") == "feature" else "tech_spec"


def _validate_and_route(paths, cfg, t: Task, stage: str) -> dict:
    d = t.dir
    s = t.s
    if stage == "requirements":
        meta, body = _req_meta(t)
        cls = s.get("class_override") or meta.get("class", "").lower()
        size = meta.get("size", "").lower()
        if cls not in CLASSES:
            raise CFError(f"req.md frontmatter `class` must be one of {', '.join(CLASSES)} (got {meta.get('class')!r})")
        if size not in SIZES:
            raise CFError(f"req.md frontmatter `size` must be one of {', '.join(SIZES)} (got {meta.get('size')!r})")
        if not meta.get("title"):
            raise CFError("req.md frontmatter needs a `title`")
        if not packets.criteria(body):
            raise CFError("req.md has no acceptance criteria (lines starting with AC-1, AC-2, …)")
        if size == "large" and not md_section(body, "Suggested split"):
            raise CFError("size is large but req.md has no `## Suggested split` section")
        s.update({"class": cls, "size": size, "title": meta["title"]})
        t.save()
        if size == "large" and not s.get("size_override"):
            _enter_gate(t, cfg, "split", "too large for one loop")
        else:
            _enter_gate(t, cfg, "gate1", f"{cls}, {size}")
        return {}
    if stage == "map_summaries":
        data = read_json(d / "map-summaries.json", {}) or {}
        if not isinstance(data, dict):
            raise CFError("map-summaries.json must be an object of module → summary")
        if data:
            repomap.store_summaries(paths, t.wt, data)
        repomap.write(paths, t.wt, load_standards(paths, t.task), cfg, d)
        t.go(_spec_stage_after_prepare(t), f"{len(data)} module summaries")
        return {}
    if stage == "product_spec":
        p = d / "product-spec.md"
        if not p.exists() or len(p.read_text().strip()) < 200:
            raise CFError("product-spec.md is missing or nearly empty")
        if not packets.criteria(p.read_text()):
            raise CFError("product-spec.md must restate the acceptance criteria by id (AC-1, …)")
        t.go("tech_spec")
        return {}
    if stage == "tech_spec":
        p = d / "tech.md"
        if not p.exists():
            raise CFError("tech.md was not written")
        text = p.read_text()
        contract = md_section(text, "Interface contract")
        tasks = md_section(text, "Tasks")
        if not contract:
            raise CFError("tech.md needs a non-empty `## Interface contract` section")
        if not re.search(r"^\s*\d+\.\s+", tasks, re.M):
            raise CFError("tech.md needs a `## Tasks` section with a numbered list")
        write_text(d / "interface-contract.md", f"# Interface contract — {t.task}\n\n{contract}\n")
        t.go("test_author")
        return {}
    if stage == "test_author":
        _validate_tests_json(t)
        if s.get("class") == "bootstrap":
            write_json(d / "red.json", {"skipped": True, "reason": "bootstrap task: no test runner yet"})
            _enter_gate(t, cfg, "gate2", "bootstrap: red check skipped")
        else:
            t.go("red_check")
        return {}
    if stage == "implement":
        wt = t.wt
        dirty = gitops.dirty_files(wt)
        if dirty:
            raise CFError("the worktree has uncommitted changes; commit each task (or remove stray files): " + ", ".join(dirty[:10]))
        start = s.get("iter_start") or s.get("freeze_commit")
        if start and not gitops.commits_since(wt, start) and s.get("iteration", 1) <= 1:
            raise CFError("no commits since the freeze commit; commit your work per task")
        t.go("verify", f"iteration {s['iteration']}")
        return {}
    if stage == "review":
        data = read_json(d / "verify-review.json")
        if not isinstance(data, dict) or str(data.get("result", "")).upper() not in ("PASS", "FAIL"):
            raise CFError("verify-review.json must be an object with result PASS or FAIL")
        if not isinstance(data.get("unmet", []), list) or not isinstance(data.get("findings", []), list):
            raise CFError("verify-review.json: `unmet` and `findings` must be lists")
        if not (d / "verify-report.md").exists():
            raise CFError("verify-report.md was not written")
        t.go("decide", f"review {data['result'].upper()}")
        return {}
    if stage == "post_pr_skills":
        t.go("retro" if cfg.get("retro") else "done", "post-PR checks recorded")
        return {}
    if stage == "retro":
        t.go("done", "retro recorded")
        return {}
    raise CFError(f"stage {stage} is not completed by an agent")


def _validate_tests_json(t: Task) -> dict:
    d = t.dir
    data = read_json(d / "tests.json")
    if not isinstance(data, dict) or not isinstance(data.get("acceptance"), list) or not data["acceptance"]:
        raise CFError("tests.json must be an object with a non-empty `acceptance` list")
    covered = set()
    for i, e in enumerate(data["acceptance"]):
        for key in ("criterion", "file", "tests"):
            if key not in e:
                raise CFError(f"tests.json acceptance[{i}] is missing `{key}`")
        if not isinstance(e["tests"], int) or e["tests"] < 1:
            raise CFError(f"tests.json acceptance[{i}].tests must be a positive integer")
        f = t.wt / e["file"]
        if not f.exists():
            raise CFError(f"acceptance test file {e['file']} does not exist in the worktree")
        covered.add(e["criterion"])
    for u in data.get("untestable", []) or []:
        if not u.get("reason"):
            raise CFError("every `untestable` entry needs a reason")
        covered.add(u.get("criterion"))
    if not (d / "test.md").exists():
        raise CFError("test.md was not written")
    if t.s.get("class") != "bootstrap":
        missing = [cid for cid, _ in packets.all_criteria(d) if cid not in covered]
        if missing:
            raise CFError("no acceptance test (or `untestable` reason) for: " + ", ".join(missing))
    return data


# ------------------------------------------------------------------ advance (helper stages)

def advance(paths, cfg, t: Task) -> dict:
    stage = t.stage
    if stage not in HELPER_STAGES:
        raise CFError(f"stage {stage} is not a helper stage; see `congoforce next {t.task}`")
    fn = {
        "prepare": _prepare, "red_check": _red_check, "freeze": _freeze, "verify": _verify,
        "decide": _decide, "ship_prepare": _ship_prepare, "ship": _ship, "post_pr": _post_pr,
    }[stage]
    try:
        out = fn(paths, cfg, t) or {}
    except CFError as exc:
        t.s["blocked"] = {"stage": stage, "reason": str(exc), "at": now()}
        t.save()
        t.log(f"{stage} failed: {exc}")
        raise
    return {"stage": t.stage, **out}


def _prepare(paths, cfg, t: Task) -> dict:
    s = t.s
    if not stdmod.is_approved(paths):
        raise CFError("standards.md is not approved")
    gitops.fetch(paths.root)
    base = gitops.resolve_base(paths.root, s.get("base_request") or cfg.get("base_branch", ""))
    branch = f"{cfg.get('branch_prefix', 'congoforce/')}{t.task}"
    if branch in cfg.get("protected_branches", []) or branch == base["branch"]:
        raise CFError(f"refusing to use protected branch {branch}")
    wt = paths.worktree(t.task)
    gitops.create_worktree(paths.root, wt, branch, base["ref"])
    s.update({"base": base, "branch": branch, "worktree": str(wt)})
    t.save()
    t.log(f"worktree {wt} on {branch} from {base['ref']} ({base['sha'][:10]})")
    std = load_standards(paths, t.task)
    timeout = int(cfg.get("command_timeout", 600))
    out_dir = t.dir / "baseline"
    if std["commands"].get("install"):
        res = runner.run(std["commands"]["install"], wt, timeout, log_path=out_dir / "install.log")
        if not res["ok"]:
            raise CFError(f"install failed ({'timed out' if res['timed_out'] else 'exit ' + str(res['exit'])}): {res['tail'][-1500:]}")
    suite = chk.run_suite(wt, std, cfg, out_dir, "baseline")
    tests = chk.case_map(suite["tests"])
    baseline = {
        "at": now(), "sha": base["sha"],
        "commands": {n: {"ok": r.get("ok"), "skipped": r.get("skipped", False), "timed_out": r.get("timed_out"), "errors": r.get("errors", []), "tail": r.get("tail", "")}
                     for n, r in suite["commands"].items()},
        "tests": {cid: c["status"] for cid, c in tests.items()},
        "test_ran": bool(suite["tests"] and not suite["tests"].get("skipped")),
    }
    write_json(t.dir / "baseline.json", baseline)
    failing_cmds = [n for n, r in baseline["commands"].items() if not r["ok"] and not r["skipped"]]
    failing_tests = [cid for cid, st in baseline["tests"].items() if st in ("failed", "error")]
    lines = [f"# Baseline — {base['ref']} @ {base['sha'][:10]}", ""]
    lines += [f"- {n}: {'skipped' if r['skipped'] else 'ok' if r['ok'] else 'FAILING'}" for n, r in baseline["commands"].items()]
    lines.append(f"- tests: {len(tests)} ran, {len(failing_tests)} failing")
    lines += [f"  - `{x}`" for x in failing_tests[:30]]
    write_text(t.dir / "baseline.md", "\n".join(lines) + "\n")
    # Repo map from the untouched base.
    repomap.write(paths, wt, std, cfg, t.dir)
    stale = repomap.stale_modules(paths, wt, std.get("package_dir", ".")) if cfg.get("repo_map_backend", "builtin") == "builtin" else []
    preexisting = failing_cmds + failing_tests
    note = "baseline clean" if not preexisting else f"baseline has pre-existing failures: {', '.join(preexisting[:8])}"
    if stale:
        s["stale_modules"] = [m["module"] for m in stale]
        t.save()
        t.go("map_summaries", note)
    else:
        t.go(_spec_stage_after_prepare(t), note)
    return {"worktree": str(wt), "branch": branch, "base": base["ref"], "preexisting_failures": preexisting,
            "baseline": str(t.dir / "baseline.md")}


def _preset_patterns(std: dict) -> tuple:
    name = std.get("preset") or ""
    try:
        p = presets.load_preset(name) if name else {}
    except CFError:
        p = {}
    return [re.compile(x) for x in p.get("suspect_patterns", [])], [re.compile(x) for x in p.get("import_red_patterns", [])]


def _match_entry(cases, entry) -> list:
    return [c for c in cases if junit.case_matches_file(c, entry["file"])]


def red_check_eval(t: Task, cfg, std: dict, out_dir: Path) -> dict:
    tests = read_json(t.dir / "tests.json", {}) or {}
    entries = tests.get("acceptance", [])
    files = sorted({e["file"] for e in entries})
    res = chk.run_tests(t.wt, std, int(cfg.get("command_timeout", 600)), out_dir, "red", files=files)
    if res.get("skipped"):
        return {"ok": False, "skipped": True, "reason": res["reason"], "problems": [res["reason"]]}
    cases = [junit.Case(**{k: c[k] for k in ("name", "classname", "file", "suite", "status", "message")}) for c in res["cases"]]
    suspect, import_red = _preset_patterns(std)
    problems, rows = [], []
    if not cases:
        problems.append(f"no JUnit report was produced; command output:\n{res.get('tail', '')[-1200:]}")
    for e in entries:
        matched = _match_entry(cases, e)
        want_red = e.get("expect_red", True)
        statuses = [c.status for c in matched]
        rows.append({"file": e["file"], "criterion": e["criterion"], "declared": e["tests"], "ran": len(matched), "statuses": statuses})
        if not matched:
            problems.append(f"{e['file']} ({e['criterion']}): no tests collected")
            continue
        for c in matched:
            if c.status == "skipped":
                problems.append(f"{c.id}: skipped")
            elif any(rx.search(c.message or "") for rx in suspect):
                problems.append(f"{c.id}: red for the wrong reason (test is broken): {junit.normalise(c.message)}")
        file_level_import_error = (len(matched) == 1 and matched[0].status in ("failed", "error")
                                   and any(rx.search(matched[0].message or "") for rx in import_red))
        if want_red:
            passing = [c for c in matched if c.status == "passed"]
            if passing:
                problems.append(f"{e['file']} ({e['criterion']}): {len(passing)} test(s) already pass before implementation: " + ", ".join(c.name for c in passing[:5]))
            if len(matched) < e["tests"] and not file_level_import_error:
                problems.append(f"{e['file']} ({e['criterion']}): declared {e['tests']} tests, collected {len(matched)}")
        else:
            failing = [c for c in matched if c.status in ("failed", "error")]
            if failing:
                problems.append(f"{e['file']} ({e['criterion']}): unchanged-behaviour tests must pass now, but fail: " + ", ".join(junit.normalise(c.message) for c in failing[:3]))
    return {"ok": not problems, "problems": problems, "rows": rows, "summary": res.get("summary"),
            "cases": [{"id": c.id, "status": c.status, "message": junit.normalise(c.message)} for c in cases]}


def _red_check(paths, cfg, t: Task) -> dict:
    std = load_standards(paths, t.task)
    red = red_check_eval(t, cfg, std, t.dir / "red")
    write_json(t.dir / "red.json", red)
    lines = [f"# Red check — {t.task}", "", "**PASS: every acceptance test is red for the right reason.**" if red["ok"] else "**FAIL**", ""]
    lines += [f"- {p}" for p in red.get("problems", [])]
    lines += ["", "| Test | Status | Message |", "| --- | --- | --- |"]
    lines += [f"| `{c['id']}` | {c['status']} | {c['message']} |" for c in red.get("cases", [])[:80]]
    write_text(t.dir / "red-check.md", "\n".join(lines) + "\n")
    if red["ok"]:
        _enter_gate(t, cfg, "gate2", "red check passed")
    else:
        t.s["red_check_attempts"] = t.s.get("red_check_attempts", 0) + 1
        if t.s["red_check_attempts"] < int(cfg.get("red_check_attempts", 2)):
            t.go("test_author", f"red check failed (attempt {t.s['red_check_attempts']})")
            t.s["last_error"] = "Red check failed:\n" + "\n".join(f"- {p}" for p in red["problems"]) + f"\nDetails: {t.dir / 'red-check.md'}"
            t.save()
        else:
            _enter_gate(t, cfg, "gate2", "red check still failing; the human decides")
    return {"red_check": "pass" if red["ok"] else "fail", "problems": red["problems"]}


def _history_path(cfg, t: Task) -> str:
    return f"{cfg.get('history_dir', '.congoforce/history').rstrip('/')}/{t.task}"


def _copy_history(cfg, t: Task, names) -> list:
    rel = _history_path(cfg, t)
    dest = t.wt / rel
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in names:
        src = t.dir / name
        if src.exists():
            shutil.copy2(src, dest / name)
            copied.append(f"{rel}/{name}")
    return copied


def _freeze(paths, cfg, t: Task) -> dict:
    std = load_standards(paths, t.task)
    tests = _validate_tests_json(t)
    files = sorted({e["file"] for e in tests["acceptance"]})
    frozen = freeze.compute(t.wt, files, std.get("freeze_globs", []), std.get("freeze_keys", []))
    docs = _copy_history(cfg, t, ["req.md", "product-spec.md", "tech.md", "interface-contract.md", "test.md", "tests.json"])
    sha = gitops.commit_paths(t.wt, files + docs, f"congoforce({t.task}): approved spec and acceptance tests")
    frozen["commit"] = sha
    frozen["at"] = now()
    write_json(t.dir / "frozen.json", frozen)
    t.s.update({"frozen": True, "freeze_commit": sha, "iter_start": sha, "history_path": _history_path(cfg, t)})
    if not t.s.get("iteration"):
        t.s["iteration"] = 1
    t.s["max_iterations"] = int(t.s.get("max_iterations") or cfg["max_iterations"])
    t.save()
    t.go("implement", f"frozen {len(frozen['files'])} files, {len(frozen['keys'])} keys at {sha[:10]}")
    return {"frozen_files": sorted(frozen["files"]), "commit": sha}


def _verify(paths, cfg, t: Task) -> dict:
    d = t.dir
    for name in ("verify-review.json", "verify-report.md"):
        if (d / name).exists():
            (d / name).unlink()
    std = load_standards(paths, t.task)
    it = t.s.get("iteration", 1)
    out_dir = d / "verify" / f"iter-{it}"
    frozen = read_json(d / "frozen.json", {}) or {}
    tampered = freeze.check(t.wt, frozen) if frozen else []
    suite = chk.run_suite(t.wt, std, cfg, out_dir, "verify")
    baseline = read_json(d / "baseline.json", {}) or {}
    base_tests = baseline.get("tests", {})
    tests_res = suite["tests"] or {"skipped": True, "reason": "no test command"}
    cases = [junit.Case(**{k: c[k] for k in ("name", "classname", "file", "suite", "status", "message")}) for c in tests_res.get("cases", [])]
    failing = [c for c in cases if c.status in ("failed", "error")]
    # Flaky: rerun failing files once.
    flaky = set()
    rerun_files = sorted({c.file for c in failing if c.file and (t.wt / c.file).exists()})
    if rerun_files:
        rr = chk.run_tests(t.wt, std, int(cfg.get("command_timeout", 600)), out_dir, "rerun", files=rerun_files)
        passed_now = {c["id"] for c in rr.get("cases", []) if c["status"] == "passed"}
        flaky = {c.id for c in failing if c.id in passed_now}
    preexisting = sorted(c.id for c in failing if base_tests.get(c.id) in ("failed", "error"))
    regressions = sorted(c.id for c in failing if base_tests.get(c.id) == "passed" and c.id not in flaky)
    sigs = []
    for c in failing:
        if c.id in flaky or c.id in preexisting:
            continue
        sigs.append(junit.signature(c))
    if tests_res.get("timed_out"):
        sigs.append("cmd:test|timeout")
    elif not tests_res.get("skipped") and tests_res.get("no_report"):
        sigs.append("cmd:test|no JUnit report: " + junit.normalise(tests_res.get("tail", "").splitlines()[-1] if tests_res.get("tail") else ""))
    # Acceptance tests must have run, unskipped.
    collection = []
    tests_json = read_json(d / "tests.json", {}) or {}
    if not tests_res.get("skipped"):
        for e in tests_json.get("acceptance", []):
            matched = _match_entry(cases, e)
            skipped = [c for c in matched if c.status == "skipped"]
            if len(matched) < e["tests"]:
                collection.append(f"collect:{e['file']}|declared {e['tests']}, ran {len(matched)}")
            if skipped:
                collection.append(f"collect:{e['file']}|{len(skipped)} skipped")
    sigs += collection
    # Non-test commands, compared with the baseline.
    cmd_out = {}
    for name, res in suite["commands"].items():
        if res.get("skipped"):
            continue
        b = (baseline.get("commands") or {}).get(name, {})
        verdict = "pass"
        if res.get("timed_out"):
            verdict = "timed out"
            sigs.append(f"cmd:{name}|timeout")
        elif not res.get("ok"):
            new_errors = [e for e in res.get("errors", []) if e not in set(b.get("errors", []))]
            if b and not b.get("ok") and not b.get("skipped") and not new_errors:
                verdict = "pre-existing failure (same as base)"
                preexisting.append(f"{name} (same errors as the base branch)")
            else:
                verdict = "fail"
                sigs.append(f"cmd:{name}|" + (new_errors[0] if new_errors else f"exit {res.get('exit')}"))
        cmd_out[name] = {"ok": res.get("ok"), "verdict": verdict, "tail": res.get("tail", "")[-2500:]}
    if tampered:
        sigs += [f"frozen:{x}" for x in tampered]
    sigs = sorted(set(sigs))
    result = {
        "iteration": it, "at": now(), "passed": not sigs and not regressions,
        "tampered": tampered, "commands": cmd_out, "test_summary": tests_res.get("summary", {}),
        "failing": [{"id": c.id, "message": junit.normalise(c.message)} for c in failing],
        "regressions": regressions, "preexisting": preexisting, "flaky": sorted(flaky),
        "collection": collection, "signatures": sigs,
    }
    write_json(d / "checks.json", result)
    write_text(d / "checks.md", _checks_md(t, result, tests_res))
    if result["passed"]:
        t.go("review", "all executable checks pass")
    else:
        t.go("decide", f"{len(sigs)} failure signature(s)" + (f", {len(regressions)} regression(s)" if regressions else ""))
    return {"passed": result["passed"], "signatures": sigs[:20], "checks": str(d / "checks.md")}


def _checks_md(t: Task, r: dict, tests_res: dict) -> str:
    lines = [f"# Checks — {t.task}, iteration {r['iteration']}", "",
             f"**{'PASS' if r['passed'] else 'FAIL'}** — executable checks only; the verifier judges the rest.", "",
             "| Check | Result |", "| --- | --- |"]
    for name, res in r["commands"].items():
        lines.append(f"| {name} | {res['verdict']} |")
    ts = r.get("test_summary") or {}
    lines.append(f"| tests | {ts.get('passed', 0)} passed, {ts.get('failed', 0) + ts.get('error', 0)} failed, {ts.get('skipped', 0)} skipped |" if ts else "| tests | not run |")
    lines.append(f"| frozen set | {'intact' if not r['tampered'] else 'CHANGED'} |")
    sections = [("Frozen set changed (process violation)", r["tampered"]), ("Regressions (passed on the base branch)", r["regressions"]),
                ("Acceptance tests not run as declared", r["collection"]), ("Pre-existing failures (not counted)", r["preexisting"]),
                ("Flaky (passed on rerun, not counted)", r["flaky"])]
    for title, items in sections:
        if items:
            lines += ["", f"## {title}", ""] + [f"- `{x}`" for x in items]
    if r["failing"]:
        lines += ["", "## Failing tests", ""] + [f"- `{f['id']}` — {f['message']}" for f in r["failing"][:60]]
    for name, res in r["commands"].items():
        if res["verdict"] not in ("pass",):
            lines += ["", f"## {name} output (tail)", "", "```", res["tail"], "```"]
    if tests_res.get("no_report") and not tests_res.get("skipped"):
        lines += ["", "## test output (tail, no JUnit report)", "", "```", tests_res.get("tail", ""), "```"]
    lines += ["", "## Failure signatures", ""] + ([f"- `{s}`" for s in r["signatures"]] or ["- none"])
    return "\n".join(lines) + "\n"


def _write_feedback(t: Task, note_prefix: str = "") -> Path:
    d = t.dir
    it = t.s["iteration"]
    lines = [f"# Feedback for iteration {it}", ""]
    if note_prefix:
        lines += ["## From the human", "", note_prefix, ""]
    lines += ["## What failed last time", "", f"Full details: `{d / 'checks.md'}`", ""]
    lines += [f"- `{s}`" for s in t.s.get("last_signatures", [])] or ["- (see checks.md)"]
    review = read_json(d / "verify-review.json")
    if review:
        unmet = review.get("unmet", [])
        blocking = [f for f in review.get("findings", []) if f.get("severity") == "blocking"]
        if unmet or blocking:
            lines += ["", "## From the verifier", ""]
            lines += [f"- {u.get('criterion')}: {u.get('why', '')}" for u in unmet]
            lines += [f"- {f.get('file', '')}: {f.get('summary', '')}" for f in blocking]
            lines.append(f"\nReport: `{d / 'verify-report.md'}`")
    lines += ["", "Fix these without changing the frozen acceptance tests or test config."]
    out = d / "feedback" / f"iter-{it}.md"
    write_text(out, "\n".join(lines) + "\n")
    return out


def _escalate(t: Task, cfg, reason: str, sigs: list) -> dict:
    t.s["escalation"] = {"reason": reason, "signatures": sigs, "at": now()}
    t.save()
    packets.escalation(t, reason, sigs)
    _enter_gate(t, cfg, "escalated", reason)
    return {"escalated": reason}


def _decide(paths, cfg, t: Task) -> dict:
    d = t.dir
    checks_r = read_json(d / "checks.json", {}) or {}
    review = read_json(d / "verify-review.json")
    if checks_r.get("tampered"):
        return _escalate(t, cfg, "process violation: the frozen acceptance tests or test config changed: " + "; ".join(checks_r["tampered"][:5]),
                         [f"frozen:{x}" for x in checks_r["tampered"]])
    if checks_r.get("regressions"):
        return _escalate(t, cfg, f"regression: {len(checks_r['regressions'])} test(s) that passed on the base branch now fail",
                         checks_r["regressions"])
    failures = list(checks_r.get("signatures", []))
    if review:
        for u in review.get("unmet", []):
            failures.append(f"review:{u.get('criterion')}")
        for f in review.get("findings", []):
            if f.get("severity") == "blocking":
                failures.append(f"review-blocking:{junit.normalise(f.get('file', '') + ' ' + f.get('summary', ''))[:120]}")
        if str(review.get("result", "")).upper() == "FAIL" and not failures:
            failures.append("review:FAIL")
    if not failures:
        t.go("ship_prepare", f"iteration {t.s['iteration']} passed")
        return {"decision": "ship"}
    seen = set(t.s.get("seen_signatures", []))
    repeated = sorted(set(failures) & seen)
    t.s["seen_signatures"] = sorted(seen | set(failures))
    t.s["last_signatures"] = failures
    t.save()
    if repeated:
        return _escalate(t, cfg, f"same failure twice: {repeated[0]}" + (f" (+{len(repeated) - 1} more)" if len(repeated) > 1 else ""), repeated)
    if t.s["iteration"] >= int(t.s.get("max_iterations") or cfg["max_iterations"]):
        return _escalate(t, cfg, f"iteration cap reached ({t.s['iteration']})", failures)
    t.s["iteration"] += 1
    fb = _write_feedback(t)
    t.s["iter_start"] = gitops.head(t.wt)
    t.save()
    t.go("implement", f"iteration {t.s['iteration']}: {len(failures)} failure(s) to fix")
    return {"decision": "implement", "feedback": str(fb)}


def _ship_prepare(paths, cfg, t: Task) -> dict:
    d = t.dir
    docs = _copy_history(cfg, t, ["verify-report.md", "checks.md"])
    if docs:
        gitops.commit_paths(t.wt, docs, f"congoforce({t.task}): verification report")
    commits = gitops.commits_since(t.wt, t.s["base"]["sha"])
    body = packets.pr_body(t, read_json(d / "checks.json", {}) or {}, read_json(d / "verify-review.json", {}) or {}, commits)
    write_text(d / "pr-body.md", body)
    if not cfg.get("push", True):
        t.go("done", f"dry run: branch {t.s['branch']} is ready in {t.wt}; nothing pushed")
        return {"pr_body": str(d / "pr-body.md"), "dry_run": True}
    if not gitops.has_remote(paths.root):
        t.go("done", f"no git remote: branch {t.s['branch']} is ready locally in {t.wt}")
        return {"pr_body": str(d / "pr-body.md"), "no_remote": True}
    if cfg.get("confirm_before_push", True):
        _enter_gate(t, cfg, "ship_confirm", "PR body ready")
    else:
        t.go("ship", "confirm_before_push is off")
    return {"pr_body": str(d / "pr-body.md")}


def _ship(paths, cfg, t: Task) -> dict:
    branch = t.s["branch"]
    base_branch = t.s["base"]["branch"]
    if branch in cfg.get("protected_branches", []) or branch == base_branch:
        raise CFError(f"refusing to push to {branch}")
    if gitops.dirty_files(t.wt):
        raise CFError("worktree has uncommitted changes; refusing to push")
    gitops.push(t.wt, branch)
    t.log(f"pushed {branch}")
    url = None
    if cfg.get("create_pr", True):
        title = t.s.get("title") or t.task
        url = gitops.create_pr(t.wt, base_branch, branch, title, t.dir / "pr-body.md")
        m = re.search(r"/pull/(\d+)", url or "")
        t.s.update({"pr_url": url, "pr_number": int(m.group(1)) if m else None})
        t.save()
    t.go("post_pr", f"PR {url}" if url else f"pushed {branch}, no PR (create_pr = false)")
    return {"pr_url": url, "branch": branch}


def _post_pr(paths, cfg, t: Task) -> dict:
    entries = cfg.get("post_pr") or []
    subs = {"{pr}": str(t.s.get("pr_number") or ""), "{pr_url}": t.s.get("pr_url") or "", "{branch}": t.s.get("branch") or "", "{task}": t.task}
    def fill(x: str) -> str:
        for k, v in subs.items():
            x = x.replace(k, v)
        return x
    skills, ran = [], []
    for e in entries:
        e = fill(e)
        if e.startswith("/"):
            skills.append(e)
        else:
            res = runner.run(e, t.wt, int(cfg.get("command_timeout", 600)), log_path=t.dir / "post-pr" / f"{len(ran)}.log")
            ran.append({"command": e, "ok": res["ok"], "tail": res["tail"][-800:]})
            t.log(f"post_pr `{e}`: {'ok' if res['ok'] else 'FAILED'}")
    if ran:
        write_json(t.dir / "post-pr.json", ran)
    if skills:
        t.s["post_pr_skills"] = skills
        t.save()
        t.go("post_pr_skills", f"{len(skills)} skill(s) to run")
    else:
        t.go("retro" if cfg.get("retro") else "done", "post-PR done")
    return {"commands": ran, "skills": skills}


# ------------------------------------------------------------------ read-only helpers for agents

def check_worktree(paths, cfg, t: Task) -> str:
    if not t.wt.exists():
        raise CFError("no worktree yet")
    std = load_standards(paths, t.task)
    suite = chk.run_suite(t.wt, std, cfg, t.dir / "scratch", "check")
    text = chk.short(suite)
    frozen = read_json(t.dir / "frozen.json")
    if frozen:
        problems = freeze.check(t.wt, frozen)
        text += "\nfrozen set: " + ("intact" if not problems else "CHANGED: " + "; ".join(problems))
    base = read_json(t.dir / "baseline.json", {}) or {}
    pre = [k for k, v in (base.get("tests") or {}).items() if v in ("failed", "error")]
    if pre:
        text += f"\n(note: {len(pre)} test(s) already failed on the base branch)"
    return text


def try_tests(paths, cfg, t: Task) -> str:
    std = load_standards(paths, t.task)
    if not (t.dir / "tests.json").exists():
        raise CFError("write tests.json first (it lists the acceptance test files)")
    red = red_check_eval(t, cfg, std, t.dir / "scratch")
    lines = ["Red check preview: " + ("PASS — every acceptance test is red for the right reason." if red["ok"] else "FAIL")]
    lines += [f"- {p}" for p in red.get("problems", [])]
    lines += [f"  {c['status']:7} {c['id']}: {c['message']}" for c in red.get("cases", [])[:60]]
    return "\n".join(lines)


def status(paths) -> list:
    rows = []
    for s in list_tasks(paths):
        total = sum(int(v) for v in (s.get("usage") or {}).values())
        rows.append({
            "task": s["task"], "stage": s["stage"] + (" (blocked)" if s.get("blocked") else ""),
            "class": s.get("class") or "—", "branch": s.get("branch") or "—",
            "base": (s.get("base") or {}).get("ref") or s.get("base_request") or "—",
            "iteration": s.get("iteration") or 0, "pr": s.get("pr_url") or "—", "tokens": total,
        })
    return rows


def clean(paths, task: str = "", merged: bool = False) -> list:
    removed = []
    for s in list_tasks(paths):
        if task and s["task"] != task:
            continue
        if not s.get("worktree") or not Path(s["worktree"]).exists():
            continue
        if not task:
            if s["stage"] not in ("done", "stopped"):
                continue
            if merged:
                st = gitops.pr_state(s["worktree"], s.get("pr_url"))
                if st not in ("MERGED", "CLOSED"):
                    continue
        gitops.remove_worktree(paths.root, Path(s["worktree"]))
        t = Task(paths, s["task"])
        t.log("worktree removed")
        removed.append(s["task"])
    return removed
