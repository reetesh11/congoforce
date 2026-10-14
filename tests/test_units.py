import json
import textwrap

import pytest

from congoforce import freeze, hooks, junit, tomlish
from congoforce.config import parse_override
from congoforce.packets import criteria
from congoforce.util import CFError, md_section, parse_frontmatter


# ---------------------------------------------------------------- push guard

@pytest.mark.parametrize("cmd", [
    "git push origin main",
    "git push -u origin HEAD:main",
    "git push origin HEAD:refs/heads/master",
    "git push --force origin feature",
    "git push -f origin feature",
    "git push origin +feature",
    "git push --force-with-lease",
    "cd repo && git push origin main",
    "git -C /tmp/x push origin main",
    "GIT_TRACE=1 git push origin main",
    "git push origin :old-branch",
    "git push --delete origin old",
])
def test_push_guard_blocks(cmd):
    assert hooks.check_push(cmd, current_branch="feature")


@pytest.mark.parametrize("cmd", [
    "git push -u origin congoforce/word-count",
    "git push origin HEAD:refs/heads/congoforce/x",
    "pkill -f node && git push origin feature",   # -f belongs to pkill, not to git push
    "git status && echo push",
    "gh pr create --base main --head feature",
    "git push",  # current branch is a feature branch
])
def test_push_guard_allows(cmd):
    assert hooks.check_push(cmd, current_branch="feature") == ""


def test_push_guard_reads_repo_protected_branches(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".congoforce").mkdir()
    (tmp_path / ".congoforce" / "config.toml").write_text('[congoforce]\nprotected_branches = ["trunk"]\n')
    protected = hooks._protected_branches(str(tmp_path))
    assert protected == ["trunk"]
    assert hooks.check_push("git push origin trunk", "feature", protected)
    assert hooks.check_push("git push origin main", "feature", protected) == ""
    assert hooks._protected_branches(str(tmp_path / "missing")) is None


def test_push_guard_bare_push_on_main():
    assert hooks.check_push("git push", current_branch="main")
    assert hooks.check_push("git push origin", current_branch="main")


# ---------------------------------------------------------------- freeze guard

def _frozen_repo(tmp_path, stage="implement", cls="task"):
    root = tmp_path / "repo"
    task = root / ".congoforce" / "tasks" / "t1"
    task.mkdir(parents=True)
    (task / "state.json").write_text(json.dumps({"task": "t1", "stage": stage, "frozen": True, "class": cls}))
    (task / "frozen.json").write_text(json.dumps({
        "files": {"tests/acceptance/test_a.py": "x", "conftest.py": "y"},
        "globs": ["**/conftest.py", "pytest.ini"],
        "keys": {"pyproject.toml#tool.pytest.ini_options": "z"},
    }))
    wt = root / ".congoforce" / "worktrees" / "t1"
    wt.mkdir(parents=True)
    return root, wt


def test_freeze_guard_blocks_frozen_files(tmp_path):
    root, wt = _frozen_repo(tmp_path)
    assert "frozen" in hooks.check_file_write(str(wt / "tests/acceptance/test_a.py"), True)
    assert "frozen" in hooks.check_file_write(str(wt / "pkg/sub/conftest.py"), True)  # new file matching a glob
    assert hooks.check_file_write(str(wt / "pyproject.toml"), True) == ""  # keys are hashed, file stays editable
    assert hooks.check_file_write(str(wt / "textkit/words.py"), True) == ""


def test_freeze_guard_protects_state_and_standards(tmp_path):
    root, wt = _frozen_repo(tmp_path)
    assert "owned by the congoforce helper" in hooks.check_file_write(str(root / ".congoforce/tasks/t1/state.json"), False)
    assert "belong to the human" in hooks.check_file_write(str(root / ".congoforce/standards.md"), True)
    assert hooks.check_file_write(str(root / ".congoforce/standards.md"), False) == ""  # the human/orchestrator may edit
    assert "belong to the human" in hooks.check_file_write(str(wt / ".congoforce/standards.md"), True)


def test_freeze_guard_allows_bootstrap_standards(tmp_path):
    root, wt = _frozen_repo(tmp_path, cls="bootstrap")
    assert hooks.check_file_write(str(wt / ".congoforce/standards.md"), True) == ""


def test_freeze_guard_bash(tmp_path):
    root, wt = _frozen_repo(tmp_path)
    assert hooks.check_bash_write("sed -i '' s/2/4/ tests/acceptance/test_a.py", str(wt))
    assert hooks.check_bash_write("echo x > tests/acceptance/test_a.py", str(root))
    assert hooks.check_bash_write("cat tests/acceptance/test_a.py", str(wt)) == ""
    assert hooks.check_bash_write("echo x > src/a.py", str(wt)) == ""


