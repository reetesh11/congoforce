---
name: status
description: Show every CongoForce task in this repo with its stage, branch, base, PR and token use. Use when the user asks what CongoForce is doing, which tasks are in flight, or where a run stopped.
---

Run `congoforce status` (or `python3 "${CLAUDE_PLUGIN_ROOT}/bin/congoforce" status` if it is not on PATH) and show the table as is.

Then, in one or two lines:
- name any task that is blocked or waiting at a gate, and say it resumes with `/congoforce:run <task>`
- for tasks whose stage is `done`, suggest `congoforce clean --merged` once their PRs are merged

If the repo has no `.congoforce/` folder, say that no task has run here yet and that `/congoforce:run <requirement-file>` starts one.
