# Harness checks are report-only, and `core/forge.py` is their only adapter

A module under `harness/checks/` is pure: data in, a verdict out, and no import of the running app. It is reachable **only** from the CLI, and `core/forge.py` is the single adapter that presents it. A check never executes a run, spawns a process, or spends model tokens.

We chose this so the check suite can be run against anything — a recorded trace, a fixture, a live workspace — without the checks becoming a second application. One adapter means the seam is real and visible: if a check needs a second entry point, that is a design signal, not a wiring detail.

## Considered Options

- **Let the app reach into `checks/` and call a check inline** — rejected: it would let a chat turn mutate or depend on a report-only surface, and it would split the "who may import it" answer across the codebase.

## Consequences

- Anything that executes or spends belongs in `harness/execution/`, which is gated and never reachable from a chat turn.
- A module that only tests import belongs in `checks/` — or it is dead code.
