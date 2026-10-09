"""Drive the helper through whole runs with stub agents on the Python fixture."""

import json
import subprocess

import stub_agents as stub
from conftest import git

AGENTS = {
    "requirements": stub.requirements,
    "tech_spec": stub.tech_spec,
    "test_author": stub.test_author,
    "implement": stub.implement,
    "review": stub.review,
}


def drive(repo, task, overrides=None, max_steps=60):
    """Follow `next` until a terminal stage or a gate the test must answer."""
    overrides = overrides or {}
    for _ in range(max_steps):
        act = repo.cf("next", task)
        kind, stage = act["kind"], act["stage"]
        if kind in ("done", "stopped") or (kind == "gate" and stage not in overrides.get("auto_gates", ())):
            return act
        if kind == "helper":
            repo.cf("advance", task)
        elif kind == "agent":
            st = repo.state(task)
            wt = repo.path / ".congoforce" / "worktrees" / task
            fn = overrides.get(stage, AGENTS[stage])
            fn(repo.task_dir(task), wt)
            repo.cf("complete", task, stage, "--tokens", "1000")
        elif kind == "explore":
            (repo.task_dir(task) / "map-summaries.json").write_text(json.dumps({m: f"summary of {m}" for m in act["modules"]}))
            repo.cf("complete", task, stage)
        elif kind in ("skills", "retro"):
            repo.cf("complete", task, stage, "--summary", "ok")
        elif kind == "gate":
            repo.cf("gate", task, stage, "approve")
        else:
            raise AssertionError(f"unexpected action {act}")
    raise AssertionError("pipeline did not finish")


def test_happy_path_with_gates(py_repo):
    r = py_repo
    out = r.cf("new", "requirements/word-count.md", "--set", "create_pr=false")
    task = out["task"]
    assert task == "word-count"
    act = r.cf("next", task)
    assert act["kind"] == "gate" and act["gate"] == "standards"
    std = (r.path / ".congoforce" / "standards.md").read_text()
    assert ".venv/bin/python" in std and "junit_family=xunit1" in std
    r.cf("gate", task, "standards", "approve")

    act = r.cf("next", task)
    assert act["kind"] == "agent" and act["agent"] == "congoforce:requirements"
    assert "CONGOFORCE_TASK: word-count" in act["prompt"]
    act = drive(r, task)
    assert act["gate"] == "gate1"
    assert "AC-3" in (r.task_dir(task) / "gate1-packet.md").read_text()
    r.cf("gate", task, "gate1", "approve")

    act = drive(r, task)
    assert act["gate"] == "gate2", act
    packet = (r.task_dir(task) / "gate2-packet.md").read_text()
    assert "All acceptance tests are red for the right reason" in packet, packet
    red = json.loads((r.task_dir(task) / "red.json").read_text())
    assert red["ok"], red
    r.cf("gate", task, "gate2", "approve")
    assert r.state(task)["stage"] == "freeze"
    r.cf("advance", task)

    st = r.state(task)
    assert st["stage"] == "implement" and st["frozen"]
    frozen = json.loads((r.task_dir(task) / "frozen.json").read_text())
    assert "tests/acceptance/test_word_count.py" in frozen["files"]
    assert "pyproject.toml#tool.pytest.ini_options" in frozen["keys"]

    act = drive(r, task)
    assert act["gate"] == "ship_confirm"
    body = (r.task_dir(task) / "pr-body.md").read_text()
    assert "AC-2" in body and "regressions against baseline | none" in body
    r.cf("gate", task, "ship_confirm", "approve")
    act = drive(r, task)
    assert act["kind"] == "done", act
    st = r.state(task)
    assert st["usage"]["implement"] == 1000
    # The branch reached the remote, with the frozen tests and the history docs.
    files = git(["ls-tree", "-r", "--name-only", "congoforce/word-count"], r.remote)
    assert "tests/acceptance/test_word_count.py" in files
    assert ".congoforce/history/word-count/req.md" in files
    assert ".congoforce/history/word-count/verify-report.md" in files
    # main was never touched
    assert git(["rev-list", "--count", "main"], r.remote) == "1"


