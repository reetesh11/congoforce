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
    "architecture_diagram": "large",  # off | large | medium | always
    "diagram_render": "auto",  # auto | off | a command with {in} and {out}
    "models": {},
    "model_tiers": {
        "spec": ["requirements", "product-spec", "tech-spec", "test-author"],
        "build": ["implementer", "verifier"],
    },
}

ROLES = ["requirements", "product-spec", "tech-spec", "test-author", "implementer", "verifier"]
# Values the Agent tool accepts for `model`; "inherit" means the session model.
MODEL_ALIASES = ("opus", "sonnet", "haiku", "fable", "inherit")
DIAGRAM_MODES = ("off", "large", "medium", "always")

USER_CONFIG_KEYS = {
    "max_iterations": int,
    "confirm_before_push": bool,
    "branch_prefix": str,
    "run_mode": str,
    "command_timeout": int,
    "default_model": str,
    "spec_model": str,
    "build_model": str,
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
    if key.startswith("models."):
        return key, raw.strip()
    if key not in DEFAULTS or key == "model_tiers":
        raise CFError(f"unknown config key {key!r}")
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return key, _coerce(bool, raw)
    if isinstance(default, int):
        return key, int(raw)
    if isinstance(default, list):
        return key, [v for v in (s.strip() for s in raw.split(",")) if v]
    return key, raw


def _norm_name(name: str) -> str:
    return str(name).strip().replace("_", "-")


def resolve_models(layers, tiers: dict) -> dict:
    """Model per role. Layers go from weakest to strongest; inside a layer a role
    beats its tier, and a tier beats `default`. "inherit" clears what came before."""
    known = {"default", *ROLES, *tiers}
    for layer in layers:
        for name, value in layer.items():
            if name not in known:
                raise CFError(f"[models] {name!r} is not a role, a tier or `default` (roles: {', '.join(ROLES)}; tiers: {', '.join(tiers)})")
            if value and value not in MODEL_ALIASES:
                raise CFError(f"[models] {name} = {value!r}: use one of {', '.join(MODEL_ALIASES)}")
    out = {}
    for role in ROLES:
        model = ""
        names = ["default", *[t for t, roles in tiers.items() if role in roles], role]
        for layer in layers:
            for name in names:
                if layer.get(name):
                    model = layer[name]
        out[role] = "" if model == "inherit" else model
    return out


def load(paths, overrides=None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    user = read_json(user_config_path(), {}) or {}
    layers = [{"default": user.pop("default_model", ""), "spec": user.pop("spec_model", ""),
               "build": user.pop("build_model", "")}]
    cfg.update({k: v for k, v in user.items() if k in DEFAULTS and k not in ("models", "model_tiers")})
    if paths.config.exists():
        try:
            data = tomlish.loads(paths.config.read_text())
        except tomlish.TomlError as exc:
            raise CFError(f"{paths.config}: {exc}")
        section = data.get("congoforce", {})
        for key, value in section.items():
            if key in DEFAULTS and key not in ("models", "model_tiers"):
                cfg[key] = value
        for tier, roles in (data.get("model_tiers") or {}).items():
            roles = [_norm_name(r) for r in (roles if isinstance(roles, list) else [roles])]
            bad = [r for r in roles if r not in ROLES]
            if bad:
                raise CFError(f"[model_tiers] {tier}: unknown roles {', '.join(bad)} (roles: {', '.join(ROLES)})")
            cfg["model_tiers"][_norm_name(tier)] = roles
        layers.append({_norm_name(k): v for k, v in (data.get("models") or {}).items()})
    run_models = {}
    for key, value in (overrides or {}).items():
        if key.startswith("models."):
            run_models[_norm_name(key.split(".", 1)[1])] = value
        else:
            cfg[key] = value
    layers.append(run_models)
    cfg["models"] = resolve_models(layers, cfg["model_tiers"])
    if cfg.get("architecture_diagram") not in DIAGRAM_MODES:
        raise CFError(f"architecture_diagram must be one of {', '.join(DIAGRAM_MODES)} (got {cfg.get('architecture_diagram')!r})")
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
worktree_dir = ""             # "" = .congoforce/worktrees; any path relative to the repo root
history_dir = ".congoforce/history"  # where specs and reports are committed on the task branch
protected_branches = ["main", "master", "develop", "release"]  # never pushed to directly
red_check_attempts = 2        # test-author retries before the red check escalates
agent_retries = 2             # re-runs of an agent whose output the helper rejects
architecture_diagram = "large"  # when tech.md must hold a Mermaid diagram: off | large | medium | always
diagram_render = "auto"       # auto (mmdc if on PATH) | off | a command with {in} and {out}

# Agent models: opus | sonnet | haiku | fable | inherit (the session model).
# A role setting beats its tier; a tier beats `default`. --set models.<name>=<model> per run.
[models]
# default = "sonnet"
# spec = "opus"               # requirements, product-spec, tech-spec, test-author
# build = "sonnet"            # implementer, verifier
# verifier = "opus"           # a role overrides its tier

# Which roles each tier covers. Redefine a tier or add your own.
# [model_tiers]
# spec = ["requirements", "product-spec", "tech-spec", "test-author"]
# build = ["implementer", "verifier"]
"""
