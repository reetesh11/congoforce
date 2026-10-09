import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
BIN = PLUGIN / "bin" / "congoforce"
sys.path.insert(0, str(PLUGIN / "lib"))

# The helper must run on the oldest supported Python; prefer the system 3.9 when present.
HELPER_PY = os.environ.get("CONGOFORCE_TEST_PYTHON") or ("/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Repo:
    def __init__(self, path: Path, env: dict):
        self.path = path
        self.env = env

    def cf(self, *args, ok=True):
        res = subprocess.run([HELPER_PY, str(BIN), *args], cwd=self.path, capture_output=True, text=True, env=self.env)
        if ok and res.returncode != 0:
            raise AssertionError(f"congoforce {' '.join(args)} failed:\n{res.stdout}\n{res.stderr}")
        try:
            return json.loads(res.stdout)
        except ValueError:
            return res.stdout

    def state(self, task):
        return json.loads((self.path / ".congoforce" / "tasks" / task / "state.json").read_text())

    def task_dir(self, task):
        return self.path / ".congoforce" / "tasks" / task


@pytest.fixture
def py_repo(tmp_path):
    src = PLUGIN / "fixtures" / "python-mini"
    repo = tmp_path / "repo"
    shutil.copytree(src, repo)
    # The fixture's .venv is the plugin's dev venv (it has pytest), so the drafted
    # standards pick it up exactly as they would a project's own venv.
    (repo / ".venv").symlink_to(PLUGIN / ".venv")
    remote = tmp_path / "remote.git"
    git(["init", "-q", "--bare", "-b", "main", str(remote)], tmp_path)
    git(["init", "-q", "-b", "main"], repo)
    git(["config", "user.email", "test@example.com"], repo)
    git(["config", "user.name", "Test"], repo)
    git(["add", "-A"], repo)
    git(["commit", "-q", "-m", "init"], repo)
    git(["remote", "add", "origin", str(remote)], repo)
    git(["push", "-q", "-u", "origin", "main"], repo)
    git(["remote", "set-head", "origin", "main"], repo)
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    r = Repo(repo, env)
    r.remote = remote
    return r
