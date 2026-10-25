#!/usr/bin/env python3
"""v600 (RED) — the AGENTS table gets the same explicit "go to chat session"
button the JOBS list already has, reusing the deck's shared `onOpenAgent`
callback (no duplicated open logic, JAG-335/484 precedent).

- `AgentsView` accepts `onOpenAgent` like `JobsView` does;
- each designated-agent row renders a `data-go` session button
  (plain sessions have no A-id: no button, nothing to open);
- the deck wires the same `(aid) => this.openAgent(aid)` into both views;
- clicks stopPropagation (a row click must not toggle/select anything else).

Static, deterministic, no model/browser.
Run: python3 tests/acceptance/v600_agents_session_button.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_av = ORBIT.split("class AgentsView")[1].split("class Constellation")[0]
_jv = ORBIT.split("class JobsView")[1].split("class RoutinesView")[0]

check("A1 AgentsView accepts the shared onOpenAgent callback",
      "constructor(api, onChanged, onOpenAgent)" in _av
      and "this.onOpenAgent = onOpenAgent" in _av)
check("A2 agent rows render a session button keyed by agent id",
      'data-go="' in _av and "session" in _av.split('data-go="')[1][:120].lower())
check("A3 the button only fires the shared callback (no second opener)",
      "_deckGo" not in _av and "gotoAgent" not in _av and "postMessage" not in _av)
check("A4 the row click does not leak through the button",
      "stopPropagation" in _av.split('querySelectorAll("[data-go]")')[1][:400]
      if 'querySelectorAll("[data-go]")' in _av else False)
check("A5 the deck wires the SAME opener into both views",
      "new AgentsView(this.api, () => this.refresh(), (aid) => this.openAgent(aid))" in ORBIT
      and "new JobsView(this.api, () => this.refresh(), (aid) => this.openAgent(aid))" in ORBIT)
check("A6 the jobs view still owns its own button (untouched)",
      'data-go="' in _jv and "this.onOpenAgent(b.dataset.go)" in _jv)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
