#!/usr/bin/env python3
"""v307 — the UI must not count CLOSED states as open (JAG-307).

After JAG-306 closed the job's todos, the coordinator session still LOOKED
unfinished: its graph has 22 done + 3 superseded, yet the deck's TASKS chip said
"3 open / 25" and the panel could resurface old plans' steps. `superseded` and
`cancelled` are CLOSED. Locked here (marker checks on the UI sources):
  * the deck chip counts ONLY truly-open statuses (todo/doing/blocked);
  * the Plan panel mark table renders `superseded` as closed;
  * the panel never falls back to the UNION of every plan's nodes.

Deterministic, no browser. Run: python3 tests/v307_open_count.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


deck = read("webui", "console.html")
ui = read("webui", "index.html")

# --- deck TASKS chip: count only truly-open -------------------------------------
check("deck defines the truly-open set", 'const _OPEN = ["todo", "doing", "blocked"]' in deck)
check("deck counts via the truly-open set", "_OPEN.includes(String(n.status))" in deck)
check("deck no longer counts every non-done node as open",
      '.filter(n => String(n.status) !== "done").length + " open' not in deck)

# --- plan panel: closed states + no union fallback ------------------------------
check("panel renders superseded as closed (mark table)",
      'superseded: "⊘"' in ui)
check("panel no longer falls back to the union of all plans",
      "_nodes = _pn.length ? _pn : (graph.nodes || []);" not in ui)
check("panel falls back to the LATEST plan that has steps", "_maxp" in ui
      and "=== _maxp" in ui)
check("fallback explicitly labels the prior plan as history",
      "Current plan " in ui and "is empty; showing historical plan " in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
