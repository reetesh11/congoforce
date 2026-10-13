# CongoForce

A software factory for Claude Code. Give it a requirement file; it gives you a
tested pull request. You approve the requirements (Gate 1) and the specs and
acceptance tests (Gate 2), confirm the push, and CongoForce does the rest.

```
/congoforce:run requirements/word-count.md
```

- **Two human gates, then a guarded loop.** The acceptance tests are written
  before any code. They are proven red for the right reason, approved by you,
  then frozen. The implementer and verifier loop until everything passes.
  The loop stops and asks you on a repeated failure, a regression, or the
  iteration cap.
- **Rules in code, not prompts.** A stdlib-only Python helper (`congoforce`)
  owns the state machine, stage order, gates, loop limits, freeze hashes,
  baseline comparison and failure signatures. Hooks block edits to frozen
  tests, pushes to protected branches, force pushes, and agents started out
  of order.
- **Python and JS/TS.** Presets detect pytest, vitest or jest, ruff or eslint,
  mypy, pyright or tsc, npm, pnpm or yarn, and monorepo package folders, then
  draft `standards.md` for you to approve once.

## Install

Requirements: Claude Code 2.1.295 or later, Python 3.9+ and git on PATH. You
also need `gh` (logged in) to open PRs; without it, set `create_pr = false`.
For a step-by-step guide, including first-run and troubleshooting, see
[SETUP.md](SETUP.md).

```bash
git clone git@github.com:reetesh11/congoforce.git
claude plugin marketplace add ./congoforce
claude plugin install congoforce@congoforce
```

or, for one session: `claude --plugin-dir /path/to/congoforce`.

When the plugin is enabled, Claude Code asks for its options (`/config` also
shows them): iteration cap, confirm before push, branch prefix, run mode,
command timeout, and the default agent model.

## Use

From inside the repository you want to change:

| You type | What happens |
| --- | --- |
| `/congoforce:run path/to/req.md` | Starts a task from a `.md`, `.txt` or `.html` file. Linked images and a sibling `<name>.assets/` folder are attached. |
| `/congoforce:run "add a --json flag to the export command"` | Starts a task from a one-liner. |
| `/congoforce:run req.md --base congoforce/other-task` | Stacks on another task's branch; the PR targets that branch. |
| `/congoforce:run req.md --class bug --set max_iterations=3` | Forces the class; per-run config override. |
| `/congoforce:run word-count` | Resumes a task where it stopped. |
| `/congoforce:status` | One line per task: stage, branch, base, PR, tokens. |

On first use in a repo, CongoForce drafts `.congoforce/standards.md` and
`.congoforce/config.toml`. Review the commands block, edit anything, approve
it, and commit both files.

## The pipeline

```
standards ─▶ requirements ─▶ [split?] ─▶ GATE 1 ─▶ prepare (worktree, install, baseline, repo map)
   ─▶ product-spec (features) ─▶ tech-spec ─▶ test-author ─▶ red check ─▶ GATE 2 (freeze)
   ─▶ implement ⇄ verify ⇄ review ─▶ ship (confirm, push, PR) ─▶ post-PR checks ─▶ retro ─▶ done
                     └─▶ escalate to you: same failure twice · regression · iteration cap · frozen test changed
```

| Stage | Run by | Output |
| --- | --- | --- |
| requirements | `congoforce:requirements` agent | `req.md`: class (feature, task, bug, bootstrap), size, EARS requirements, `AC-n` criteria |
| Gate 1 | you | approve, revise with a note, or stop |
| prepare | helper | a fresh base from `origin/<default>`, branch `congoforce/<task>`, a worktree under `.congoforce/worktrees/`, install, a baseline of every command, the repo map |
| product-spec | agent (features only) | `product-spec.md`: user-facing behaviour, criteria sharpened by id |
| tech-spec | agent | `tech.md`: **interface contract**, an ordered **task list** (one commit each), and a Mermaid **architecture diagram** for large tasks |
| test-author | agent | acceptance tests in the worktree, plus `tests.json` and `test.md`. It sees only the interface contract, never `tech.md`. |
| red check | helper | every acceptance test fails for the right reason; unchanged-behaviour tests pass |
| Gate 2 | you | approve and freeze, send back the tech spec, tests or product spec, or stop |
| implement | agent | one commit per task in the worktree |
| verify | helper | runs lint, typecheck, build and tests (JUnit), checks the freeze hash, checks that frozen tests ran and were not skipped, compares against the baseline, reruns flaky tests once |
| review | `congoforce:verifier` agent | spec compliance per criterion, then a quality review: `verify-review.json` and `verify-report.md` |
| decide | helper | ship, loop with a feedback file, or escalate |
| ship | helper | PR body with the criteria table, checks, review notes, architecture diagram, commits, models and tokens. Confirm, push, `gh pr create` |
| post-PR | helper and you | `post_pr` commands or slash commands, for example `/seo-review {pr}` |
| retro | orchestrator | proposes `standards.md` edits; you apply or skip them |

