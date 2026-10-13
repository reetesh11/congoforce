# Setting up CongoForce

This guide takes you from a fresh machine to a first CongoForce pull request.
For what CongoForce does and how the pipeline works, see [README.md](README.md).

## 1. Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| Claude Code | 2.1.295 or later | runs the plugin, agents and hooks |
| Python | 3.9+ | the `congoforce` helper (standard library only, nothing to pip install) |
| git | any recent | worktrees, branches, freeze hashes |
| `gh` (GitHub CLI) | logged in | opens the pull request; optional if you set `create_pr = false` |
| Node.js | 18+ | only for JS/TS target repos |

```bash
claude --version
python3 --version
git --version
gh auth status        # or: gh auth login
```

## 2. Install the plugin

Clone the repository and register it as a local marketplace:

```bash
git clone git@github.com:reetesh11/congoforce.git
claude plugin marketplace add ./congoforce
claude plugin install congoforce@congoforce
```

To try it for one session without installing:

```bash
claude --plugin-dir /path/to/congoforce
```

When the plugin is enabled, Claude Code asks for its user options. You can
change them later with `/config`. These options apply to every repo you use
CongoForce in:

| Option | Default | Meaning |
| --- | --- | --- |
| Max implement/verify iterations | 5 | loop cap before CongoForce stops and asks you |
| Confirm before push | true | show the PR body and wait for your yes |
| Branch prefix | `congoforce/` | task branches are `<prefix><task-id>` |
| Run mode | foreground | `background` runs the implementer and verifier in the background |
| Command timeout | 600 s | upper bound for each install, lint, build or test command |
| Default agent model | (session model) | e.g. `sonnet` for all six agents |

## 3. Prepare a target repository

Run these from inside the repository you want CongoForce to change. It needs
a git remote with a default branch.

```bash
congoforce doctor     # checks Python, git, gh login, and this repo's config
congoforce init       # drafts .congoforce/standards.md and .congoforce/config.toml
```

`congoforce init` detects the stack (pytest, vitest or jest; ruff or eslint;
mypy, pyright or tsc; npm, pnpm or yarn) and drafts the exact commands. Use
`--preset python` or `--preset js` if detection guesses wrong. You can also skip
this step, because `/congoforce:run` drafts both files the first time you use it.

Then:

1. **Review `standards.md`.** Its commands block must run as written:
   `install`, `lint`, `typecheck`, `build`, `test`, `test_files`, `e2e`. Leave a
   command empty if your repo has no such step.
2. **Review `config.toml`.** Every key is listed with its default; see
   [Configuration](#4-configuration).
3. **Approve the standards** when `/congoforce:run` asks, then commit both
   files.

Add `.congoforce/**` to the ignore lists of vitest and eslint, because they may
scan the task worktrees. pytest skips dot folders on its own. You can also set
`worktree_dir` to a folder outside those tools' scope.

## 4. Configuration

Settings are layered. Each layer overrides the one before it:

```
built-in defaults  <  plugin options (/config)  <  .congoforce/config.toml  <  --set key=value (one run)
```

`.congoforce/config.toml`:

```toml
[congoforce]
max_iterations = 5
confirm_before_push = true
base_branch = ""              # "" = remote default branch; e.g. "origin/main"
branch_prefix = "congoforce/"
run_mode = "foreground"
command_timeout = 600
post_pr = []                  # e.g. ["/seo-review {pr}", "echo opened {pr_url}"]
retro = true
repo_map_backend = "builtin"
e2e = false
push = true
create_pr = true
worktree_dir = ""
history_dir = ".congoforce/history"
protected_branches = ["main", "master", "develop", "release"]
red_check_attempts = 2
agent_retries = 2

[models]                      # per role; empty = inherit
requirements = ""
product-spec = ""
tech-spec = ""
test-author = ""
implementer = ""
verifier = ""
```

To override a setting for one run:

```
/congoforce:run req.md --set max_iterations=3 --set push=false
```

List values take a comma-separated list, for example
`--set protected_branches=main,staging`.

The push guard hook also reads `protected_branches`, so any branch you add
there is blocked from direct pushes in every Claude Code session in that repo.

## 5. First run

Write a small requirement:

```markdown
<!-- requirements/word-count.md -->
Add a `word_count(text)` function to textkit that returns the number of
whitespace-separated words. Empty or whitespace-only text returns 0.
```

Run it:

```
/congoforce:run requirements/word-count.md
```

You will be asked three times:

1. **Gate 1:** approve or revise `req.md` (class, size, acceptance criteria).
2. **Gate 2:** approve the specs and the failing acceptance tests. The tests
   are frozen after this.
3. **Ship:** confirm the PR body before the branch is pushed.

To see what is in flight, run `/congoforce:status`. To resume a task that
stopped, run `/congoforce:run <task-id>`.

For a dry run that does not push, use `--set push=false`.

## 6. Try it on the bundled fixtures

`fixtures/python-mini` and `fixtures/js-mini` are small repos with requirement
files, so you can try the pipeline without touching real code:

```bash
cp -r fixtures/python-mini /tmp/python-mini && cd /tmp/python-mini
git init -q && git add -A && git commit -qm init
claude --plugin-dir /path/to/congoforce
# then: /congoforce:run requirements/word-count.md --set push=false
```

## 7. Developing CongoForce itself

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q          # unit tests + full pipeline runs with stub agents
claude plugin validate --strict .
claude plugin eval . --scaffold        # live eval cases (uses tokens)
```

CI (`.github/workflows/ci.yml`) runs the tests on Python 3.9 and 3.12 and
validates the plugin manifest on every push and pull request.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `congoforce: command not found` | The helper is on PATH only while the plugin is enabled. Use `/path/to/congoforce/bin/congoforce`. |
| `gh: not logged in` | `gh auth login`, or set `create_pr = false`. |
| "pushes to main are blocked" | Expected: the push guard protects `protected_branches`. Push a feature branch, or run the push yourself outside Claude Code. |
| "X is frozen" | Acceptance tests are frozen after Gate 2. To change them, send the task back from Gate 2 or start a new task. |
| The run stops with an escalation | The same failure happened twice, a regression appeared, or the loop hit `max_iterations`. Read `.congoforce/tasks/<task>/verify-report.md` and decide at the prompt. |
| vitest or eslint picks up worktree files | Exclude `.congoforce/**`, or set `worktree_dir`. |
