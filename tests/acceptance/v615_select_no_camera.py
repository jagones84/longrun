#!/usr/bin/env python3
"""v615 — cross-panel selection moves NO camera (select, don't travel).

Operator: clicking an AGENTS row must select the organigram node without
moving the organigram camera, and clicking an organigram node must select
the AGENTS row without moving the agents panel — in both directions.

Contract:
  A  focusAgent(sid, scroll) defaults to NO scroll; _applyFocus highlights
     always but scrolls only on the one-shot _scrollNext flag (the 5s poll
     re-render must not yank the table on every cycle);
  B  selectNode(sid, scroll) defaults to NO scroll; scroll only on
     scroll===true (explicit "take me there");
  C  the ONLY scroll=true path is focusAgentSession (Sessions rail menu);
     A-id clicks, node single/right clicks and onPick stay camera-still;
  D  the bridge forwards the flag (onHighlight passes scroll through).

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v615_select_no_camera.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: row side ----------------------
check("A1 focusAgent takes a scroll flag (default silent)",
      "focusAgent(sid, scroll)" in ORBIT and "const sc = (scroll === true)" in ORBIT)
check("A2 highlight is unconditional, scroll is one-shot",
      'tr.classList.add("rowsel")' in ORBIT and "if (!this._scrollNext) return;" in ORBIT
      and "this._scrollNext = false;" in ORBIT)
check("A3 the poll re-render cannot yank the table (flag consumed)",
      "this._applyFocus();" in ORBIT and "_scrollNext" in ORBIT)

# ---------------- B: organigram side ----------------------
check("B1 selectNode takes a scroll flag (default silent)",
      "selectNode(sid, scroll)" in ORBIT)
check("B2 the node scrolls ONLY on an explicit take-me-there",
      "if (scroll === true && hit)" in ORBIT)
check("B3 the remembered .sel repaint stays scroll-free",
      'x.classList.toggle("sel", x.dataset.sid === this.selSid)' in ORBIT)

# ---------------- C: one explicit path ----------------------
check("C1 ONLY the Sessions-rail menu travels (both sides scroll=true)",
      "this.agents.focusAgent(sid, true)" in ORBIT
      and "this.org.selectNode(sid, true)" in ORBIT)
check("C2 A-id click selects without travelling",
      "if (tr) this.focusAgent(tr.dataset.sid);" in ORBIT)
check("C3 node single/right click select without travelling",
      "this.selectNode(n.dataset.sid);" in ORBIT
      and "if (this.onPick) this.onPick(this.bySid[n.dataset.sid]);" in ORBIT)

# ---------------- D: the flag crosses the bridge ----------------------
check("D1 onHighlight forwards the scroll intent",
      "this.onHighlight(sid, sc)" in ORBIT
      and "(sid, scroll) => { try { this.org.selectNode(sid, scroll); }" in ORBIT)

print("---")
ok = sum(results)
print("\nv615: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
