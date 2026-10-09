"""One-page packets for each human gate, and the PR body."""

from __future__ import annotations

import re
from pathlib import Path

from .util import md_section, parse_frontmatter, read_json, write_text

AC_RX = re.compile(r"\bAC-\d+\b")


def criteria(text: str) -> list:
    """[(id, text)] for every acceptance criterion line, first mention wins."""
    out, seen = [], set()
    for line in text.splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+\.)?\s*\**\s*(AC-\d+)\s*\**\s*[:.)\-—]*\s*(.*)$", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), m.group(2).strip().strip("*").strip()))
    return out


def all_criteria(task_dir: Path) -> list:
    req = (task_dir / "req.md").read_text() if (task_dir / "req.md").exists() else ""
    spec = (task_dir / "product-spec.md").read_text() if (task_dir / "product-spec.md").exists() else ""
    merged = dict(criteria(req))
    for cid, text in criteria(spec):
        merged[cid] = text or merged.get(cid, "")
    return sorted(merged.items(), key=lambda kv: int(kv[0].split("-")[1]))


def open_questions(task_dir: Path, files=("req.md", "product-spec.md", "tech.md", "test.md")) -> list:
    out = []
    for name in files:
        p = task_dir / name
        if not p.exists():
            continue
        sec = md_section(p.read_text(), "Open questions")
        for line in sec.splitlines():
            line = line.strip()
            if re.match(r"^[-*]\s+", line):
                q = re.sub(r"^[-*]\s+", "", line)
                if q.lower().strip(". ") not in ("none", "n/a", "no open questions"):
                    out.append(f"{q} _(from {name})_")
    return out


def gate1(t) -> Path:
    d = t.dir
    meta, body = parse_frontmatter((d / "req.md").read_text())
    lines = [
        f"# Gate 1 — approve requirements: {meta.get('title', t.task)}",
        "",
        f"Class **{meta.get('class')}**, size **{meta.get('size')}**. Full document: `{d / 'req.md'}`",
        "",
        "## Problem",
        md_section(body, "Problem") or "_(missing)_",
        "",
        "## Acceptance criteria",
    ]
    lines += [f"- **{cid}** {text}" for cid, text in criteria(body)] or ["_(none found)_"]
    oos = md_section(body, "Out of scope")
    if oos:
        lines += ["", "## Out of scope", oos]
    qs = open_questions(d, ("req.md",))
    lines += ["", "## Open questions"] + ([f"- {q}" for q in qs] or ["- none"])
    out = d / "gate1-packet.md"
    write_text(out, "\n".join(lines) + "\n")
    return out


def gate2(t, red: dict) -> Path:
    d = t.dir
    tests = read_json(d / "tests.json", {}) or {}
    lines = [f"# Gate 2 — approve specs and freeze acceptance tests: {t.s.get('title') or t.task}", ""]
    lines += ["## Acceptance criteria", ""]
    by_crit = {}
    for e in tests.get("acceptance", []):
        by_crit.setdefault(e.get("criterion"), []).append(e)
    lines += ["| Criterion | Text | Test file | Tests | Expect |", "| --- | --- | --- | --- | --- |"]
    for cid, text in all_criteria(d):
        entries = by_crit.get(cid, [])
        if not entries:
            lines.append(f"| {cid} | {text} | **no test** | | |")
        for e in entries:
            lines.append(f"| {cid} | {text} | `{e.get('file')}` | {e.get('tests', '?')} | {'red' if e.get('expect_red', True) else 'green (unchanged behaviour)'} |")
    for u in tests.get("untestable", []):
        lines.append(f"| {u.get('criterion')} | | untestable: {u.get('reason')} | | |")
    contract = (d / "interface-contract.md").read_text() if (d / "interface-contract.md").exists() else "_(missing)_"
    lines += ["", "## Interface contract (from tech.md)", "", contract.strip()]
    tasks = md_section((d / "tech.md").read_text(), "Tasks") if (d / "tech.md").exists() else ""
    if tasks:
        lines += ["", "## Implementation tasks (from tech.md)", "", tasks]
    lines += ["", "## Red check", ""]
    if red.get("skipped"):
        lines.append(f"Skipped: {red.get('reason')}")
    else:
        lines.append("**All acceptance tests are red for the right reason.**" if red.get("ok") else "**Red check FAILED.** Approving anyway freezes tests that may be wrong.")
        for p in red.get("problems", []):
            lines.append(f"- {p}")
    qs = open_questions(d)
    lines += ["", "## Open questions"] + ([f"- {q}" for q in qs] or ["- none"])
    lines += ["", f"Full documents: `{d}` (req.md, product-spec.md, tech.md, test.md, tests.json)"]
    out = d / "gate2-packet.md"
    write_text(out, "\n".join(lines) + "\n")
    return out


