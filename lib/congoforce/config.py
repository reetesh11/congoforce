"""Layered config: defaults < user (plugin userConfig) < repo config.toml < per-run flags."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import tomlish
from .util import CFError, read_json, write_json

DEFAULTS = {
    "max_iterations": 5,
    "confirm_before_push": True,
    "base_branch": "",  # "" = the remote's default branch, fetched fresh
    "branch_prefix": "congoforce/",
    "run_mode": "foreground",
    "command_timeout": 600,
    "post_pr": [],
    "retro": True,
    "repo_map_backend": "builtin",
    "e2e": False,
    "push": True,
    "create_pr": True,
    "worktree_dir": "",
    "history_dir": ".congoforce/history",
    "protected_branches": ["main", "master", "develop", "release"],
    "red_check_attempts": 2,
    "agent_retries": 2,
    "models": {},
}

ROLES = ["requirements", "product-spec", "tech-spec", "test-author", "implementer", "verifier"]

USER_CONFIG_KEYS = {
    "max_iterations": int,
    "confirm_before_push": bool,
    "branch_prefix": str,
    "run_mode": str,
    "command_timeout": int,
    "default_model": str,
}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "congoforce" / "user.json"


def _coerce(kind, raw: str):
    if kind is bool:
        low = raw.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise ValueError(raw)
    if kind is int:
        return int(float(raw))
    return raw


def sync_user_config(pairs) -> dict:
    """Store plugin userConfig values that the skill passes in as key=value strings.

    Values that were not substituted (still contain `${`) or are empty are skipped,
    so an unset option keeps the default instead of becoming a literal string.
    """
    stored = read_json(user_config_path(), {}) or {}
    for pair in pairs:
        if "=" not in pair:
            continue
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in USER_CONFIG_KEYS or not raw.strip() or "${" in raw:
            continue
        try:
            stored[key] = _coerce(USER_CONFIG_KEYS[key], raw)
        except ValueError:
            continue
    write_json(user_config_path(), stored)
    return stored


def parse_override(pair: str):
    if "=" not in pair:
        raise CFError(f"--set expects key=value, got {pair!r}")
    key, raw = pair.split("=", 1)
    key = key.strip()
    if key not in DEFAULTS:
        raise CFError(f"unknown config key {key!r}")
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return key, _coerce(bool, raw)
    if isinstance(default, int):
        return key, int(raw)
    if isinstance(default, list):
        return key, [v for v in (s.strip() for s in raw.split(",")) if v]
    return key, raw


def load(paths, overrides=None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    user = read_json(user_config_path(), {}) or {}
    default_model = user.pop("default_model", "")
    cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    if default_model:
        cfg["models"] = {role: default_model for role in ROLES}
    if paths.config.exists():
        try:
            data = tomlish.loads(paths.config.read_text())
        except tomlish.TomlError as exc:
            raise CFError(f"{paths.config}: {exc}")
        section = data.get("congoforce", {})
        for key, value in section.items():
            if key in DEFAULTS and key != "models":
                cfg[key] = value
        models = dict(cfg.get("models") or {})
        models.update({k: v for k, v in (data.get("models") or {}).items() if v})
        cfg["models"] = models
    for key, value in (overrides or {}).items():
        cfg[key] = value
    return cfg


CONFIG_TEMPLATE = """# CongoForce repo config. Commit this file.
# Precedence: plugin userConfig < this file < per-run flags (--set key=value).

[congoforce]
max_iterations = 5            # implement/verify loop cap
confirm_before_push = true    # show the PR body and wait for a yes
base_branch = ""              # "" = remote default branch, fetched fresh; e.g. "origin/main"
branch_prefix = "congoforce/"
run_mode = "foreground"       # or "background": post-Gate 2 agents run in the background
command_timeout = 600         # seconds, per command the helper runs
post_pr = []                  # e.g. ["/seo-review {pr}", "echo opened {pr_url}"]
retro = true                  # propose standards.md edits after each run
repo_map_backend = "builtin"  # or an executable that takes --repo <path>
e2e = false
push = true                   # false = dry run: stop before pushing
create_pr = true              # false = push the branch but open no PR

[models]                      # optional model per role, e.g. implementer = "sonnet"
"""
