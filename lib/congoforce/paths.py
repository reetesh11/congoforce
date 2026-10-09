"""Where everything lives.

Tooling lives in the plugin; state lives in the target repo under
`.congoforce/`. Task folders and worktrees are git-ignored (via
.git/info/exclude, so no tracked file is touched); config, standards and the
repo map are meant to be committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .util import CFError

CF_DIR = ".congoforce"


def _git(args, cwd) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if res.returncode != 0:
        raise CFError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def find_repo_root(start=None) -> Path:
    """Main checkout root, even when called from inside a task worktree."""
    start = Path(start or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent
    try:
        common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], start)
    except CFError:
        raise CFError(f"{start} is not inside a git repository")
    common_path = Path(common)
    if common_path.name == ".git":
        return common_path.parent
    # Unusual layouts (bare repo, separate git dir): fall back to the toplevel.
    return Path(_git(["rev-parse", "--show-toplevel"], start))


class Paths:
    def __init__(self, root: Path, worktree_dir: str = ""):
        self.root = Path(root).resolve()
        self.cf = self.root / CF_DIR
        self.tasks = self.cf / "tasks"
        self.worktrees = (self.root / worktree_dir) if worktree_dir else self.cf / "worktrees"
        self.config = self.cf / "config.toml"
        self.standards = self.cf / "standards.md"
        self.standards_approval = self.cf / "tasks" / ".standards-approved.json"
        self.repomap = self.cf / "repo-map.md"
        self.map_summaries = self.cf / "tasks" / ".map-summaries.json"
        self.history = self.cf / "history"

    def task_dir(self, task: str) -> Path:
        return self.tasks / task

    def state_file(self, task: str) -> Path:
        return self.task_dir(task) / "state.json"

    def worktree(self, task: str) -> Path:
        return self.worktrees / task

    def standards_for(self, task: str = "") -> Path:
        """The worktree copy wins once it exists (a bootstrap run edits it there)."""
        if task:
            wt = self.worktree(task) / CF_DIR / "standards.md"
            if wt.exists():
                return wt
        return self.standards

    def ensure_excludes(self) -> None:
        """Keep task state and worktrees out of git without editing .gitignore."""
        try:
            git_dir = Path(_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], self.root))
        except CFError:
            return
        exclude = git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text() if exclude.exists() else ""
        wanted = [f"/{CF_DIR}/tasks/"]
        try:
            rel = self.worktrees.relative_to(self.root)
            wanted.append(f"/{rel.as_posix()}/")
        except ValueError:
            pass
        missing = [w for w in wanted if w not in current.splitlines()]
        if missing:
            with exclude.open("a") as fh:
                if current and not current.endswith("\n"):
                    fh.write("\n")
                fh.write("# congoforce\n" + "\n".join(missing) + "\n")


def locate_from_path(path: str):
    """For hooks: map a file path to (repo_root, task) when it sits in a task worktree.

    Returns (None, None) when the path is not inside `.congoforce/worktrees/<task>/`.
    Custom worktree_dir settings are resolved by the caller via config.
    """
    p = Path(path)
    parts = p.parts
    for i in range(len(parts) - 2):
        if parts[i] == CF_DIR and parts[i + 1] == "worktrees" and i + 2 < len(parts):
            return Path(*parts[:i]), parts[i + 2]
    return None, None