def escalation(t, reason: str, sigs: list) -> Path:
    d = t.dir
    lines = [
        f"# Escalation — {t.task}",
        "",
        f"**Why the loop stopped:** {reason}",
        "",
        f"Iteration {t.s['iteration']} of {t.s.get('max_iterations')}.",
        "",
        "## Failures",
    ]
    lines += [f"- `{s}`" for s in sigs[:40]] or ["- (none recorded)"]
    lines += [
        "",
        f"Details: `{d / 'checks.md'}`" + (f", `{d / 'verify-report.md'}`" if (d / "verify-report.md").exists() else ""),
        "",
        "## Options",
        "- **code**: the tests are right; give the implementer 2 more iterations, with your note.",
        "- **spec**: the spec is wrong; unfreeze and revise tech.md (then tests and Gate 2 again).",
        "- **test**: a test is wrong; unfreeze and revise the acceptance tests (then Gate 2 again).",
        "- **stop**: end the run; the worktree and branch stay for manual work.",
    ]
    out = d / "escalation.md"
    write_text(out, "\n".join(lines) + "\n")
    return out


def pr_body(t, checks: dict, review: dict, commits: list) -> str:
    d = t.dir
    meta, body = parse_frontmatter((d / "req.md").read_text())
    tests = read_json(d / "tests.json", {}) or {}
    files_by_crit = {}
    for e in tests.get("acceptance", []):
        files_by_crit.setdefault(e.get("criterion"), []).append(e.get("file"))
    unmet = {u.get("criterion") for u in (review or {}).get("unmet", [])}
    lines = [
        "## Summary",
        "",
        md_section(body, "Problem") or meta.get("title", t.task),
        "",
        "## Acceptance criteria",
        "",
        "| Criterion | Test | Status |",
        "| --- | --- | --- |",
    ]
    for cid, text in all_criteria(d):
        files = ", ".join(f"`{f}`" for f in files_by_crit.get(cid, [])) or "—"
        status = "not met" if cid in unmet else "met"
        lines.append(f"| **{cid}** {text} | {files} | {status} |")
    lines += ["", "## Verification", "", "| Check | Result |", "| --- | --- |"]
    for name, res in (checks.get("commands") or {}).items():
        if not res.get("skipped"):
            lines.append(f"| {name} | {res.get('verdict', 'pass' if res.get('ok') else 'fail')} |")
    ts = checks.get("test_summary") or {}
    if ts:
        lines.append(f"| tests | {ts.get('passed', 0)} passed, {ts.get('failed', 0)} failed, {ts.get('skipped', 0)} skipped |")
    lines.append(f"| acceptance tests frozen and unchanged | {'yes' if not checks.get('tampered') else 'NO'} |")
    lines.append(f"| regressions against baseline | {len(checks.get('regressions', [])) or 'none'} |")
    if checks.get("preexisting"):
        lines += ["", "Pre-existing failures on the base branch (not caused by this change):"]
        lines += [f"- `{p}`" for p in checks["preexisting"][:20]]
    if checks.get("flaky"):
        lines += ["", "Flaky (failed, then passed on rerun):"] + [f"- `{f}`" for f in checks["flaky"][:20]]
    findings = [f for f in (review or {}).get("findings", []) if f.get("severity") != "blocking"]
    if findings:
        lines += ["", "## Review notes", ""]
        lines += [f"- **{f.get('severity', 'note')}** {f.get('file', '')}: {f.get('summary', '')}" for f in findings[:20]]
    if commits:
        lines += ["", "## Commits", ""] + [f"- {c.split(' ', 1)[1] if ' ' in c else c}" for c in reversed(commits)]
    usage = t.s.get("usage") or {}
    total = sum(int(v) for v in usage.values())
    lines += [
        "",
        "## Run",
        "",
        f"CongoForce task `{t.task}`, class {t.s.get('class')}, {t.s.get('iteration')} implement iteration(s)"
        + (f", {total:,} tokens" if total else "") + ".",
        f"Specs and tests: `{t.s.get('history_path', '')}`",
        "",
        "🤖 Generated with CongoForce on [Claude Code](https://claude.com/claude-code)",
    ]
    return "\n".join(lines) + "\n"
