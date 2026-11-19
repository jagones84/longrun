# AGENTS.md — start here (Longrun)

Orientation for an AI agent (or human) landing in this repo. Read in this order;
you should be productive within minutes and operate at the level of the agents
that built this.

## Read order (do not skip)

> `.agent/` is the maintainer's **local** working memory (all documents under
> `docs/` — `handoff/`, `runbooks/`, `plans/`, `research/` — plus tooling;
> update rules in `docs/MAINTENANCE.md`) and is **gitignored** — it
> exists only in a development checkout, never in a clone. Everything listed below
> is tracked and present in every clone.

1. **`docs/ARCHITECTURE.md`** and **`docs/CLI.md`** — how the system is wired.
2. **`docs/TESTING-PLAYBOOK.md`** — the mindset for testing the harness live.
3. **`CONTRIBUTING.md`** — how to run the gate, write a test, and the house style.
4. **`docs/RESEARCH-frontier-harnesses-2026.md`** — the research base and where Longrun
   sits vs. the 2026 frontier.

## The 60-second mental model

- A stdlib-only Python **agent harness** (`src/longrun/`), HTTP on `:8790`,
  SPA at `webui/index.html`, optional Orbit deck at `src/longrun/orbit/`.
- **Five object levels**: `Team (TN) → Job (JN) → Subjob (JN.k) → Agent (AX) → Todo
  (AX.nY)`. A **team** owns its roster; an **agent IS a session**
  (`agent["session"] == sid`). A **job** runs a coordinator + its team in dependency
  waves — the coordinator's PLAN turn is plan-only and read-only, the workers execute.
- **Everything is gated** behind `Authorization: Bearer <token>` (or `?token=`);
  the token lives in the service `EnvironmentFile`, never in the repo.
- State is files under `data/` (sessions, graphs, runs, edits, events.db, jobs).
- The **harness is the model's secretary**: it injects synthetic turns tagged
  `nudge` / `observation` / `continue`, persisted so the chat rebuilds them on reload.

## The one command that matters

```bash
bash tests/battery.sh     # FAST deterministic gate; trust its reported count
```

## Non-negotiables

- **Skills are local-only.** The user's personal skill library under `skills/`
  (symlinked categories) is **gitignored** — it is a development-checkout only artefact.
  The single tracked exception is the first-party `skills/core/repo-orientation` skill
  (self-orientation for an LLM landing here). See `.gitignore`.
- **No secrets in the repo.** `.env.template` is the only tracked env file.
- **Evidence over belief.** A claim needs a number (test count, HTTP status, file field).
- **`ast.parse` after any scripted patch.** Inspect the diff and restore only the
  affected hunk if a patch breaks; never overwrite unrelated user changes.
- **Checkpoint large refactors**, but never use destructive rollback commands
  (`git reset --hard`, `git checkout --`, `git clean`) over a dirty worktree.
- **Temporary agent scripts go to `.agent/trash/`**; do not put them in `scripts/`
  or the repo-root `trash/` data directory.
- **Maintainers: update the local (gitignored) `.agent/docs/handoff/HANDOFF.md` + the matching
  `docs/runbooks/*.md` in the same session. Section update rules: `.agent/docs/reference/MAINTENANCE.md`; the single spec index is `.agent/docs/tech-spec/SPEC-INDEX.md`.
- **Never kill an agent turn.** Restart only after BOTH the chat gate
  (`curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8790/api/chat/live` →
  `{"active": []}`) and the tool gate
  (`curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8790/api/tools/running` →
  `{"running": []}`) are empty — never chained with `&&`, then announce the restart and
  read the `service.resume` event afterwards. Full runbook: `docs/OPERATIONS.md`.
- **Reports to the operator** (proposals, rankings, diagrams) follow `docs/REPORTING.md`.

## Source layout — place by runtime role, not by subject (2026-11-20)

A new module goes where its ROLE lives; the folder answers "who may import it, and what can start it?".
Place it by these three questions, in order:

1. **Imported by the running app** (agent loop, HTTP route, tool dispatch, memory/model/plan
   machinery) → the owning package: `agent/`, `core/`, `tools/`, `memory/`, `model/`, `plan/`,
   `orchestrate/`, `evolve/`, `orbit/`, `research/`, `interop/`, `util/`.
2. **Pure — data in, verdict out, no app imports — reachable only from the CLI** →
   `src/longrun/harness/checks/`. Report-only; `core/forge.py` is the only adapter.
3. **Executes a run, spawns a process or spends model tokens** →
   `src/longrun/harness/execution/`. Gated; never reachable from a chat turn.

Anything the app imports from `harness/` stays at the `harness/` root. No new top-level package for one
subject; no round/paper names in paths (the reference goes in the docstring); a module only tests import
belongs in `checks/` (or it is dead — say so). A move updates every importer, `core/forge.py`, tests and
docs in the same commit, and is proven by the import audit + `python3 forge.py harness` + the battery.

