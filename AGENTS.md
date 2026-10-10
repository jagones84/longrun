# AGENTS.md — start here (Longrun)

Orientation for an AI agent (or human) landing in this repo. Read in this order;
you should be productive within minutes and operate at the level of the agents
that built this.

## Read order (do not skip)

> `.agent/` is the maintainer's **local** working memory (HANDOFF + per-domain
> manuals) and is **gitignored** — it exists only in a development checkout, never
> in a clone. Everything listed below is tracked and present in every clone.

1. **`docs/ARCHITECTURE.md`** and **`docs/CLI.md`** — how the system is wired.
2. **`docs/TESTING-PLAYBOOK.md`** — the mindset for testing the harness live.
3. **`CONTRIBUTING.md`** — how to run the gate, write a test, and the house style.
4. **`docs/RESEARCH-frontier-harnesses-2026.md`** — the research base and where Longrun
   sits vs. the 2026 frontier.

## The 60-second mental model

- A stdlib-only Python **agent harness** (`src/longrun/`), HTTP on `:8790`,
  SPA at `webui/index.html`, optional Orbit deck at `src/longrun/orbit/`.
- **Five object levels**: `Team (TN) → Job (JN) → Subjob (JN.j) → Agent (AX) → Todo
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
bash tests/battery.sh     # 127/127 GREEN required before any commit
```

## Non-negotiables

- **Skills are local-only.** The user's personal skill library under `skills/`
  (symlinked categories) is **gitignored** — it is a development-checkout only artefact.
  The single tracked exception is the first-party `skills/core/repo-orientation` skill
  (self-orientation for an LLM landing here). See `.gitignore`.
- **No secrets in the repo.** `.env.template` is the only tracked env file.
- **Evidence over belief.** A claim needs a number (test count, HTTP status, file field).
- **`ast.parse` after any scripted patch**; `git checkout -- <file>` if you break it.
- **Checkpoint before refactor**, then `git reset --hard <checkpoint>` to roll back.
- **Trash goes to `trash/`**, temp scripts never pollute `scripts/` or the repo root.
- **Maintainers: update the local (gitignored) `.agent/HANDOFF.md` + the matching `README-*.md` in the same session.**
