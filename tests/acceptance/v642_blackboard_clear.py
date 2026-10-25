#!/usr/bin/env python3
"""v642 — the blackboard can be emptied, and the editor survives the Control deck.

Operator: "Swarm and blackboard non capisco … si possono cancellare le cose che
si fanno? rimangono per sempre lì? c'è un clear all?" and "se vado page control
l'editor è staccato alla sua finestra, non la riesco più a spostare o chiudere".

Contract:
  A) swarm.clear() really empties the board (one topic, or all), and the version
     counter restarts from #1 (ids follow the surviving entries).
  B) DELETE /api/blackboard is wired to it.
  C) The panel offers `clear all` with a confirm; the three explanatory prose
     cards are tooltips; the Subagents cross-link survives.
  D) The floating editor is moved out of the inert #app while Control is up and
     put back exactly where it was afterwards.

Run: python tests/acceptance/v642_blackboard_clear.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v642_")
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
EDITOR = src("webui", "assets", "editor.js")
API = src("src", "longrun", "core", "api_v02.py")

from longrun.agent import swarm as S   # noqa: E402 — after the env is set

# ---- A. the store ------------------------------------------------------------
S.post("t1", "first")
S.post("t2", "second")
S.post("t1", "third")
check("A1 three entries are stored", len(S.get(limit=10)) == 3, S.get(limit=10))
r = S.clear("t1")
check("A2 clear(topic) removes only that topic", r.get("removed") == 2
      and [e["topic"] for e in S.get(limit=10)] == ["t2"], r)
r2 = S.clear()
check("A3 clear() empties the board", r2.get("removed") == 1 and S.get(limit=10) == [], r2)
e = S.post("t", "after the clear")
check("A4 versions restart from #1 (ids follow the surviving entries)",
      e.get("version") == 1, e.get("version"))

# ---- B. the route ------------------------------------------------------------
del_section = API[API.find('if method == "DELETE":'):]
check("B1 DELETE /api/blackboard exists", 'if path == "/api/blackboard":' in del_section)
check("B2 it calls swarm.clear with the topic filter", "_SWARM.clear(qs.get(\"topic\"))" in del_section)
check("B3 the store has the function", "def clear(topic=None):" in src("src", "longrun", "agent", "swarm.py"))

# ---- C. the panel ------------------------------------------------------------
check("C1 the panel offers a real clear-all", 'data-call="bbClearAll"' in UI)
check("C2 it asks before wiping", 'confirmDelete("delete every blackboard entry' in UI)
check("C3 it calls the DELETE door", 'api("DELETE", "/api/blackboard")' in UI)
check("C4 the three prose cards are gone", "What this tab is (and is not)" not in UI
      and "Two ways" not in UI and "One source of truth: <code>GET / POST /api/blackboard</code>" not in UI)
check("C5 what the tab is survives as a tooltip",
      'title="Not the subagent engine — the model, the parallel limit' in UI)
check("C6 the spend warning is still on screen", "costs N+1 model calls" in UI)
check("C7 the Subagents cross-link survives (JAG-536)", 'data-call="gotoSubagents"' in UI)

# ---- D. the floating editor over Control -------------------------------------
check("D1 the settle helper exists", "function _dockControlSettle()" in UI)
check("D2 Control detaches the floating window from inert #app",
      'document.body.appendChild(dk)' in UI and 'app.setAttribute("inert", "")' in UI)
check("D3 leaving Control puts it back where it was",
      "dk._home.insertBefore(dk, dk._homeNext || null)" in UI
      and "showSessions() {" in UI)
check("D4 both transitions call it", UI.count("_dockControlSettle();") >= 2)
check("D5 a dock/float switch re-places it too",
      "window._dockControlSettle();" in EDITOR)

print("\nv642: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
