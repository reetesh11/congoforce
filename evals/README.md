# CongoForce evals

Live evals run the real `/congoforce:run` skill and its six agents against the
fixture repos with `claude plugin eval`. Each case seeds a fresh workspace (a
fixture copy, its dependencies and a bare `origin` remote), runs one prompt,
and grades what the run left behind.

## Cases

| Case | Tags | What it proves | Rough cost |
| --- | --- | --- | --- |
| `python-word-count` | e2e, slow, python, feature | A full run on pytest reaches `done`: checks pass, the verifier says PASS, the acceptance tests are frozen by hash | ~20–40 min |
| `js-clamp` | e2e, slow, js, task | The same on vitest/npm, including a `RangeError` acceptance test | ~20–40 min |
| `python-bug-fix` | e2e, slow, python, bug | A bug report is classed `bug`, skips the product spec, its regression test is red before the fix, existing behaviour is pinned green | ~20–40 min |
| `python-architecture-tiers` | e2e, slow, python, feature, diagram, models | With `architecture_diagram=always` and `models.spec=opus`, `models.build=sonnet`: the Mermaid diagram reaches the Gate 2 packet and PR body and names the real modules, and each agent gets its tier's model | ~30–45 min |
| `large-task-split` | e2e, python, gates | A large requirement stops at the split gate with a suggested split; no worktree is created | ~3 min |
| `status-skill` | — | `/congoforce:status` fires and doesn't invent tasks | <1 min |

All runs use `--auto-approve` (fixture repos only) and `create_pr=false`, so
nothing leaves the sandbox: branches are pushed to the case's local bare
remote.

## Running

```bash
# everything end to end, one run per case, no no-plugin baseline arm
claude plugin eval . --scaffold --ablation none --tag e2e

# one case
claude plugin eval . --scaffold --ablation none --case python-bug-fix

# the cheap gate check only
claude plugin eval . --scaffold --ablation none --case large-task-split

# a cost ceiling and a pass threshold for CI
claude plugin eval . --scaffold --ablation none --tag e2e --max-cost-usd 40 --threshold 0.9
```

- `--scaffold` is required: it runs each case's `scaffold.sh`
  (`_shared/scaffold.sh python-mini|js-mini`). It needs `python3`, and `npm` for the JS case.
- `--ablation none` skips the baseline arm. Without the plugin, these
  prompts mean nothing, so a baseline only doubles the cost.
- End-to-end cases set `runs: 1`. Use `--runs 3` to measure flakiness.
- `--keep-temp` keeps the workspaces. Look in `.congoforce/tasks/<task>/`
  (`run-log.md`, `checks.md`, `verify-report.md`) to see why a run failed.
- Results and the HTML report go to `evals/results/` (git-ignored).

## Graders

- **regex on a file:** the helper's own records (`state.json`, `checks.json`,
  `verify-review.json`, `frozen.json`, `red.json`, `tests.json`, packets,
  `architecture.mmd`). These are deterministic and cost nothing.
- **tool_used:** the skill fired, and agents were spawned with the expected `model`.
- **llm:** the final report is honest, and the diagram describes this change
  rather than boilerplate.

`tests/test_eval_graders.py` replays each scenario with stub agents and
applies the case's regex graders to the files the helper wrote. It runs in
`pytest` and CI, so a grader that names the wrong file or pattern fails there
before a live run costs tokens. When you add a case, add its replay there.

## Adding a case

1. Put the requirement in `fixtures/<fixture>/requirements/`.
2. Create `evals/<case>/` with `case.yaml` (quote the description), `prompt.md`,
   and a `scaffold.sh` that calls `../_shared/scaffold.sh <fixture>` (make it
   executable).
3. Pass `--id <task>` in the prompt so graders can name
   `.congoforce/tasks/<task>/…` exactly.
4. Prefer file graders over LLM graders. Add a replay to `tests/test_eval_graders.py`.
