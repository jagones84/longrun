# Runtime data lives outside the checkout; project rules stay with the workspace

Harness runtime data — sessions, the event log, indexes, costs and the self-evolution runtime — lives under ONE root (`~/.longrun`, `%LOCALAPPDATA%\Longrun` on Windows). Project instructions are the deliberate workspace-local exception: only `<workspace>/.longrun/rules/*.md` and `<workspace>/AGENTS.md` are project sources.

We chose this so a `git pull`, a fresh clone or a container image can never replace or expose the operator's sessions or costs, while project rules remain beside the code they govern. The runtime root is movable (explicit override → a config value → the platform default); the small `config/` directory always stays at the default location, because it is the file that records where the root is.

## Considered Options

- **A `data/` directory inside the checkout** — rejected: it makes application state a merge conflict and puts user data one `git clean` away from deletion. A legacy in-repo `data/` is still served, flagged rather than silently migrated, so nothing is lost.
- **Project rules in the external data home or IDE-specific rule folders** — rejected: rules must live with the workspace. Longrun reads only `.longrun/rules/*.md` and root `AGENTS.md`; it does not source project rules from `.trae/rules` or `<data>/projects/`. The `.longrun/` tree is gitignored; root `AGENTS.md` is the versioned instruction file.

## Consequences

- Per-workspace runtime state (`prompt.d/`, rule-switch metadata and the codebase index) remains in the data home.
- `<workspace>/.longrun/rules/*.md` is the sole folder source for project rules; root `AGENTS.md` is the only additive project instruction file. Both are protected prompt-bearing files.
- Workspace state adoption must preserve `.longrun/rules/` and must never migrate its contents to the external data home.
- Moving the root is a verified copy-then-remove with a progress report, not a rename.
