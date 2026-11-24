# AGENTS.md — start here (Longrun)

Orientation for an AI agent (or human) landing in this repo. `.agent/` is the
maintainer's local working memory (gitignored, development checkout only); everything
below is tracked and present in every clone.

## Read order (do not skip)

1. **`GLOSSARY.md`** — the project vocabulary; it stops `job`/`run`/`turn` from drifting.
2. **`docs/adr/`** — hard-to-reverse decisions and the rejected alternative; surface a
   conflict instead of re-litigating it silently.
3. **`docs/ARCHITECTURE.md`** and **`docs/CLI.md`** — how the system is wired.
4. **`docs/TESTING-PLAYBOOK.md`** — the mindset for testing the harness live.
5. **`CONTRIBUTING.md`** + **`CODING_STANDARDS.md`** — the gate and the standards.
6. **`docs/RESEARCH-frontier-harnesses-2026.md`** — the research base.

## The 60-second mental model

- Stdlib-only Python **agent harness** (`src/longrun/`), HTTP on `:8790`, SPA at
  `webui/index.html`, optional Orbit deck at `src/longrun/orbit/`.
- **Five levels**: `Team (TN) → Job (JN) → Subjob (JN.k) → Agent (AX) → Todo (AX.nY)`.
  An **agent IS a session** (`agent["session"] == sid`). A **job** runs a read-only
  coordinator PLAN + workers in dependency waves; an in-chat `batch` is a **Session Job
  (SJ<n>)** that lives in the session's ledger and dies with the chat.
- **Everything is gated** behind `Authorization: Bearer <token>` (or `?token=`); the
  token lives in the service `EnvironmentFile`, never in the repo.
- State is files under `data/` (sessions, graphs, runs, edits, events.db, jobs,
  session_jobs).
- The **harness is the model's secretary**: it injects synthetic `nudge` / `observation` /
  `continue` turns, persisted so the chat rebuilds them on reload.

## The commands that matter

```bash
bash scripts/check.sh     # syntax + lint + types, ratcheted — after every edit
bash tests/battery.sh     # full deterministic gate; trust its reported count
```

`check.sh` is a **ratchet**: it fails when a count *increases*, so a new unused import,
undefined name or type slip is caught in seconds (`pyproject.toml` owns the rules).

## Non-negotiables

- **Skills are local-only** under `skills/` (gitignored, dev checkout only); the single
  tracked exception is `skills/core/repo-orientation`.
- **No secrets in the repo.** `.env.template` is the only tracked env file.
- **Evidence over belief.** A claim needs a number (test count, HTTP status, file field).
- **`ast.parse` after any scripted patch**; never overwrite unrelated user changes.
- **A CLI route is declared once** in `core/forge.py` `ROUTES` (handlers call
  `req(*_route("name"))`); `v588`/`v1276` hold you to it, adding a command adds its route.
- **Checkpoint large refactors**, never destructive rollback (`git reset --hard`,
  `git checkout --`, `git clean`) over a dirty worktree.
- **Temporary agent scripts go to `.agent/trash/`**, not `scripts/`.
- **Maintainers** update `.agent/docs/handoff/HANDOFF.md` + the matching
  `docs/runbooks/*.md` in the same session (`.agent/docs/reference/MAINTENANCE.md`;
  spec index `.agent/docs/tech-spec/SPEC-INDEX.md`).
- **Never kill an agent turn.** Restart only when both `/api/chat/live` and
  `/api/tools/running` answer empty (never chained with `&&`), then announce it and read
  `service.resume` (`docs/OPERATIONS.md`).
- **Reports to the operator** (proposals, rankings, diagrams) follow `docs/REPORTING.md`.

## Source layout — by runtime role, not by subject

Place a new module by its ROLE ("who may import it, and what can start it?"), in order:

1. **Imported by the running app** → the owning package: `agent/`, `core/`, `tools/`,
   `memory/`, `model/`, `plan/`, `orchestrate/`, `evolve/`, `orbit/`, `research/`,
   `interop/`, `util/`.
2. **Pure, no app imports, CLI-only** → `src/longrun/harness/checks/` (report-only;
   `core/forge.py` is the only adapter).
3. **Spawns a process or spends tokens** → `src/longrun/harness/execution/` (gated).

No new top-level package; no round/paper names in paths; a module only tests import
belongs in `checks/` (or it is dead). A move updates every importer, `core/forge.py`,
tests and docs in the same commit (proven by `v1273` + `python3 forge.py harness` + battery).

## Agent skills

Work is tracked as local markdown under `.scratch/<feature>/` (`spec.md` +
`issues/<NN>-<slug>.md`, see `docs/agents/issue-tracker.md`); domain docs are one
`GLOSSARY.md` + `docs/adr/` (see `docs/agents/domain.md`).
