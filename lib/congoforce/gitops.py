"""Git and GitHub operations: fresh base, task worktree, commits, push, PR."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .util import CFError


def git(args, cwd, check=True) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and res.returncode != 0:
        raise CFError(f"git {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


def has_remote(root, remote="origin") -> bool:
    return remote in git(["remote"], root, check=False).split()


def default_branch(root) -> str:
    """origin/<default> when there is a remote, else the local main/master/current branch."""
    if has_remote(root):
        ref = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], root, check=False)
        if ref:
            return ref.replace("refs/remotes/", "")
        for name in ("main", "master"):
            if git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"], root, check=False):
                return f"origin/{name}"
    for name in ("main", "master"):
        if git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"], root, check=False):
            return name
    return git(["rev-parse", "--abbrev-ref", "HEAD"], root)


def fetch(root) -> None:
    if has_remote(root):
        git(["fetch", "--quiet", "origin"], root, check=False)


def resolve_base(root, base: str) -> dict:
    """Return {ref, branch, sha}; `branch` is what the PR targets."""
    ref = base or default_branch(root)
    sha = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], root, check=False)
    if not sha and not ref.startswith("origin/") and has_remote(root):
        # A bare branch name: prefer the fetched remote copy.
        sha = git(["rev-parse", "--verify", f"origin/{ref}^{{commit}}"], root, check=False)
        if sha:
            ref = f"origin/{ref}"
    if not sha:
        raise CFError(f"base {ref!r} does not resolve to a commit")
    branch = ref[len("origin/"):] if ref.startswith("origin/") else ref
    return {"ref": ref, "branch": branch, "sha": sha}


def create_worktree(root, path: Path, branch: str, base_ref: str) -> None:
    path = Path(path)
    if path.exists():
        if (path / ".git").exists():
            return  # resuming: already there
        raise CFError(f"{path} exists and is not a worktree")
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], root, check=False)
    if exists:
        git(["worktree", "add", str(path), branch], root)
    else:
        git(["worktree", "add", "-b", branch, str(path), base_ref], root)


def remove_worktree(root, path: Path) -> None:
    if Path(path).exists():
        git(["worktree", "remove", "--force", str(path)], root, check=False)
        if Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
    git(["worktree", "prune"], root, check=False)


def is_clean(wt) -> bool:
    return git(["status", "--porcelain"], wt) == ""


def dirty_files(wt) -> list:
    out = git(["status", "--porcelain"], wt)
    return [line[3:] for line in out.splitlines() if line.strip()]


def head(wt) -> str:
    return git(["rev-parse", "HEAD"], wt)


def commit_paths(wt, paths, message: str) -> str:
    rels = [str(p) for p in paths]
    if rels:
        git(["add", "-f", "--", *rels], wt)
    if not git(["diff", "--cached", "--name-only"], wt):
        return head(wt)
    git(["commit", "--quiet", "--no-verify", "-m", message], wt)
    return head(wt)


def commits_since(wt, sha: str) -> list:
    out = git(["log", "--format=%H %s", f"{sha}..HEAD"], wt, check=False)
    return [line for line in out.splitlines() if line.strip()]


def changed_files(wt, base_sha: str) -> list:
    out = git(["diff", "--name-only", f"{base_sha}...HEAD"], wt, check=False)
    return [x for x in out.splitlines() if x]


def push(wt, branch: str) -> str:
    return git(["push", "--quiet", "-u", "origin", f"HEAD:refs/heads/{branch}"], wt)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def create_pr(wt, base: str, branch: str, title: str, body_file: Path) -> str:
    if not gh_available():
        raise CFError("gh CLI not found; install it or set create_pr = false")
    res = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", str(body_file)],
        cwd=str(wt), capture_output=True, text=True,
    )
    if res.returncode != 0:
        existing = subprocess.run(["gh", "pr", "view", branch, "--json", "url", "-q", ".url"], cwd=str(wt), capture_output=True, text=True)
        if existing.returncode == 0 and existing.stdout.strip():
            return existing.stdout.strip()
        raise CFError(f"gh pr create failed: {(res.stderr or res.stdout).strip()}")
    m = re.search(r"https://\S+/pull/\d+", res.stdout)
    return m.group(0) if m else res.stdout.strip()


def pr_state(wt, pr_url: str) -> str:
    if not gh_available() or not pr_url:
        return ""
    res = subprocess.run(["gh", "pr", "view", pr_url, "--json", "state", "-q", ".state"], cwd=str(wt), capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""
