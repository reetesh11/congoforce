"""Stack presets: detect the stack and draft standards.md.

All stack-specific knowledge sits in presets/<name>/preset.json plus the small
amount of logic here, so the state machine, agents and loop stay stack-neutral.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .util import CFError

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = PLUGIN_ROOT / "presets"
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "dist", "build", ".congoforce", ".claude", "__pycache__", ".next", "coverage"}


def load_preset(name: str) -> dict:
    path = PRESETS_DIR / name / "preset.json"
    if not path.exists():
        raise CFError(f"unknown preset {name!r}; available: {', '.join(available())}")
    return json.loads(path.read_text())


def available() -> list:
    return sorted(p.name for p in PRESETS_DIR.iterdir() if (p / "preset.json").exists())


def _walk(root: Path, max_depth: int = 3):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not (d.startswith(".") and d != ".github")]
        if rel_depth >= max_depth:
            dirnames[:] = []
        yield Path(dirpath), filenames


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _js_packages(root: Path) -> list:
    pkgs = []
    for dirpath, files in _walk(root, 3):
        if "package.json" in files:
            pkgs.append(dirpath)
    return pkgs


def _tracked(root: Path, name: str) -> bool:
    """A lockfile only counts when it is committed: worktrees start from git, not the disk."""
    import subprocess
    res = subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=str(root), capture_output=True, text=True)
    if res.returncode == 0:
        return True
    in_git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(root), capture_output=True, text=True).returncode == 0
    return (not in_git) and (Path(root) / name).exists()


def _deps(pkg_json: dict) -> dict:
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(pkg_json.get(key) or {})
    return deps


def detect(root: Path) -> list:
    """Presets that match, best first."""
    root = Path(root)
    scores = []
    py = load_preset("python")
    if any((root / f).exists() for f in py["detect_files"]):
        text = ""
        for f in ("pyproject.toml", "setup.cfg", "requirements-dev.txt", "requirements.txt"):
            if (root / f).exists():
                text += (root / f).read_text(errors="replace")
        has_tests = "pytest" in text or (root / "tests").exists() or (root / "conftest.py").exists()
        scores.append(("python", 2 if has_tests else 1))
    pkgs = _js_packages(root)
    if pkgs:
        has_runner = any(("vitest" in _deps(_read_json(p / "package.json")) or "jest" in _deps(_read_json(p / "package.json"))) for p in pkgs)
        scores.append(("js", 2 if has_runner else 1))
    scores.sort(key=lambda s: -s[1])
    return [name for name, _ in scores]


def _docs(root: Path, extra_dirs=()) -> list:
    names = ["README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "ARCHITECTURE.md"]
    found = []
    for dirpath, files in _walk(root, 3):
        for name in names:
            if name in files:
                found.append((Path(dirpath) / name).relative_to(root).as_posix())
    return found[:12]


# ---------------------------------------------------------------- python

def draft_python(root: Path) -> dict:
    p = load_preset("python")
    venv = root / ".venv" / "bin" / "python"
    python = str(venv) if venv.exists() else "python3"
    env = "PYTHONPATH=src " if (root / "src").is_dir() else "PYTHONPATH=. "
    text = ""
    for f in ("pyproject.toml", "setup.cfg", "requirements-dev.txt", "requirements.txt", "tox.ini"):
        if (root / f).exists():
            text += (root / f).read_text(errors="replace") + "\n"
    install = ""
    for marker, cmd in p["install"].items():
        if _tracked(root, marker):
            install = cmd
            break
    lint = ""
    if "[tool.ruff" in text or (root / "ruff.toml").exists() or (root / ".ruff.toml").exists() or re.search(r"^ruff\b", text, re.M):
        lint = p["lint"]["ruff"]
    elif (root / ".flake8").exists() or "[flake8]" in text:
        lint = p["lint"]["flake8"]
    typecheck = ""
    if "[tool.mypy" in text or (root / "mypy.ini").exists():
        typecheck = p["typecheck"]["mypy"]
    elif (root / "pyrightconfig.json").exists() or "[tool.pyright" in text:
        typecheck = p["typecheck"]["pyright"]
    sub = lambda s: s.replace("{python}", python).replace("{env}", env)  # noqa: E731
    keys = []
    pyproject = (root / "pyproject.toml").read_text(errors="replace") if (root / "pyproject.toml").exists() else ""
    for spec in p["freeze_keys"]:
        section = spec.split("#", 1)[1]
        if f"[{section}]" in pyproject:
            keys.append(spec)
    return {
        "preset": "python",
        "stack": ", ".join(x for x in [
            "Python", "pytest",
            "ruff" if "ruff" in lint else "flake8" if lint else "",
            "mypy" if "mypy" in typecheck else "pyright" if typecheck else "",
            "src layout" if (root / "src").is_dir() else "",
        ] if x),
        "commands": {
            "install": sub(install),
            "lint": sub(lint),
            "typecheck": sub(typecheck),
            "build": "",
            "test": sub(p["test"]),
            "test_files": sub(p["test_files"]),
            "e2e": "",
        },
        "package_dir": ".",
        "freeze_globs": p["freeze_globs"],
        "freeze_keys": keys,
        "docs": _docs(root),
        "acceptance_dir": p["acceptance_dir"],
        "notes": [
            f"Tests run with PYTHONPATH set so the worktree's own code is imported ({env.strip()}).",
            "pytest writes JUnit XML with junit_family=xunit1 so each test carries its file path.",
        ],
    }


# ---------------------------------------------------------------- js

def draft_js(root: Path) -> dict:
    p = load_preset("js")
    pkgs = _js_packages(root)
    if not pkgs:
        pkgs = [root]
    def rank(pkg: Path):
        data = _read_json(pkg / "package.json")
        deps = _deps(data)
        scripts = data.get("scripts") or {}
        return (("vitest" in deps) or ("jest" in deps), "test" in scripts, "build" in scripts, -len(pkg.relative_to(root).parts))
    pkg = sorted(pkgs, key=rank, reverse=True)[0]
    rel = pkg.relative_to(root).as_posix() if pkg != root else "."
    data = _read_json(pkg / "package.json")
    deps = _deps(data)
    scripts = data.get("scripts") or {}
    pm = "pnpm" if _tracked(root, "pnpm-lock.yaml") else "yarn" if _tracked(root, "yarn.lock") else "npm"
    install = ""
    for marker, cmd in p["install"].items():
        if _tracked(root, marker):
            install = cmd
            break
    runner = "vitest" if "vitest" in deps else "jest" if "jest" in deps else ""
    run_script = p["script_runner"][pm]
    def sub(cmd: str) -> str:
        return cmd.replace("cd {pkg} && ", "") if rel == "." else cmd.replace("{pkg}", rel)

    commands = {
        "install": install,
        "lint": sub(f"cd {{pkg}} && {run_script} lint") if "lint" in scripts else "",
        "typecheck": "",
        "build": sub(f"cd {{pkg}} && {run_script} build") if "build" in scripts else "",
        "test": sub(p["runners"][runner]["test"]) if runner else "",
        "test_files": sub(p["runners"][runner]["test_files"]) if runner else "",
        "e2e": "",
    }
    if "typecheck" in scripts:
        commands["typecheck"] = sub(f"cd {{pkg}} && {run_script} typecheck")
    elif (pkg / "tsconfig.json").exists() and "typescript" in deps:
        commands["typecheck"] = sub("cd {pkg} && npx tsc --noEmit")
    if "@playwright/test" in deps:
        commands["e2e"] = sub(p["e2e"]["@playwright/test"])
    prefix = "" if rel == "." else rel + "/"
    globs = [prefix + g if not g.startswith("**") else g for g in p["freeze_globs"]]
    notes = []
    if runner:
        globs += [prefix + g for g in p["runners"][runner]["config_globs"]]
        if p["runners"][runner].get("note"):
            notes.append(p["runners"][runner]["note"])
    for vite in pkg.glob("vite.config.*"):
        if re.search(r"\btest\s*:", vite.read_text(errors="replace")):
            globs.append(prefix + vite.name)
            notes.append(f"{prefix}{vite.name} holds the test config, so it is frozen too; move test settings to vitest.config.* if the implementer needs to change the Vite config.")
    keys = []
    for spec in p["freeze_keys"]:
        key = spec.split("#", 1)[1]
        head = key.split(".")[0]
        if head in data and (key == head or key.split(".")[1] in (data.get(head) or {})):
            keys.append(prefix + spec)
    if not runner:
        notes.append("No test runner found: the first task should be of class bootstrap (add vitest, then set commands.test).")
    return {
        "preset": "js",
        "stack": ", ".join(x for x in [
            "TypeScript" if "typescript" in deps else "JavaScript",
            "React" if "react" in deps else "",
            "Vite" if "vite" in deps else "",
            runner, pm, f"package in {rel}" if rel != "." else "",
        ] if x),
        "commands": commands,
        "package_dir": rel,
        "freeze_globs": globs,
        "freeze_keys": keys,
        "docs": _docs(root),
        "acceptance_dir": (prefix + p["acceptance_dir"]),
        "notes": notes,
    }


def draft(root: Path, preset: str) -> dict:
    if preset == "python":
        return draft_python(root)
    if preset == "js":
        return draft_js(root)
    raise CFError(f"unknown preset {preset!r}")


def _toml_str(s: str) -> str:
    return json.dumps(s)


def render_standards(root: Path, d: dict) -> str:
    repo = Path(root).name
    cmd = d["commands"]
    docs = "\n".join(f"- `{x}`" for x in d["docs"]) or "- (none found; list the docs agents must read)"
    notes = "\n".join(f"- {n}" for n in d.get("notes", [])) or "- (none)"
    lines = [
        f"# Standards — {repo}",
        "",
        "Every CongoForce agent follows this file. The human owns it: edit anything,",
        "then approve with `congoforce standards approve`. Agents never edit it,",
        "except a bootstrap task, which may fill in the test commands.",
        "",
        "## Stack",
        "",
        f"- {d['stack']}",
        f"- Acceptance tests live in `{d['acceptance_dir']}/` unless the repo already has a convention.",
        "",
        "## Conventions",
        "",
        "- Match the style, naming and structure of the surrounding code.",
        "- Reuse existing utilities before adding new ones.",
        "- Keep each commit to one task from tech.md, with the build green after it.",
        "- (add repo-specific rules here: layout, error handling, logging, copy tone)",
        "",
        "## Docs agents should read",
        "",
        docs,
        "",
        "## Gotchas",
        "",
        "- (none yet; Retro proposes additions after each run)",
        "",
        "## Draft notes",
        "",
        notes,
        "",
        "## Commands (machine-readable)",
        "",
        "Each command runs from the task worktree root under `command_timeout`.",
        "`{junit}` is replaced with the JUnit XML path the helper reads; `{files}`",
        "with the test files to run. Leave a command empty to skip it.",
        "",
        "```toml",
        "[preset]",
        f"name = {_toml_str(d['preset'])}",
        "",
        "[commands]",
    ]
    for key in ("install", "lint", "typecheck", "build", "test", "test_files", "e2e"):
        lines.append(f"{key} = {_toml_str(cmd.get(key, ''))}")
    lines += [
        "",
        "[paths]",
        f"package_dir = {_toml_str(d['package_dir'])}",
        "",
        "[freeze]",
        "# Frozen at Gate 2 with the acceptance tests: test config the implementer must not touch.",
        "globs = [" + ", ".join(_toml_str(g) for g in d["freeze_globs"]) + "]",
        "keys = [" + ", ".join(_toml_str(k) for k in d["freeze_keys"]) + "]",
        "```",
        "",
    ]
    return "\n".join(lines)
