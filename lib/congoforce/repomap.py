"""Repo map: deterministic facts plus short per-module summaries.

Facts come from git and manifests. Summaries come from the read-only Explore
agent, only for modules whose git tree hash changed since the last map, and
are cached in .congoforce/tasks/.map-summaries.json.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections import Counter
from pathlib import Path

from . import runner
from .gitops import git
from .util import now, read_json, write_json, write_text

MAX_STALE = 12
TEST_RX = re.compile(r"(^|/)(tests?|__tests__|spec|__acceptance__)(/|$)|(_test|\.test|\.spec|^test_)[^/]*$|/test_[^/]*$")
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}


def _files(wt: Path) -> list:
    out = git(["ls-files"], wt, check=False)
    return [f for f in out.splitlines() if f]


def module_roots(wt: Path, package_dir: str) -> Path:
    pkg = Path(package_dir or ".")
    for cand in (pkg / "src", Path("src"), pkg, Path(".")):
        if (Path(wt) / cand).is_dir():
            return cand
    return Path(".")


def modules(wt: Path, package_dir: str) -> list:
    root = module_roots(wt, package_dir)
    files = _files(wt)
    prefix = "" if str(root) == "." else root.as_posix() + "/"
    names = set()
    for f in files:
        if not f.startswith(prefix):
            continue
        rest = f[len(prefix):]
        if "/" in rest:
            top = rest.split("/", 1)[0]
            if not top.startswith(".") and top not in ("node_modules", "tests", "test", "__tests__", "docs"):
                names.add(prefix + top)
    return sorted(names)[:60]


def tree_hash(wt: Path, path: str) -> str:
    return git(["rev-parse", f"HEAD:{path}"], wt, check=False)


def stale_modules(paths, wt: Path, package_dir: str) -> list:
    cache = read_json(paths.map_summaries, {}) or {}
    stale = []
    for m in modules(wt, package_dir):
        h = tree_hash(wt, m)
        if not h:
            continue
        if cache.get(m, {}).get("hash") != h:
            stale.append({"module": m, "hash": h})
    return stale[:MAX_STALE]


def store_summaries(paths, wt: Path, summaries: dict) -> None:
    cache = read_json(paths.map_summaries, {}) or {}
    for module, text in summaries.items():
        cache[module] = {"hash": tree_hash(wt, module), "summary": str(text).strip(), "at": now()}
    write_json(paths.map_summaries, cache)


def build(paths, wt: Path, std: dict, cfg: dict) -> str:
    files = _files(wt)
    sha = git(["rev-parse", "HEAD"], wt, check=False)
    lines = [f"<!-- congoforce repo-map sha={sha} generated={now()} -->", "# Repo map", ""]
    # Layout
    tops = Counter()
    for f in files:
        parts = f.split("/")
        key = "/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else "(root files)")
        tops[key] += 1
    lines += ["## Layout", "", "| Path | Files |", "| --- | --- |"]
    for key, n in sorted(tops.items())[:60]:
        lines.append(f"| `{key}` | {n} |")
    # Manifests and entry points
    lines += ["", "## Manifests and entry points", ""]
    for f in files:
        name = Path(f).name
        if name == "package.json" and "node_modules" not in f:
            try:
                data = json.loads((Path(wt) / f).read_text())
            except Exception:
                continue
            scripts = ", ".join(f"`{k}`" for k in (data.get("scripts") or {}))
            entry = data.get("main") or data.get("module") or data.get("bin") or ""
            lines.append(f"- `{f}`: {data.get('name', '')} — scripts: {scripts or 'none'}" + (f"; entry `{entry}`" if entry else ""))
        elif name in ("pyproject.toml", "setup.cfg", "setup.py"):
            text = (Path(wt) / f).read_text(errors="replace")
            m = re.search(r"^\[project\.scripts\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
            scripts = ", ".join(x.split("=")[0].strip() for x in (m.group(1).strip().splitlines() if m else []) if "=" in x)
            lines.append(f"- `{f}`" + (f" — console scripts: {scripts}" if scripts else ""))
    for f in files:
        if re.search(r"(^|/)(__main__\.py|main\.(py|[jt]sx?)|index\.(html|[jt]sx?)|app\.(py|[jt]sx?))$", f) and "test" not in f:
            lines.append(f"- entry: `{f}`")
    # Tests
    tests = [f for f in files if TEST_RX.search(f) and Path(f).suffix in CODE_EXT]
    dirs = Counter(str(Path(f).parent) for f in tests)
    lines += ["", "## Tests", "", f"{len(tests)} test files."]
    for d, n in dirs.most_common(15):
        lines.append(f"- `{d}/`: {n}")
    # Commands
    lines += ["", "## Commands (from standards.md)", ""]
    for k, v in std["commands"].items():
        if v:
            lines.append(f"- {k}: `{v}`")
    # Modules
    cache = read_json(paths.map_summaries, {}) or {}
    mods = modules(wt, std.get("package_dir", "."))
    lines += ["", "## Modules", ""]
    for m in mods:
        n = sum(1 for f in files if f.startswith(m + "/"))
        summary = (cache.get(m) or {}).get("summary", "")
        lines.append(f"### `{m}/` ({n} files)")
        lines.append(summary or "_No summary yet._")
        lines.append("")
    backend = cfg.get("repo_map_backend", "builtin")
    if backend and backend != "builtin":
        res = runner.run(f"{backend} --repo {shlex.quote(str(wt))}", wt, int(cfg.get("command_timeout", 600)))
        lines += [f"## From backend `{backend}`", "", res["output"] if res["ok"] else f"_backend failed: {res['tail']}_"]
    return "\n".join(lines) + "\n"


def write(paths, wt: Path, std: dict, cfg: dict, task_dir: Path = None) -> str:
    text = build(paths, wt, std, cfg)
    write_text(paths.repomap, text)
    if task_dir:
        write_text(Path(task_dir) / "repo-map.md", text)
    return text