Classes skip what they don't need: **bug** and **task** skip the product spec;
**bootstrap** (no test runner yet) skips the red check and ends with a working
test command in `standards.md`. A **large** task stops with a suggested split.

## Models per stage

Writing specs needs a stronger model than following them, so each agent's
model is configurable. The six agents fall into two tiers:

| Tier | Roles |
| --- | --- |
| `spec` | requirements, product-spec, tech-spec, test-author |
| `build` | implementer, verifier |

Set them with the plugin options **Spec model** and **Build model** (`/config`),
for every repo, or per repo in `.congoforce/config.toml`:

```toml
[models]
spec = "opus"        # the expensive model writes the specs and tests
build = "sonnet"     # the cheaper model writes and reviews the code
verifier = "opus"    # optional: a role overrides its tier
```

Values are `opus`, `sonnet`, `haiku`, `fable` or `inherit` (the session model).
Settings are layered: plugin options, then `config.toml`, then
`--set models.<tier-or-role>=<model>` for one run. A later layer wins. Within a
layer, a role beats its tier and a tier beats `default`. You can redefine the
tiers or add your own under `[model_tiers]`. `congoforce doctor` shows the
model each role resolves to. The PR body records the models used.

## Architecture diagrams

For large tasks, the tech-spec agent adds a `## Architecture` section to
`tech.md` with a [Mermaid](https://mermaid.js.org) diagram (open source, MIT
licence) of the components the change touches and the data flow between them.
New and changed parts are highlighted. The diagram appears in the Gate 2 packet and
the PR body (GitHub and GitLab render Mermaid natively), and is committed with
the specs under the history folder. The implementer follows it, and the verifier
reports any drift as a finding.

