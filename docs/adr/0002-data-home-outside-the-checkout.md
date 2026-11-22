# The data home lives outside the checkout

Everything the harness owns — sessions, the event log, indexes, costs, the self-evolution runtime and the operator's project rules — lives under ONE root (`~/.longrun`, `%LOCALAPPDATA%\Longrun` on Windows), never inside the repository.

We chose this so a `git pull`, a fresh clone or a container image can never replace or expose the operator's sessions, costs or rules. The root is movable (explicit override → a config value → the platform default); the small `config/` directory always stays at the default location, because it is the file that records where the root is.

## Considered Options

- **A `data/` directory inside the checkout** — rejected: it makes application state a merge conflict and puts user data one `git clean` away from deletion. A legacy in-repo `data/` is still served, flagged rather than silently migrated, so nothing is lost.

## Consequences

- Per-workspace state (project rules, prompt files, the codebase index) lives in the data home too, so a harness checkout never drops a `.longrun/` folder into a user's projects.
- Moving the root is a verified copy-then-remove with a progress report, not a rename.
