#!/usr/bin/env python3
"""v1057 — per-turn header, activity tally, Sources block, retry.

Static source pins: the turn header must be created at the first work item of a
turn, frozen on the persisted duration, and the Sources block must sit between
the answer and the turn footer. No browser, server or network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    html = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


check("A1 header starts at a real request", "if (rawText != null) _turnStart(d);" in html)
check("A2 header lands above the first work item",
      "_turnHeadPing();   // 2026-11-16: the turn header lands above the first work item" in html)
check("A3 header markup", 'head.className = "turnhead";' in html
      and 'class="twork"' in html and 'class="tally"' in html)
check("A4 live clock", "setInterval(_turnPaint, 1000)" in html)
check("A5 tally classes", "const _TALLY_LABEL = {" in html and "function _toolBump" not in html
      and "function _turnBump(tool)" in html)
check("A6 todo bookkeeping excluded", 'if (t.startsWith("todo.")) return;   // plan bookkeeping, not work' in html)
check("A7 frozen on chat.done", "if (d.session && d.session === sessionId) _turnEnd(d.duration_s);" in html)
check("A8 frozen on reload with persisted duration", "_turnEnd(m.duration_s, false);" in html)
check("A9 live answer attaches sources then footer",
      "const _foot = el => { _attachSources(el, t); _turnFoot(el, d); _turnEnd(d.duration_s); };" in html)
check("A10 reload attaches sources", "_attachSources(d, m.content);" in html)
check("A11 sources order after bubble / before footer",
      "if (foot) msgEl.insertBefore(el, foot); else msgEl.appendChild(el);" in html)
check("A12 sources markup", 'det.className = "sources";' in html and '"<summary>Sources · "' in html)
check("A13 fetched pages weigh more than hits", "host: pg.host || _hostOf(pg.url), weight: 2" in html)
check("A14 no borrowing a previous turn's hits", "if (!_turnT0 && !_turnHeadEl) return;" in html)
check("A15 retry button", 'rb.className = "retry"' in html and "function _retryTurn(raw, display)" in html)
check("A16 retry re-sends the model-facing raw", "send(txt, String(display == null ? txt : display));" in html)
check("A17 retry guarded while running", 'toast("this turn is still running — stop it before retrying", "warn");' in html)
check("A18 turn state resets with the chat tree",
      "_turnCounts = {}; _turnCards = []; _citeIndex = {};" in html)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
