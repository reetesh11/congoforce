# Tech spec — <title>

## Approach
One paragraph: the design and why it fits this codebase. Name the existing
files and patterns you follow.

## Interface contract
The only section the test-author sees. Public surfaces the acceptance tests
call, with exact names, import paths, signatures, inputs, outputs, errors:
- `module/path.ext`: `functionName(arg: type) -> type` — behaviour, errors.
- CLI: `cmd --flag value` → stdout/exit code.
- HTTP: `POST /path` body → status + body.
- UI: component name, props, visible text/roles the test queries.

## Data and state changes
Schemas, migrations, config, env vars (concrete names and types), or "none".

## Tasks
Ordered; each one is one commit that leaves the build green.
1. **<title>** — `path/to/file` (new|modified): what changes.
2. …

## Implementation tests
Unit/integration tests the implementer adds alongside the code (not frozen).

## Risks and rollout
Migration order, flags, anything a reviewer should know.

## Open questions
- … or "none".
