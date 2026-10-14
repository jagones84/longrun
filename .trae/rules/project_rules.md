# Longrun — Project Rules (TRAE)

Read this before touching the harness. It captures the **operational knowledge**
that is not obvious from the code. Written in English (the product is English-only;
only the chat may be in the operator's language). read your global rules first. use Caveman skill. Use appropriate sets of skills in geenral if needed for specific scopes.

## What this is

Longrun = a local frontier-style agent harness (WebUI + HTTP/SSE API) running on a
DGX Spark (GB10, ARM64) behind a llama.cpp router on `:8080`. Repo root =
`/home/jagones/Repositories/longrun`. On this Windows PC the repo is mounted at
`Z:\\Repositories\\longrun` (Z: **is** the DGX home, never copy between them).

## Golden rules

## The quality gate (the ONLY regression gate)

```bash
bash tests/battery.sh                          # FAST gate: \~12s, heavy tests skipped, PARALLEL
LONGRUN\_BATTERY\_FULL=1 bash tests/battery.sh   # FULL suite (\~1min)
LONGRUN\_BATTERY\_JOBS=1 bash tests/battery.sh   # force sequential (debug a flaky test)
```

Tests auto-discover from `tests/acceptance/v\*.py`, each ISOLATED (own `LONGRUN\_\*`
temp dirs). The 6 heavy tests (vector-index builds / doc ingestion) are skipped
unless `LONGRUN\_BATTERY\_FULL=1`. When you ADD a test, bump the README badge count
(`N/N`) — `v354` checks it. Every acceptance test must be deterministic: **no live
model, no network, no server**.

## Testing the WebUI live with Chrome DevTools MCP

The WebUI is a vanilla-JavaScript SPA served by the Longrun process that owns
the REST API. Use the configured Chrome DevTools MCP page for live checks. MCP
interactions do not move the user's mouse or send OS-level keystrokes. Do not
use `Start-Process`, `SendKeys`, `SetCursorPos`, `SetForegroundWindow`, or
PowerShell screenshots to operate this page.

### 1. Find the authorized Longrun page

1. Call `mcp_chrome-devtools_list_pages` before any page interaction.
2. Reuse the existing authenticated Longrun page when it is listed. Keep its
   numeric `pageId`; do not copy its full URL because the query may contain the
   auth token.
3. If no Longrun page is open, use LAN first:
   `http://192.168.1.37:8790/?token=<LONGRUN_TOKEN>`.
   Use Tailscale `http://100.102.61.23:8790/` only if LAN is unavailable.
   Open it with `mcp_chrome-devtools_new_page` or
   `mcp_chrome-devtools_navigate_page`.
4. Read `LONGRUN_TOKEN` from the ignored repository `.env` or the configured
   Longrun environment file. Never write its value into this document, scripts,
   chat, screenshots, or command output. If exposed, rotate it.
5. Never use `localhost:8790` from Windows; it targets the Windows host.

The query token is the documented browser authentication handshake. The WebUI
stores it for that origin after its first authorized request. Prefer reusing
the existing authorized page so no new tokenized URL is needed.

### 2. Interact only through DevTools MCP

1. Call `mcp_chrome-devtools_take_snapshot` with the numeric `pageId` before
   interacting. Use the latest snapshot UID for each target.
2. Use `mcp_chrome-devtools_click`, `mcp_chrome-devtools_fill`,
   `mcp_chrome-devtools_press_key`, or `mcp_chrome-devtools_type_text`.
   Resnapshot after navigation or DOM changes because UIDs can change.
3. Use `mcp_chrome-devtools_evaluate_script` only for task-scoped, read-only
   inspection. Never read cookies, `localStorage`, or auth material; never use
   page JavaScript to make external requests or mutate the UI.
4. Capture visual proof with `mcp_chrome-devtools_take_screenshot`.
   Check browser errors with `mcp_chrome-devtools_list_console_messages`.
5. Use MCP actions only. Do not switch to the integrated browser, OS Chrome
   automation, or keyboard/mouse control when a page action fails. Diagnose
   the MCP error and retry with a fresh snapshot and valid numeric `pageId`.

### 3. Cross-check real backend state

The sidebar uses `GET /api/sessions`; thread titles use
`GET /api/threads?session=<sid>`; the plan uses
`GET /api/sessions/<sid>/graph`; context uses `GET /api/context`. Routes are
registered in `src/longrun/core/httpapi.py` and `src/longrun/core/api_v02.py`.
Compare the visible panel with its REST response. Keep bearer values private.

The sidebar does not automatically refresh after a session is created through
REST. Reload the page with `mcp_chrome-devtools_navigate_page` on the same
`pageId`, then verify that the new session appears.

### 4. Live verification criteria

For a WebUI change, capture a DevTools MCP screenshot and cross-check the same
state through REST. Check the console for errors. Acceptance tests alone and
REST responses alone do not prove the rendered UI is correct. The deterministic
regression gate is still `bash tests/battery.sh`; it does not replace live UI
verification.

## Commands on the DGX

Windows host → DGX over SSH: `ssh dgx "<cmd>"` (cwd `C:\\Users\\giova`; a UNC cwd
breaks the shell). Repo reads = native `Read`/`Grep` on `Z:` paths. **Never inline
quotes/`\&\&`/`;`** **in an ssh command** — write a `.sh` file and run
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