def test_red_check_rejects_tests_that_already_pass(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--auto-approve", "--set", "create_pr=false")["task"]
    early = lambda d, wt: stub.test_author(d, wt, early_pass=True)  # noqa: E731
    act = drive(r, task, {"test_author": early, "auto_gates": ()})
    # Two red-check attempts, then the human decides at Gate 2 (auto-approved here).
    log = (r.task_dir(task) / "run-log.md").read_text()
    assert "red check failed (attempt 1)" in log
    assert "red check still failing" in log
    red = json.loads((r.task_dir(task) / "red.json").read_text())
    assert any("already pass before implementation" in p for p in red["problems"])


def test_tampering_with_frozen_test_escalates(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--auto-approve", "--set", "create_pr=false")["task"]

    def cheat(d, wt):
        stub.implement(d, wt, broken=True)
        f = wt / "tests" / "acceptance" / "test_word_count.py"
        f.write_text(f.read_text().replace("== 2", "== 4"))
        subprocess.run(["git", "commit", "-qam", "tweak test"], cwd=wt, check=True)

    act = drive(r, task, {"implement": cheat})
    assert act["kind"] == "stopped"  # auto-approve never decides an escalation
    st = r.state(task)
    assert "process violation" in st["escalation"]["reason"]


def test_same_failure_twice_escalates(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--auto-approve", "--set", "create_pr=false")["task"]
    calls = {"n": 0}

    def broken(d, wt):
        calls["n"] += 1
        if calls["n"] == 1:
            stub.implement(d, wt, broken=True)
        else:  # a no-op "fix" commit: same failure again
            (wt / "NOTES.md").write_text(f"attempt {calls['n']}\n")
            subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
            subprocess.run(["git", "commit", "-qm", "try again"], cwd=wt, check=True)

    act = drive(r, task, {"implement": broken})
    st = r.state(task)
    assert act["kind"] == "stopped"
    assert st["escalation"]["reason"].startswith("same failure twice")
    assert st["iteration"] == 2
    assert (r.task_dir(task) / "feedback" / "iter-2.md").exists()


def test_escalation_choice_code_gives_more_iterations(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--set", "create_pr=false", "--set", "max_iterations=1")["task"]
    r.cf("gate", task, "standards", "approve")
    drive(r, task)
    r.cf("gate", task, "gate1", "approve")
    drive(r, task)
    r.cf("gate", task, "gate2", "approve")
    act = drive(r, task, {"implement": lambda d, wt: stub.implement(d, wt, broken=True)})
    assert act["gate"] == "escalated"
    assert "iteration cap" in r.state(task)["escalation"]["reason"]
    r.cf("gate", task, "escalated", "code", "--note", "punctuation-only tokens must not count")
    st = r.state(task)
    assert st["stage"] == "implement" and st["max_iterations"] == 3
    fb = (r.task_dir(task) / "feedback" / f"iter-{st['iteration']}.md").read_text()
    assert "punctuation-only tokens" in fb
    act = drive(r, task)  # the real fix this time
    assert act["gate"] == "ship_confirm"


def test_stage_guard_and_validation(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--auto-approve")["task"]
    # Completing a stage that is not current is refused.
    res = r.cf("complete", task, "implement", ok=False)
    assert "error" in res and "not implement" in res["error"]
    # A requirements doc without acceptance criteria is rejected, with the reason fed back.
    (r.task_dir(task) / "req.md").write_text("---\nclass: task\nsize: small\ntitle: x\n---\n# nothing\n")
    res = r.cf("complete", task, "requirements", ok=False)
    assert "acceptance criteria" in res["error"]
    act = r.cf("next", task)
    assert "previous attempt was rejected" in act["prompt"]


def test_status_and_dry_run(py_repo):
    r = py_repo
    task = r.cf("new", "requirements/word-count.md", "--auto-approve", "--set", "push=false")["task"]
    act = drive(r, task)
    assert act["kind"] == "done" and "dry run" in act["summary"]
    rows = r.cf("status", "--json")
    assert rows[0]["task"] == task and rows[0]["stage"] == "done"
