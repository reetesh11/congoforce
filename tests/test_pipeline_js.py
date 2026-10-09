"""The same pipeline on the JS fixture with real vitest (needs npm; skipped offline)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import PLUGIN, Repo, git
from test_pipeline import drive

pytestmark = pytest.mark.skipif(shutil.which("npm") is None, reason="npm not installed")

REQ = """---
class: task
size: small
title: Add clamp to math
---
# Requirements — clamp

## Problem
Callers need to keep a number inside a range.

## Acceptance criteria
- AC-1: `clamp(5, 0, 10)` returns 5; `clamp(-1, 0, 10)` returns 0; `clamp(11, 0, 10)` returns 10.
- AC-2: `clamp(1, 10, 0)` throws a RangeError.
- AC-3: `sum` keeps working.

## Open questions
- none
"""

TECH = """# Tech

## Interface contract
- `export function clamp(value: number, min: number, max: number): number` in `src/math.js`.

## Tasks
1. Add `clamp` to `src/math.js`.
"""

ACC = """import { describe, expect, it } from "vitest";
import { clamp } from "../math.js";

describe("clamp", () => {
  it("keeps values in range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(11, 0, 10)).toBe(10);
  });
  it("throws when min > max", () => {
    expect(() => clamp(1, 10, 0)).toThrow(RangeError);
  });
});
"""

UNCHANGED = """import { expect, it } from "vitest";
import { sum } from "../math.js";

it("sum still adds", () => {
  expect(sum([2, 3])).toBe(5);
});
"""


def requirements(d, wt):
    (d / "req.md").write_text(REQ)


def tech_spec(d, wt):
    (d / "tech.md").write_text(TECH)


def write_tests(d, wt):
    acc = wt / "src" / "__acceptance__"
    acc.mkdir(parents=True, exist_ok=True)
    (acc / "clamp.test.js").write_text(ACC)
    (acc / "sum-unchanged.test.js").write_text(UNCHANGED)
    (d / "tests.json").write_text(json.dumps({"acceptance": [
        {"criterion": "AC-1", "file": "src/__acceptance__/clamp.test.js", "tests": 2},
        {"criterion": "AC-2", "file": "src/__acceptance__/clamp.test.js", "tests": 2},
        {"criterion": "AC-3", "file": "src/__acceptance__/sum-unchanged.test.js", "tests": 1, "expect_red": False},
    ]}))
    (d / "test.md").write_text("# Tests\n")


def implement(d, wt):
    p = wt / "src" / "math.js"
    p.write_text(p.read_text() + """
/** Keep value inside [min, max]. */
export function clamp(value, min, max) {
  if (min > max) throw new RangeError("min must be <= max");
  return Math.min(max, Math.max(min, value));
}
""")
    subprocess.run(["git", "commit", "-qam", "Add clamp"], cwd=wt, check=True)


def implement_with_console(d, wt):
    implement(d, wt)
    p = wt / "src" / "math.js"
    p.write_text(p.read_text().replace("Keep value", "Keep value") + "\nconsole.log('debug');\n")
    subprocess.run(["git", "commit", "-qam", "debug"], cwd=wt, check=True)


def review(d, wt):
    (d / "verify-review.json").write_text(json.dumps({"result": "PASS", "unmet": [], "findings": []}))
    (d / "verify-report.md").write_text("# ok\n")


@pytest.fixture
def js_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(PLUGIN / "fixtures" / "js-mini", repo)
    res = subprocess.run(["npm", "install", "--silent", "--no-audit", "--no-fund"], cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"npm install failed (offline?): {res.stderr[-300:]}")
    git(["init", "-q", "-b", "main"], repo)
    git(["add", "-A"], repo)  # package-lock.json committed; node_modules ignored
    git(["-c", "user.email=t@e", "-c", "user.name=T", "commit", "-qm", "init"], repo)
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "xdg"), GIT_AUTHOR_NAME="T", GIT_COMMITTER_NAME="T",
               GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_EMAIL="t@e")
    return Repo(repo, env)


AGENTS = {"requirements": requirements, "tech_spec": tech_spec, "test_author": write_tests, "implement": implement, "review": review}


def test_js_happy_path(js_repo):
    r = js_repo
    task = r.cf("new", "requirements/clamp.md", "--auto-approve")["task"]
    std = (r.path / ".congoforce" / "standards.md").read_text()
    assert 'install = "npm ci"' in std and "vitest run" in std
    act = drive(r, task, AGENTS)
    red = json.loads((r.task_dir(task) / "red.json").read_text())
    assert red["ok"], red
    assert act["kind"] == "done", act
    assert "no git remote" in act["summary"]
    checks = json.loads((r.task_dir(task) / "checks.json").read_text())
    assert checks["passed"] and checks["test_summary"]["passed"] == 5


def test_js_new_lint_error_loops_back(js_repo):
    r = js_repo
    task = r.cf("new", "requirements/clamp.md", "--auto-approve", "--set", "max_iterations=1")["task"]
    act = drive(r, task, {**AGENTS, "implement": implement_with_console})
    st = r.state(task)
    assert act["kind"] == "stopped"
    assert "iteration cap" in st["escalation"]["reason"]
    assert any(s.startswith("cmd:lint|") for s in st["escalation"]["signatures"])