def test_freeze_guard_bash_scoped_to_own_task(tmp_path):
    root, wt = _frozen_repo(tmp_path)
    other = root / ".congoforce" / "worktrees" / "t2"
    other.mkdir(parents=True)
    # A stacked task may delete or rewrite files that only another task froze.
    assert hooks.check_bash_write("git rm tests/acceptance/test_a.py", str(other)) == ""
    # Naming t1's worktree copy from elsewhere is still blocked.
    assert hooks.check_bash_write(f"rm {wt}/tests/acceptance/test_a.py", str(other))
    # Agents usually run from the repo root and cd into their worktree.
    assert hooks.check_bash_write(f"cd {other} && git rm tests/acceptance/test_a.py", str(root)) == ""
    assert hooks.check_bash_write(f"git -C {other} rm tests/acceptance/test_a.py", str(root)) == ""
    assert hooks.check_bash_write(f"cd {wt} && git rm tests/acceptance/test_a.py", str(root))


def test_stage_guard(tmp_path, capsys, monkeypatch):
    root, wt = _frozen_repo(tmp_path)
    data = {"cwd": str(root), "tool_input": {"subagent_type": "congoforce:verifier", "prompt": "CONGOFORCE_TASK: t1\n"}}
    hooks.stage_guard(data)
    out = capsys.readouterr().out
    assert "deny" in out and "expects congoforce:implementer" in out
    data["tool_input"]["subagent_type"] = "congoforce:implementer"
    hooks.stage_guard(data)
    assert capsys.readouterr().out == ""
    data["tool_input"]["prompt"] = "do something"
    hooks.stage_guard(data)
    assert "CONGOFORCE_TASK" in capsys.readouterr().out
    hooks.stage_guard({"cwd": str(root), "tool_input": {"subagent_type": "Explore", "prompt": "x"}})
    assert capsys.readouterr().out == ""


def test_context_guard(capsys):
    hooks.context_guard({"agent_type": "congoforce:test-author", "tool_input": {"file_path": "/r/.congoforce/tasks/t/tech.md"}})
    assert "interface-contract" in capsys.readouterr().out
    hooks.context_guard({"agent_type": "congoforce:implementer", "tool_input": {"file_path": "/r/.congoforce/tasks/t/tech.md"}})
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------- junit

VITEST_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<testsuites name="vitest tests" tests="3" failures="2" errors="0" time="0.5">
    <testsuite name="src/__acceptance__/clamp.test.js" timestamp="x" hostname="h" tests="2" failures="1" errors="0" skipped="0" time="0.01">
        <testcase classname="src/__acceptance__/clamp.test.js" name="clamp &gt; returns min below range" time="0.002">
            <failure message="clamp is not a function" type="TypeError">TypeError: clamp is not a function
 ❯ src/__acceptance__/clamp.test.js:5:12</failure>
        </testcase>
        <testcase classname="src/__acceptance__/clamp.test.js" name="clamp &gt; keeps value" time="0.001"></testcase>
    </testsuite>
    <testsuite name="src/math.test.js" tests="1" failures="0" errors="0" skipped="1" time="0">
        <testcase classname="src/math.test.js" name="sum &gt; adds" time="0"><skipped/></testcase>
    </testsuite>
