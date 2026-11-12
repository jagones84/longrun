#!/usr/bin/env python3
"""v962 — a phone/PWA is ASKED for the token, in the app's own dialog.

2026-11-11 (operator, from mobile): the installed PWA never asked for the token.
Reproduced with headless Chrome in mobile emulation (`.agent/trash/mobile_token_flow.py`):

  * fresh origin, no stored token -> a NATIVE `prompt()` is the only ask; the app's
    own dialog (the 2026-11-07 "every dialog is the app's own" rule) never opens;
  * a stored but REJECTED token -> no ask at all: every `/api` call 401s and the
    "Browser is not authenticated" card sits inside the sessions drawer, which is
    CLOSED by default on a phone, so the phone shows an empty app.

Pins: the ask is the app modal, a stored token is probed and a rejected one re-opens
the ask, and the probe is bounded so an offline phone does not stall boot.

Run: python3 tests/acceptance/v962_mobile_token_ask.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the ask is the app's own dialog, never the browser's -------------------
check("A1 the boot token ask is not a native prompt()",
      'prompt("Longrun API token' not in UI, "")
check("A2 the ask is the shared in-app modal (uiAsk)",
      "async function askServerToken(" in UI
      and "uiAsk({" in UI and 'title: "Connect to Longrun"' in UI, "")
check("A3 the typed token is probed before it is stored",
      "await tokenState(t)" in UI and 'if (st === "ok") return t;' in UI, "")
check("A4 a token the server cannot be asked about is kept, not discarded",
      'if (st !== "rejected") return t;' in UI, "")

# --- B: a stored but rejected credential asks again ---------------------------
check("B1 the stored token is validated at boot",
      "if (await tokenState(TOKEN) !== \"rejected\") return TOKEN;" in UI, "")
check("B2 a rejected stored token is cleared before the ask",
      'TOKEN = ""; localStorage.removeItem("sf_token");' in UI, "")
check("B3 the ask result is what the browser stores",
      "TOKEN = await askServerToken();" in UI
      and 'localStorage.setItem("sf_token", TOKEN);' in UI, "")

# --- C: an offline phone must not stall on the probe --------------------------
check("C1 the token probe is bounded (a dead network decides nothing)",
      "new AbortController()" in UI and "ctl.abort()" in UI, "")

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
