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

## Testing the WebUI live (no batch, no headless — drive it like a human)

The harness's UI is a vanilla-JS single page served by the same longrun process
that owns the REST API. The page is the same code that real users run; treat
what you see there as the only "live" evidence. There is **no headless
playwright** flow and **no `battery.sh` for UI** — the WebUI is verified by
opening it in a real browser, exercising one or two endpoints, and reading the
rendered state.

### 1. Reach the server (LAN first, Tailscale fallback)

The DGX is on two networks simultaneously. **Always try LAN first** — it has no
Tailscale auth gate, no extra DNS, no relay latency:

| URL                                     | When to use                                  |
|-----------------------------------------|----------------------------------------------|
| `http://192.168.1.37:8790/?token=<t>`   | Default. Inside the LAN.                     |
| `https://192.168.1.37:8791/?token=<t>`  | Same, over TLS (self-signed — `-k` in curl). |
| `http://100.102.61.23:8790/?token=<t>`  | Tailscale (MagicDNS or IP). Only if LAN is down or you are off-site. Note: a `?token=` URL is **not** a "trick" — it is the documented auth handshake; the browser stores it in `localStorage` after the first call. |
| `http://spark-6263:8790/?token=<t>`     | Same as above (MagicDNS name).               |

**Do not** use `localhost:8790` from Windows — that resolves to the local
Windows process if any, not the DGX. Always use the LAN/Tailscale IP.

### 2. Where the token lives

- Live value: read it from the running service.
  - DGX: `journalctl --user -u longrun | grep -i token` (the unit prints it at
    startup) or `grep ^LONGRUN_TOKEN ~/.config/longrun/env`.
  - Windows: `C:\Users\giova\.hermes\.env` (if populated by `deploy/longrun.service`).
  - Repo fallback: `Z:\Repositories\longrun\.env` (gitignored, copy of `.env.template`).
- The token gates every REST route (`Authorization: Bearer <t>`) **and** the
  WebUI (`?token=<t>` in the URL). The server starts with no auth when the
  token is empty, but that is a security risk the moment the port is reachable
  from anything other than localhost.
- **If you ever paste the token in chat, revoke and regenerate it.** The
  generation endpoint is `https://github.com/settings/tokens` (or whatever
  issued it).

### 3. Open it in a real browser (the only supported driver)

```powershell
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  -ArgumentList "--new-window", "http://192.168.1.37:8790/?token=<token>"
```

- Use the OS Chrome, **not** the Chrome DevTools MCP instance. The MCP instance
  is a separate process tree; screenshots/UI events you trigger there do not
  reach the user's actual browser, and the user can never see what the MCP
  "sees".
- Chrome DevTools MCP is fine for **navigation** and **list-pages** (those
  calls do not require `pageId`). It is **broken** for any tool that takes
  `pageId: number` (take_snapshot, evaluate_script, take_screenshot,
  click, type_text, …) because the TRAE→MCP bridge serialises the number as a
  string and the validator rejects it. Do not waste turns trying to work
  around it — drive the OS browser instead.

### 4. Capture evidence (PowerShell + .NET, no MCP)

The user is the one who looks at the browser. To bring back proof to chat, take
a screenshot of the OS Chrome window and attach it. The working pattern is:

```powershell
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class WinH {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
'@
$h = (Get-Process chrome | Where-Object MainWindowTitle -match 'Longrun')[0].MainWindowHandle
[WinH]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 800
$rect = New-Object WinH+RECT
[void][WinH]::GetWindowRect($h, [ref]$rect)
$bmp = New-Object System.Drawing.Bitmap ($rect.R - $rect.L) ($rect.B - $rect.T)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.L, $rect.T, 0, 0, (New-Object System.Drawing.Size ($rect.R - $rect.L) ($rect.B - $rect.T)))
$bmp.Save("$env:TEMP\longrun_$(Get-Date -Format yyyyMMdd_HHmmss).png")
```

The user pastes that PNG into chat (drag-and-drop, or via the screenshot skill).
Do not invent "I see X" claims — only describe what the image actually shows,
and only after attaching it.

### 5. Cross-check the UI by reading the same REST it reads

The WebUI's sidebar is `GET /api/sessions`, the per-session transcript is
`GET /api/threads?session=<sid>`, the live plan is `GET /api/sessions/<sid>/graph`,
the cost/context is `GET /api/context`. The full surface is registered in
`src/longrun/core/httpapi.py` (older routes) and `src/longrun/core/api_v02.py`
(newer routes). If a panel is empty, hit the corresponding endpoint with
`curl -H "Authorization: Bearer <t>"` and compare.

**Important quirk**: the sidebar list is **not** auto-refreshed when you
navigate the chat. After a REST call that creates a session, the user must
press `F5` in the browser to repopulate the sidebar. State this in the report
so the user knows the bug is in the UI's polling, not in the data.

### 6. What "verified live" means (and does not mean)

- ✓ PASS: you have a screenshot of the OS Chrome window showing the new state,
  **and** a REST call that returns the same state.
- ✗ Not a verification: a successful REST call alone (no screenshot), a
  Chrome DevTools MCP call (driver is broken), or a smoke test against an
  in-process handler.
- ✗ Not a verification: a screenshot of the headless MCP browser. The user
  cannot see it; treat the MCP browser as a black box that may show anything.

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

<http://100.102.61.23:8790/?token=nKVlAmB04UatWhYSemN0MebYp_7SC5fj>
