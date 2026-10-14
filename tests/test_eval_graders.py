"""The live evals' file graders, checked against stub runs of the same scenarios.

`claude plugin eval` runs real agents and costs tokens, so a grader that names
the wrong file or pattern would only show up there. Each test below drives the
helper through the eval's scenario with stub agents and applies that case's
regex graders to the files the helper wrote.
"""

import re
from pathlib import Path

import pytest

import stub_agents as stub
from conftest import PLUGIN
from test_pipeline import DIAGRAM, drive

EVALS = PLUGIN / "evals"


def regex_graders(case: str) -> dict:
    out = {}
    for f in sorted((EVALS / case / "graders").glob("*.md")):
        head = f.read_text().split("---")[1]
        if re.search(r"^type:\s*regex", head, re.M):
            path = re.search(r"path:\s*([^\s}]+)", head).group(1)
            pattern = re.search(r"^pattern:\s*'(.*)'\s*$", head, re.M).group(1)
            out[f.stem] = (path, pattern)
    return out


def assert_graders_pass(repo, case: str, skip=()):
    graders = regex_graders(case)
    assert graders, f"{case} has no regex graders"
    for name, (path, pattern) in graders.items():
        if name in skip:
            continue
        target = repo.path / path
        assert target.exists(), f"{case}/{name}: {path} was not written"
        assert re.search(pattern, target.read_text(), re.M), f"{case}/{name}: {pattern!r} not found in {path}"


def test_case_files_are_complete():
    for case in sorted(p for p in EVALS.iterdir() if (p / "prompt.md").exists()):
        assert list((case / "graders").glob("*.md")), case.name
        if (case / "case.yaml").exists() and "scaffold_script" in (case / "case.yaml").read_text():
            assert (case / "scaffold.sh").stat().st_mode & 0o111, f"{case.name}/scaffold.sh is not executable"
        for _, (path, pattern) in regex_graders(case.name).items():
            re.compile(pattern)


def test_python_word_count_graders(py_repo):
    task = py_repo.cf("new", "requirements/word-count.md", "--auto-approve", "--set", "create_pr=false")["task"]
    assert drive(py_repo, task)["kind"] == "done"
    assert_graders_pass(py_repo, "python-word-count")


def test_python_bug_fix_graders(py_repo):
    task = py_repo.cf("new", "requirements/title-case-whitespace.md", "--id", "title-case-ws",
                      "--auto-approve", "--set", "create_pr=false")["task"]
    bug = lambda d, wt: (d / "req.md").write_text(stub.REQ.replace("class: task", "class: bug"))  # noqa: E731
    assert drive(py_repo, task, {"requirements": bug})["kind"] == "done"
    assert_graders_pass(py_repo, "python-bug-fix")


def test_python_architecture_tiers_graders(py_repo):
    task = py_repo.cf("new", "requirements/text-stats-cli.md", "--id", "text-stats", "--auto-approve",
                      "--set", "create_pr=false", "--set", "architecture_diagram=always", "--set", "diagram_render=off",
                      "--set", "models.spec=opus", "--set", "models.build=sonnet")["task"]
    tech = lambda d, wt: (d / "tech.md").write_text(stub.TECH.replace("## Interface contract", DIAGRAM.lstrip() + "\n## Interface contract"))  # noqa: E731
    assert drive(py_repo, task, {"tech_spec": tech})["kind"] == "done"
    assert_graders_pass(py_repo, "python-architecture-tiers")


def test_large_task_split_graders(py_repo):
    task = py_repo.cf("new", "requirements/textkit-suite.md", "--id", "textkit-suite", "--auto-approve")["task"]
    large = lambda d, wt: (d / "req.md").write_text(  # noqa: E731
        stub.REQ.replace("size: small", "size: large") + "\n## Suggested split\n- slugify and truncate first.\n")
    assert drive(py_repo, task, {"requirements": large})["kind"] == "stopped"
    assert_graders_pass(py_repo, "large-task-split")


def test_js_clamp_graders_name_real_files():
    # The JS run itself is covered by test_pipeline_js; here only the file names.
    names = {Path(p).name for p, _ in regex_graders("js-clamp").values()}
    assert names <= {"state.json", "checks.json", "verify-review.json", "tests.json"}
