#!/usr/bin/env python3
"""v636 — the rest of the RH rail: one field, one save, icon-only hand-offs.

Operator: "goal and graph node still not compact", "the save button eats space in
session role", "the other RH sections still look bad".

Contract:
  A) Plan: ONE input feeds both verbs (▶ goal / + node / ↻ replan); `taskInp` is
     gone and `addTask` reads the shared field.
  B) Rules: `save` is a link on the path row (no second row of chrome); the id
     `rule_<kind>_save` and the dirty marker are unchanged, so every handler
     works as before.
  C) Workspace: the placeholder is host-agnostic, browse/editor are icon buttons
     with an accessible name, and `#wsSave` keeps the `config-save` wiring.
  D) Codebase: the caps "Search codebase" title is gone (the input says it).

Run: python tests/acceptance/v636_rail_fields.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v636_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

# ---- A. Plan: one field -------------------------------------------------------
check("A1 the second input is gone", 'id="taskInp"' not in UI)
check("A2 one field feeds the three verbs",
      'id="planInp" class="inp u-f1 u-p610 u-fs12" placeholder="goal or node…"' in UI
      and UI.index('id="planInp"') < UI.index('data-call="planGoal"')
      and UI.index('data-call="planGoal"') < UI.index('data-call="addTask"')
      and UI.index('data-call="addTask"') < UI.index('data-call="replanGraph"'))
check("A3 addTask reads the shared field",
      'const v = $("planInp").value.trim();' in UI
      and '$("planInp").value = "";' in UI)
check("A4 Enter in the field runs the goal (no orphan listener)",
      'data-key="Enter" data-key-fn="planGoal"' in UI
      and '$("taskInp").addEventListener' not in UI)

# ---- B. Rules: save on the path row ------------------------------------------
check("B1 save is a link on the path row",
      '<button type="button" class="lnk" id="\' + id + \'_save"' in UI
      and '<div class="rpath"><span title=' in UI)
check("B2 the old full-width save row is gone",
      '<div class="rrow"><button class="ghost" id="\' + id + \'_save"' not in UI)
check("B3 the dirty marker and the handler survive",
      "function markRuleDirty(kind)" in UI and "classList.add(\"dirty\")" in UI
      and ".rpath .lnk.dirty {" in UI)

# ---- C. Workspace -------------------------------------------------------------
check("C1 the placeholder is short and host-agnostic",
      'placeholder="folder path…"' in UI
      and 'placeholder="folder path — use 📁 browse… (any folder the harness host can read)"' not in UI)
check("C2 browse / editor are icon buttons with an accessible name",
      'aria-label="browse folders"' in UI and 'aria-label="open the editor"' in UI
      and ">📁</button>" in UI and ">🗔</button>" in UI)
check("C3 the save keeps its config-save wiring",
      'class="ghost config-save" id="wsSave"' in UI)

# ---- D. Codebase --------------------------------------------------------------
check("D1 the caps search title is gone; the input says it",
      "Search codebase</h2>" not in UI
      and 'placeholder="search the codebase…"' in UI)

print("\nv636: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
