#!/usr/bin/env python3
"""v329 — the Orbit 5s poll must not destroy an OPEN <select> (JAG-329).

The agents table is rebuilt every 5 seconds (`setInterval(() => this.refresh(), 5000)`
-> AgentsView.render -> body.innerHTML = ...). It already deferred the rebuild while a
text field was focused, but NOT while a native <select> (the MODEL / REPORTS-TO
dropdown) was open — so choosing a model closed itself "after a timer, even while it
is open for selection". The guard must cover every form control.

Deterministic, source-locked. Run: python3 tests/acceptance/v329_select_survives_poll.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    o = f.read()

check("A1 the poll guard covers SELECT (model / reports-to dropdowns)",
      'ae.tagName === "SELECT"' in o)
check("A2 the guard still covers INPUT and TEXTAREA",
      'ae.tagName === "INPUT"' in o and 'ae.tagName === "TEXTAREA"' in o)
check("A3 the rebuild is still deferred while a control is live",
      "if (editing || roleDirty) return;" in o)
check("A4 the 5s auto-poll that this guards still exists",
      "setInterval(() => this.refresh(), 5000)" in o)
check("A5 the model select is really a <select> in the table",
      '<select class="inp mini"' in o and 'data-f="model">' in o)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