When [mermaid-cli](https://github.com/mermaid-js/mermaid-cli) (`mmdc`) is
installed, the helper renders each diagram to SVG. This doubles as a syntax
check: a diagram that does not parse is sent back to the tech-spec agent with
the parser's error. Without `mmdc`, the helper only checks the diagram type
on the first line.

```bash
npm install -g @mermaid-js/mermaid-cli     # optional; congoforce doctor reports it
```

| Setting | Values |
| --- | --- |
| `architecture_diagram` | `large` (default): large tasks, including large tasks you chose not to split · `medium`: medium and large · `always` · `off` |
| `diagram_render` | `auto` (default): `mmdc` if it is on PATH · `off` · any command with `{in}` and `{out}`, for example `npx -y @mermaid-js/mermaid-cli@11.12.0 -i {in} -o {out}` |

## Configuration

`.congoforce/config.toml` (commit it) overrides the plugin options; `--set key=value` overrides both for one run.

| Key | Default | Meaning |
| --- | --- | --- |
| `max_iterations` | 5 | implement/verify loop cap |
| `confirm_before_push` | true | Gate before pushing |
| `base_branch` | remote default | e.g. `origin/main` |
| `branch_prefix` | `congoforce/` | |
| `run_mode` | foreground | `background` runs the implementer and verifier in the background |
| `command_timeout` | 600 | seconds per command |
| `post_pr` | `[]` | `"/skill {pr}"` entries run as slash commands, anything else as shell; `{pr}`, `{pr_url}`, `{branch}`, `{task}` are substituted |
| `retro` | true | |
| `repo_map_backend` | builtin | or any executable taking `--repo <path>` that prints Markdown |
| `e2e` | false | run the e2e command in verify |
| `push` / `create_pr` | true / true | `push = false` is a dry run |
| `worktree_dir` | `.congoforce/worktrees` | where task worktrees go, relative to the repo root |
| `history_dir` | `.congoforce/history` | where specs and reports are committed on the task branch |
| `protected_branches` | main, master, develop, release | the push guard and ship stage refuse direct pushes to these |
| `red_check_attempts` | 2 | test-author retries before a failing red check escalates |
| `agent_retries` | 2 | re-runs of an agent whose output the helper rejects |
| `architecture_diagram` | large | when tech.md must include a Mermaid diagram: `off`, `large`, `medium`, `always` |
| `diagram_render` | auto | `auto` (mmdc if installed), `off`, or a command with `{in}` and `{out}` |
| `[models]` | — | model per tier (`spec`, `build`), per role, or `default`; see [Models per stage](#models-per-stage) |
| `[model_tiers]` | spec, build | which roles each tier covers |

`standards.md` has a machine-readable block: the exact `install`, `lint`,
`typecheck`, `build`, `test`, `test_files` and `e2e` commands (`{junit}` and
`{files}` placeholders), `package_dir`, and the freeze `globs` and `keys` (for
example `package.json#scripts.test` or `pyproject.toml#tool.pytest.ini_options`).

## Where things live

```
congoforce/                      this plugin
  .claude-plugin/plugin.json     manifest + userConfig
  skills/run/SKILL.md            orchestrator (/congoforce:run), templates/
  skills/status/SKILL.md         /congoforce:status
  agents/                        requirements, product-spec, tech-spec, test-author, implementer, verifier
  hooks/hooks.json               push guard, freeze guard, stage guard, context guard
  bin/congoforce                 the helper (stdlib Python 3.9+), on PATH while the plugin is enabled
  lib/congoforce/                helper modules
  presets/python, presets/js     detection, commands, freeze globs, red-check patterns
  tests/  fixtures/  evals/      pytest for the helper, fixture repos, plugin eval cases

<your repo>/.congoforce/
  config.toml  standards.md  repo-map.md     commit these
  history/<task>/                            specs, tests list, verify report (committed on the task branch)
  tasks/<task>/                              run state, git-ignored via .git/info/exclude
  worktrees/<task>/                          the task worktree, git-ignored
```

Each task folder holds `input.md`, `assets/`, `req.md`, `product-spec.md`,
`tech.md`, `interface-contract.md`, `tests.json`, `test.md`, `red-check.md`,
`gate1-packet.md`, `gate2-packet.md`, `baseline.json`, `checks.md`,
`verify-report.md`, `pr-body.md`, `feedback/iter-N.md`, `answers.md`,
`run-log.md`, and `state.json`.

## The helper by hand

The orchestrator drives it, but every command works from a shell too:

```bash
congoforce doctor                 # prerequisites, config, standards status
congoforce init [--preset js]     # draft standards.md and config.toml
congoforce new req.md             # create a task
congoforce next <task>            # what happens next (JSON)
congoforce advance <task>         # run the current helper stage
congoforce gate <task> gate2 approve --note "…"
congoforce check <task>           # run the checks in the worktree, no state change
congoforce status
congoforce clean --merged         # remove worktrees whose PR merged or closed
```

## Notes and limits

- The worktree sits inside the repo (`.congoforce/worktrees/`). pytest skips
  dot folders, but vitest and eslint may not. While a task is in flight,
  exclude `.congoforce/**` in their configs if your own runs pick it up, or
  set `worktree_dir` elsewhere.
- Guards are a strong deterrent, not a sandbox: a determined shell command
  can still write a frozen file. That is why the helper also hashes the
  frozen set and refuses any pass after a change.
- `--auto-approve` exists for fixture repos and evals. It never decides an
  escalation or a split; those stop the run.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q          # unit tests + full pipeline runs with stub agents (Python and JS)
claude plugin validate --strict .
claude plugin eval . --scaffold --ablation none --tag e2e   # live end-to-end evals (uses tokens; see evals/README.md)
```

Ideas borrowed with thanks (see NOTICE): GitHub Spec Kit, Superpowers,
BMAD-METHOD, and Kiro's EARS-style criteria. It generalises the repo-local
factory first proven on biharipakwan.
