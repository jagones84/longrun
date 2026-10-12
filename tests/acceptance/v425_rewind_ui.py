#!/usr/bin/env python3
"""v425 — WebUI rewind surface (JAG-426 follow-up).

Longrun shipped turn-anchored rewind in the API, but the WebUI exposed no control
for it (D2's "open point"). This pins the surface end-to-end at the static level:
the session menu offers "Rewind…", the dialog anchors are rendered and the two API
calls (GET the anchors, POST the rewind) are wired with the right parameters.

Deterministic (no model, no network).

Run: python3 tests/acceptance/v425_rewind_ui.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: the session menu offers a rewind entry -------------------------------
check("1a the session menu has a rewind action",
      'data-a="rewind"' in HTML, "")
check("1b the menu handler dispatches the rewind branch",
      'if (a === "rewind")' in HTML and "openRewindDlg(s.id)" in HTML, "")

# --- 2: the dialog markup exists and is wired to the dispatcher --------------
check("2a the rewind dialog exists", 'id="rwDlg"' in HTML, "")
check("2b the backdrop closes the dialog",
      'id="rwBackdrop"' in HTML and 'data-call="closeRewindDlg"' in HTML, "")
check("2c the dialog lists anchors in #rwList", 'id="rwList"' in HTML, "")
check("2d there is a CSS rule for the dialog", "#rwDlg {" in HTML, "")

# --- 3: the JS functions exist -----------------------------------------------
for fn in ("openRewindDlg", "closeRewindDlg", "doRewind"):
    check("3 the %s() function is defined" % fn, ("function " + fn + "(") in HTML, "")

# --- 4: the API calls carry the right parameters -----------------------------
check("4a openRewindDlg fetches the session anchors",
      '"/api/checkpoints?session="' in HTML, "")
check("4b doRewind POSTs the rewind",
      '"POST", "/api/rewind"' in HTML, "")
check("4c the rewind body carries session + msg_index",
      "session: sid, msg_index: idx" in HTML, "")
check("4d the renderer reads the `marks` payload",
      "data.marks" in HTML, "")

# --- 5: the dialog HTML is registered as a global (dispatcher resolves window) -
# the data-call dispatcher resolves window[name]; the functions are top-level
# `function` declarations, so they are hoisted onto the global object.
check("5 the functions are declared at top level (hoisted to window)",
      "\nfunction closeRewindDlg(" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
