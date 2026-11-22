# Modules are placed by runtime role, not by subject

A new module goes where its ROLE lives, and the folder answers two questions: *who may import it, and what can start it?* The three roles, in order: (1) imported by the running app → the owning package; (2) pure, data-in/verdict-out, CLI-only → `harness/checks/`; (3) executes a run, spawns a process or spends tokens → `harness/execution/`.

We chose this over a subject-based layout (a folder per feature or per paper) because the harness grows by agents adding modules, and a role-based answer is decidable without asking the maintainer. It also keeps round/paper provenance out of paths: the reference goes in the docstring.

## Consequences

- No new top-level package for a single subject; no round or paper names in paths.
- A move must update every importer, the adapter, the tests and the docs in the same commit, and is proven by the import-audit pin (`tests/acceptance/v1273_checks_reachability.py`) plus the harness command plus the battery.