</testsuites>"""


def test_junit_vitest(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text(VITEST_XML)
    cases = junit.parse(p)
    assert [c.status for c in cases] == ["failed", "passed", "skipped"]
    assert junit.case_matches_file(cases[0], "src/__acceptance__/clamp.test.js")
    assert junit.case_matches_file(cases[0], "apps/web/src/__acceptance__/clamp.test.js")  # package_dir prefix
    assert not junit.case_matches_file(cases[2], "src/__acceptance__/clamp.test.js")
    assert junit.signature(cases[0]) == "test:src/__acceptance__/clamp.test.js::clamp > returns min below range|clamp is not a function"


def test_junit_pytest_dotted_and_collection(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text("""<testsuites><testsuite name="pytest">
      <testcase classname="tests.acceptance.test_x.TestThing" name="test_a"/>
      <testcase classname="" name="tests.acceptance.test_y"><error message="collection failure">ImportError: cannot import name 'f'</error></testcase>
    </testsuite></testsuites>""")
    a, b = junit.parse(p)
    assert junit.case_matches_file(a, "tests/acceptance/test_x.py")
    assert not junit.case_matches_file(a, "tests/acceptance/test_y.py")
    assert junit.case_matches_file(b, "tests/acceptance/test_y.py")
    assert "ImportError" in b.message


def test_normalise_strips_noise():
    m = "AssertionError at 0x7f3a2b in /Users/me/x/y.py:42 after 12ms"
    assert junit.normalise(m) == "AssertionError at 0x? in <path>:<n> after <t>"


# ---------------------------------------------------------------- toml, freeze, docs

def test_tomlish_fallback():
    text = textwrap.dedent('''
        # comment
        [commands]
        test = "pytest -q --junitxml={junit}"  # trailing
        empty = ""
        [freeze]
        globs = [
          "**/conftest.py",   # multi-line
          "pytest.ini",
        ]
        keys = []
        [congoforce]
        max_iterations = 5
        push = false
        name = 'lit # not a comment'
        esc = "a\\"b"
    ''')
    data = tomlish._fallback_loads(text)
    assert data["commands"]["test"] == "pytest -q --junitxml={junit}"
    assert data["freeze"]["globs"] == ["**/conftest.py", "pytest.ini"]
    assert data["congoforce"]["max_iterations"] == 5 and data["congoforce"]["push"] is False
    assert data["congoforce"]["name"] == "lit # not a comment"
    assert data["congoforce"]["esc"] == 'a"b'


def test_freeze_globs_and_keys(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "conftest.py").write_text("x")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}))
    fz = freeze.compute(tmp_path, [], ["**/conftest.py"], ["package.json#scripts.test"])
    assert "a/b/conftest.py" in fz["files"]
    assert freeze.check(tmp_path, fz) == []
    # Changing an unrelated key is fine; changing the frozen key is caught.
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "build": "vite build --x"}}))
    assert freeze.check(tmp_path, fz) == []
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run --passWithNoTests"}}))
    assert freeze.check(tmp_path, fz) == ["package.json#scripts.test: changed"]
    (tmp_path / "conftest.py").write_text("new")
    assert any("added" in p for p in freeze.check(tmp_path, fz))


def test_docs_helpers():
    meta, body = parse_frontmatter("---\nclass: Bug\ntitle: \"X y\"\n---\n# T\n## Problem\nIt breaks.\n## Other\nz\n")
    assert meta == {"class": "Bug", "title": "X y"}
    assert md_section(body, "problem") == "It breaks."
    assert criteria("- **AC-1**: a\n- AC-2. b\n1. AC-3 c\n- AC-1 dup") == [("AC-1", "a"), ("AC-2", "b"), ("AC-3", "c")]


def test_parse_override():
    assert parse_override("max_iterations=3") == ("max_iterations", 3)
    assert parse_override("push=false") == ("push", False)
    assert parse_override("post_pr=/seo-review {pr},echo hi") == ("post_pr", ["/seo-review {pr}", "echo hi"])
    with pytest.raises(CFError):
        parse_override("nope=1")


# ---------------------------------------------------------------- model tiers

def _cfg_repo(tmp_path, monkeypatch, toml="", user=None):
    from congoforce import config
    from congoforce.paths import Paths
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    if user:
        config.sync_user_config([f"{k}={v}" for k, v in user.items()])
    (tmp_path / ".congoforce").mkdir(exist_ok=True)
    if toml:
        (tmp_path / ".congoforce" / "config.toml").write_text(toml)
    return config, Paths(tmp_path)


def test_models_default_to_inherit(tmp_path, monkeypatch):
    config, paths = _cfg_repo(tmp_path, monkeypatch)
    assert set(config.load(paths)["models"].values()) == {""}


def test_model_tiers_layer_and_role_beats_tier(tmp_path, monkeypatch):
    config, paths = _cfg_repo(tmp_path, monkeypatch, user={"default_model": "sonnet", "spec_model": "opus"},
                              toml='[models]\nbuild = "haiku"\nverifier = "sonnet"\n')
    m = config.load(paths)["models"]
    assert m["requirements"] == m["tech-spec"] == m["test-author"] == "opus"
    assert m["implementer"] == "haiku" and m["verifier"] == "sonnet"
    # A per-run tier beats the repo file's role setting (later layers win); inherit means the session model.
    m = config.load(paths, dict([config.parse_override("models.build=opus"), config.parse_override("models.tech_spec=inherit")]))["models"]
    assert m["implementer"] == m["verifier"] == "opus" and m["tech-spec"] == "" and m["requirements"] == "opus"


def test_custom_tier(tmp_path, monkeypatch):
    config, paths = _cfg_repo(tmp_path, monkeypatch,
                              toml='[model_tiers]\nreview = ["verifier", "test_author"]\n[models]\nreview = "opus"\nbuild = "haiku"\n')
    m = config.load(paths)["models"]
    assert m["verifier"] == "opus" and m["test-author"] == "opus" and m["implementer"] == "haiku"


@pytest.mark.parametrize("toml, msg", [
    ('[models]\nimplementor = "haiku"\n', "not a role, a tier"),
    ('[models]\nbuild = "gpt-4"\n', "use one of"),
    ('[model_tiers]\nspec = ["planner"]\n', "unknown roles"),
    ('[congoforce]\narchitecture_diagram = "huge"\n', "architecture_diagram"),
])
def test_bad_model_config_is_rejected(tmp_path, monkeypatch, toml, msg):
    config, paths = _cfg_repo(tmp_path, monkeypatch, toml=toml)
    with pytest.raises(CFError, match=msg):
        config.load(paths)


# ---------------------------------------------------------------- diagrams

from congoforce import diagram  # noqa: E402

TECH_WITH_DIAGRAM = "## Approach\nx\n\n## Architecture\n\n```mermaid\n%% overview\nflowchart LR\n  a --> b\n```\n\n## Interface contract\n- f()\n"


@pytest.mark.parametrize("mode, size, requested, need", [
    ("off", "large", "large", False),
    ("always", "small", "small", True),
    ("large", "medium", "medium", False),
    ("large", "medium", "large", True),  # split declined: still a large task
    ("medium", "medium", "medium", True),
    ("medium", "small", "small", False),
])
def test_diagram_required(mode, size, requested, need):
    assert diagram.required({"architecture_diagram": mode}, {"size": size, "size_requested": requested}) is need


def test_diagram_blocks_and_headers():
    assert diagram.blocks(TECH_WITH_DIAGRAM) == ["%% overview\nflowchart LR\n  a --> b\n"]
    assert diagram.blocks("## Interface contract\n```mermaid\nflowchart LR\n```\n") == []  # outside the section
    assert diagram.header_error("---\ntitle: x\n---\nsequenceDiagram\n  A->>B: hi\n") == ""
    assert "use one of" in diagram.header_error("graphh TD\n")
    assert diagram.header_error("\n%% only a comment\n") == "is empty"


def test_diagram_process(tmp_path):
    cfg = {"architecture_diagram": "always", "diagram_render": "off", "command_timeout": 30}
    assert "needs a `## Architecture`" in diagram.process(cfg, {"size": "small"}, "## Tasks\n1. x\n", tmp_path)["error"]
    res = diagram.process(cfg, {"size": "small"}, TECH_WITH_DIAGRAM, tmp_path)
    assert res["error"] == "" and res["files"] == ["architecture.mmd"] and (tmp_path / "architecture.mmd").exists()
    # A renderer that reports a parse error rejects the diagram; any other failure is only a note.
    cfg["diagram_render"] = "echo 'Error: Parse error on line 2:' && exit 1"
    assert "Parse error on line 2" in diagram.process(cfg, {}, TECH_WITH_DIAGRAM, tmp_path)["error"]
    cfg["diagram_render"] = "echo 'Failed to launch the browser process' && exit 1"
    res = diagram.process(cfg, {}, TECH_WITH_DIAGRAM, tmp_path)
    assert res["error"] == "" and "not rendered" in res["note"]
    cfg["diagram_render"] = "cp {in} {out}"
    assert diagram.process(cfg, {}, TECH_WITH_DIAGRAM, tmp_path)["rendered"] == ["architecture.svg"]


# ---------------------------------------------------------------- heredocs

PUSH_LINE = "git push -u origin main"


@pytest.mark.parametrize("cmd", [
    f"cat > scaffold.sh <<'EOF'\n{PUSH_LINE}\nEOF",
    f"cat > a.sh <<EOF && chmod +x a.sh\n{PUSH_LINE}\nEOF\necho done",
    f"tee notes.md <<\"END\" >/dev/null\n{PUSH_LINE}\nEND",
    f"cat > a <<-EOF\n\t{PUSH_LINE}\n\tEOF",
    f"cat > a <<A > b <<B\n{PUSH_LINE}\nA\n{PUSH_LINE}\nB",
])
def test_push_guard_ignores_heredoc_text(cmd):
    assert hooks.check_push(cmd, current_branch="feature") == ""


@pytest.mark.parametrize("cmd", [
    f"bash <<'EOF'\n{PUSH_LINE}\nEOF",            # the body runs
    f"sh -s <<EOF\n{PUSH_LINE}\nEOF",
    f"cat <<EOF | bash\n{PUSH_LINE}\nEOF",
    f"eval $(cat <<EOF\n{PUSH_LINE}\nEOF\n)",
    f"cat > a <<'EOF'\nhi\nEOF\n{PUSH_LINE}",     # after the terminator
    f"echo 'x <<EOF'\n{PUSH_LINE}\nEOF",           # << inside quotes is not a heredoc
    f"git push origin main <<EOF\nEOF",
])
def test_push_guard_still_sees_real_pushes(cmd):
    assert hooks.check_push(cmd, current_branch="feature")


def test_freeze_guard_ignores_heredoc_text_but_not_targets(tmp_path):
    root, wt = _frozen_repo(tmp_path)
    assert hooks.check_bash_write("cat > NOTES.md <<'EOF'\nsee tests/acceptance/test_a.py\nEOF", str(wt)) == ""
    assert hooks.check_bash_write("cat > tests/acceptance/test_a.py <<'EOF'\nx\nEOF", str(wt))
