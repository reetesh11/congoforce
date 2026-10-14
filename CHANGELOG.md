# Changelog

## Unreleased

- **Model tiers.** Agents are grouped into a `spec` tier (requirements,
  product-spec, tech-spec, test-author) and a `build` tier (implementer,
  verifier). Set them with the new plugin options Spec model and Build model,
  `[models]` in config.toml, or `--set models.<tier|role>=<model>`. Tiers can
  be redefined under `[model_tiers]`. Unknown roles and model names are
  rejected. The models used are recorded in state.json and the PR body.
- **Architecture diagrams.** Large tasks (`architecture_diagram`: off, large,
  medium or always) need a Mermaid diagram in tech.md's `## Architecture`
  section. mermaid-cli renders it and checks its syntax when installed
  (`diagram_render`). The diagram is shown at Gate 2, put in the PR body and
  committed with the specs. The verifier reports drift from it.
- Gate packets are written even when a gate is auto-approved.
- The push and freeze guards ignore heredoc bodies that only feed `cat` or
  `tee` (file contents, not commands). Bodies fed to a shell, a pipe or `eval`
  are still checked.
- **End-to-end evals:** `js-clamp`, `python-bug-fix`,
  `python-architecture-tiers` and `large-task-split`, a shared scaffold, and
  stronger graders on `python-word-count`. `tests/test_eval_graders.py`
  replays each case with stub agents to check its file graders offline.
- SETUP.md: install, target-repo setup, configuration, first run, troubleshooting.
- The push guard reads `protected_branches` from the repo config instead of a
  fixed list.
- The config.toml template and README list every key (`worktree_dir`,
  `history_dir`, `protected_branches`, `red_check_attempts`, `agent_retries`).
- The freeze guard is scoped to the current task's worktree, so stacked tasks
  can change files that only another task froze.

## 0.1.0 — 2026-10-10

First release.

- `/congoforce:run` orchestrator and `/congoforce:status`.
- Six agents: requirements, product-spec, tech-spec, test-author, implementer, verifier.
- Helper (`congoforce`, stdlib Python 3.9+): state machine, gates, red check,
  freeze hashes, baseline, verify with JUnit, failure signatures, flaky rerun,
  escalation, PR body, post-PR hooks, retro, repo map, status and clean.
- Presets: Python (pytest, ruff, mypy or pyright) and JS/TS (vitest or jest,
  eslint, tsc, npm, pnpm or yarn, monorepo package folders).
- Hooks: push guard, freeze guard, stage guard, context guard.
