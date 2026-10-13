"""Agent prompts: the per-run facts (paths, inputs, outputs, feedback).

Role behaviour lives in agents/*.md. The prompt only says where things are,
so every agent gets the same inputs no matter how the orchestrator phrases it.
"""

from __future__ import annotations

from pathlib import Path

from . import diagram
from .presets import PLUGIN_ROOT
from .state import AGENT_STAGES

TEMPLATES = PLUGIN_ROOT / "skills" / "run" / "templates"


def _exists(p: Path) -> bool:
    return Path(p).exists()


def build(t, cfg: dict, standards_path: Path) -> dict:
    s = t.s
    stage = t.stage
    role = AGENT_STAGES[stage]
    d = t.dir
    wt = t.wt
    lines = [
        f"CONGOFORCE_TASK: {t.task}",
        f"CONGOFORCE_STAGE: {stage}",
        "",
        f"You are the **{role}** stage of CongoForce for task `{t.task}`"
        + (f" (class: {s['class']}, size: {s['size']})" if s.get("class") else "") + ".",
        "",
        "## Where things are",
        f"- Task folder (inputs and your outputs): `{d}`",
    ]
    if _exists(wt):
        lines.append(f"- Worktree with the code, branch `{s.get('branch')}` from `{(s.get('base') or {}).get('ref')}`: `{wt}`")
        lines.append(f"  Run every shell command from there: `cd {wt} && …`. Never touch the main checkout at `{t.paths.root}`.")
    else:
        lines.append(f"- Repository (read only at this stage): `{t.paths.root}`")
    lines.append(f"- Standards (follow them; never edit): `{standards_path}`")
    if _exists(d / "repo-map.md"):
        lines.append(f"- Repo map (read the sections you need): `{d / 'repo-map.md'}`")
    elif _exists(t.paths.repomap):
        lines.append(f"- Repo map: `{t.paths.repomap}`")
    if _exists(d / "answers.md"):
        lines.append(f"- Human answers and notes so far (they override earlier docs): `{d / 'answers.md'}`")

    inputs, outputs = [], []
    if stage == "requirements":
        inputs = [d / "input.md"]
        if _exists(d / "assets"):
            inputs.append(d / "assets")
        outputs = [(d / "req.md", TEMPLATES / "req.md")]
    elif stage == "product_spec":
        inputs = [d / "req.md", d / "input.md"] + ([d / "assets"] if _exists(d / "assets") else [])
        outputs = [(d / "product-spec.md", TEMPLATES / "product-spec.md")]
    elif stage == "tech_spec":
        inputs = [d / "req.md"] + ([d / "product-spec.md"] if _exists(d / "product-spec.md") else [])
        outputs = [(d / "tech.md", TEMPLATES / "tech.md")]
    elif stage == "test_author":
        inputs = [d / "req.md"] + ([d / "product-spec.md"] if _exists(d / "product-spec.md") else []) + [d / "interface-contract.md"]
        outputs = [(d / "tests.json", TEMPLATES / "tests.json"), (d / "test.md", TEMPLATES / "test.md")]
        if _exists(d / "red-check.md") and s.get("red_check_attempts"):
            inputs.append(d / "red-check.md")
    elif stage == "implement":
        inputs = [d / "tech.md", d / "req.md"] + ([d / "product-spec.md"] if _exists(d / "product-spec.md") else []) + [d / "tests.json", d / "test.md"]
        fb = d / "feedback" / f"iter-{s['iteration']}.md"
        if _exists(fb):
            inputs.append(fb)
    elif stage == "review":
        inputs = [d / "req.md"] + ([d / "product-spec.md"] if _exists(d / "product-spec.md") else []) + [d / "tech.md", d / "tests.json", d / "checks.md"]
        outputs = [(d / "verify-review.json", TEMPLATES / "verify-review.json"), (d / "verify-report.md", TEMPLATES / "verify-report.md")]

    if inputs:
        lines += ["", "## Read these inputs"] + [f"- `{p}`" for p in inputs]
    if outputs:
        lines += ["", "## Write these outputs (follow the template's structure)"]
        lines += [f"- `{out}` — template: `{tpl}`" for out, tpl in outputs]

    if stage == "tech_spec":
        need = diagram.required(cfg, s)
        lines += [
            "",
            "## Stage facts",
            (f"- Architecture diagram: **required** (architecture_diagram = {cfg.get('architecture_diagram')}). "
             if need else "- Architecture diagram: optional; add one only if the change spans several components. ")
            + "Put one ```mermaid block in `## Architecture`. The helper checks it and renders it with mermaid-cli when installed.",
        ]
    if stage == "test_author":
        lines += [
            "",
            "## Stage facts",
            f"- Write the acceptance test files inside the worktree. Do not commit them; the helper commits them at Gate 2.",
            f"- Do not read `{d / 'tech.md'}`: you see only the interface contract, so the tests stay independent of the implementation plan.",
            f"- Check your tests are red for the right reason with: `congoforce try-tests {t.task}`",
        ]
    if stage == "implement":
        base_note = s.get("freeze_commit") or "the freeze commit"
        lines += [
            "",
            "## Stage facts",
            f"- Iteration {s['iteration']} of at most {s.get('max_iterations') or cfg['max_iterations']}.",
            f"- Acceptance tests and test config are frozen (edits are blocked and hashed). Tests listed in tests.json must pass unchanged.",
            f"- Commit each task from tech.md separately in the worktree (`git -C {wt} commit`). Leave the worktree clean; uncommitted work is rejected.",
            f"- Check your work with: `congoforce check {t.task}` (runs the standards commands, changes no state).",
            f"- Your commits start after {base_note}.",
        ]
    if stage == "review":
        base = (s.get("base") or {}).get("sha", "")
        lines += [
            "",
            "## Stage facts",
            f"- The helper already ran every executable check: see `checks.md`. Do not re-run them; judge what cannot be executed.",
            f"- The change under review: `git -C {wt} diff {base}...HEAD` and `git -C {wt} log --oneline {base}..HEAD`.",
            f"- Review in two passes: spec compliance per acceptance criterion first, then code quality.",
        ]
        if (s.get("diagram") or {}).get("files"):
            lines.append("- tech.md has an `## Architecture` diagram: report components or data flows the code adds, drops or wires differently as a finding.")
    if s.get("last_error"):
        lines += ["", "## Your previous attempt was rejected", f"{s['last_error']}", "Fix exactly this and finish the stage."]

    lines += [
        "",
        "## How to finish",
        "End your final message with these lines, exactly:",
        "```",
        "STATUS: done            (or: STATUS: blocked: <one-line reason the human must resolve>)",
        "SUMMARY: <one or two sentences>",
        "OPEN QUESTIONS:",
        "- <question for the human, or 'none'>",
        "```",
    ]
    model = (cfg.get("models") or {}).get(role, "")
    return {
        "agent": f"congoforce:{role}",
        "role": role,
        "model": model,
        "description": f"CongoForce {role}: {t.task}",
        "prompt": "\n".join(lines),
    }
