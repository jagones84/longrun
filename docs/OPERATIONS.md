# Agent turns — never kill them, never declare them dead

> The restart-safety essentials are mirrored in `AGENTS.md` §"Non-negotiables" (loaded by both the
> IDE agent and Longrun's own agents); this file is the full procedure.

A running turn is live work: a model call, files being written, a plan in flight. Killing it
silently is the worst failure this harness can have, and the operator has said so
("agents that stop unexpectedly ... that's the worst thing can happen"). These rules are
mandatory for every agent working in this repository.

## Before ANY service restart

1. **Proof of idleness first.** A restart is allowed only when this answers with an empty list:
   `curl -s -H "Authorization: Bearer $(grep -m1 '^LONGRUN_TOKEN=' .env | cut -d= -f2-)" \
      http://127.0.0.1:8790/api/chat/live`
   → `{"active": []}`. If anything is active, **wait**; re-check every few seconds.
   Never chain it (`curl … && systemctl --user restart longrun`): `&&` runs on a NON-empty answer too.
   Parse the JSON and exit when the list is not empty — on 2026-11-16 this exact chain restarted the
   service under session `5033e643711a` (resumed from `service.resume`, but still an avoidable abort).
2. Never `kill`, `pkill`, `kill -9` or `systemctl stop` the service to make a change land.
   `systemctl --user restart longrun` is the only supported form, and only under rule 1.
3. Announce it in the same message: what changed, why the restart, and that a turn was or was
   not running. A silent restart is a hidden data loss.
4. A parallel stream may restart the service at any time. Re-read `ActiveEnterTimestamp`
   (`systemctl --user show longrun -p ActiveEnterTimestamp`) before blaming your own code for a
   turn that "stopped".

## After a restart

5. Read the recovery record — it names what was resumed, not what was lost:
   `GET /api/events?kind=service.resume` (or the `service.resume` row in `data/events.db`).
   `{"running": [...], "resumed": [...], "skipped": [...]}` is the answer.
6. A session whose last message says *"interrupted by a service restart"* may already be running
   again in the background: the harness delivers a `[Harness restart]` continuation message.
   **Read the stored history before re-briefing** (`GET /api/history?session=<id>`); sending the
   same brief twice is a defect, not a retry.
7. Never report "the agent stopped / the work was lost" until you have quoted, for that session:
   the session id, the last message index, and whether a `[Harness restart]` message follows.

## Diagnosing "an agent stopped"

8. There are exactly three causes. Name the one you measured; do not guess:
   - **Killed by a restart** — the transcript ends with `error_detail: "interrupted-by-restart"`.
     Check `service.resume` (rule 5): it was resumed, or it is waiting for the operator.
   - **Blank / unusable model reply** — an empty assistant turn followed by harness nudges
     (`harness → LLM NUDGE`), or `error_detail: "empty reply from the model"`. The turn is closed
     with an explicit record; it is not silent. The transport now records `finish_reason` /
     `reasoning_tokens`, and a reasoning-only reply fails over to another model.
   - **Orphaned run row** — `runs.status = 'running'` with a `ts` older than the current process.
     `tracing.reconcile_orphans()` closes these at boot as `interrupted`; report the count from
     `runs.reconciled`, never edit `events.db` by hand.
9. The UI rail reads in-process runs only; the `runs` table is the audit. A row is not evidence
   that something is running now — `/api/chat/live` and `/api/tools/running` are.

## The worktree is shared

10. Several agents edit these same files. Never create a branch and never `git add -A`:
    stage the files you actually changed (and, in a file another agent is editing, only your
    hunks). Commit and push on `Experimental-Refactor` — one branch, one history, no merge.
