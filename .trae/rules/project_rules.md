# Longrun — Project Rules (TRAE)

Read this before touching the harness. It captures the **operational knowledge**
that is not obvious from the code. Written in English (the product is English-only;
only the chat may be in the operator's language).

-read your global rules first

## What this is

Longrun = a local frontier-style agent harness (WebUI + HTTP/SSE API) running on a
DGX Spark (GB10, ARM64) behind a llama.cpp router on `:8080`. Repo root =
`/home/jagones/Repositories/longrun`. On this Windows PC the repo is mounted at
`Z:\Repositories\longrun` (Z: **is** the DGX home, never copy between them).

## Golden rules

## The quality gate (the ONLY regression gate)

```bash
bash tests/battery.sh                          # FAST gate: ~12s, heavy tests skipped, PARALLEL
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # FULL suite (~1min)
LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh   # force sequential (debug a flaky test)
```

Tests auto-discover from `tests/acceptance/v*.py`, each ISOLATED (own `LONGRUN_*`
temp dirs). The 6 heavy tests (vector-index builds / doc ingestion) are skipped
unless `LONGRUN_BATTERY_FULL=1`. When you ADD a test, bump the README badge count
(`N/N`) — `v354` checks it. Every acceptance test must be deterministic: **no live
model, no network, no server**.

## Testing the WebUI live (Chrome DevTools MCP)

Server: `http://192.168.1.37:8790/?token=<token>` (also HTTPS `:8791`). The token is
in `journalctl --user -u longrun` startup output, or the `longrun.service` unit.

## Commands on the DGX

Windows host → DGX over SSH: `ssh dgx "<cmd>"` (cwd `C:\Users\giova`; a UNC cwd
breaks the shell). Repo reads = native `Read`/`Grep` on `Z:` paths. **Never inline
quotes/`&&`/`;`** **in an ssh command** — write a `.sh` file and run
`ssh dgx "bash /home/jagones/Repositories/longrun/<path>.sh"`.

## Where things live

## UI surfaces (keep them truthful — "I see what is real")

Every panel must read REAL backend state, never a stub. Key panels: Sessions,
Inspector (right rail), **Settings** (Appearance / Models / **Subagents** / Knowledge
/ Keys / MCP / Skills / Rules / Harness / Tool policy / **Improvement** / Info).

## WebUI driving / editing conventions

## Workflow

Plan → code → run → check → fix → run → check. Finish only when it runs AND the
output is verified (battery green + live WebUI evidence). Leave the tree clean:
temp scripts in `.agent/trash/` (or delete them), keep `HANDOFF.md` current.
