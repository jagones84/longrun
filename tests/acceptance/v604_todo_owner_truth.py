#!/usr/bin/env python3
"""v604 (RED) — todo labels name a REAL owner (single source of truth).

"A155.n40" was a phantom: the node is "n40", its session's agent is A49,
its session number is J155 — no A155 exists anywhere (41 agents, jobs
J12-J22). Labels must resolve against the roster, never fabricate:

- designated session -> the agent id (A49.n40);
- plain session    -> its own session number in the J namespace (J180.n87);
- the header J-number carries a tooltip saying it is the session's own
  number, not a team job (those live in the Control tab).

Static, deterministic, no model/browser.
Run: python tests/acceptance/v604_todo_owner_truth.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_todo = HTML.split("function _todoid")[1][:600]
_segs = HTML.split('graphHead")')
_head = _segs[2].split("taskCount")[0] if len(_segs) > 2 else ""

check("T1 the label owner resolves against the roster (designated agent)",
      "_agents[sessionId]" in _todo)
check("T2 no fabricated agent id anywhere (phantom A155 class is gone)",
      '"A" + curJob' not in HTML and '"J" + curJob' in _todo)
check("T3 the header session number says what it is (not a team job)",
      "session number" in _head)
check("T4 no regression (counts, dropdown, history, rewind, roster map)",
      "nodes \u00b7 " in _head and "goalfull" in _head
      and "OLD PLAN" in HTML and "rewind to just before this todo" in HTML
      and "_agents[a.session] = a" in HTML)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
