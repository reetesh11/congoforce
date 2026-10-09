# Changelog

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
