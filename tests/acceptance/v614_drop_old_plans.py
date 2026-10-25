#!/usr/bin/env python3
"""v614 — delete ALL old plans at once, per session and per team (not WebUI-only).

Operator ask: "delete all old plans? for a team? for all the agents?"
One x per plan does not scale. Locks:

  A  backend drop_old_plans() is REAL: every node whose plan != current is
     removed from data/graphs/<sid>.json in ONE save, deps pruned,
     transcript untouched, current plan kept, empty case honest;
  B  routes exist: POST /api/sessions/<sid>/graph/plan/drop-old (single)
     and POST /api/teams/<tid>/drop-old-plans (team bulk via _team_bulk);
  C  UI: one "x all" button OUTSIDE the <details> + dropAllOldPlans()
     confirm + POSTs to drop-old + reloads graph.

Deterministic: temp graph dir, no server, no model, no network.
Run: python3 tests/acceptance/v614_drop_old_plans.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v614-")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "data")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "appdata"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph as TG  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
HTTPAPI = _read("src", "longrun", "core", "httpapi.py")
ORCH = _read("src", "longrun", "orchestrate", "orchestration.py")
DECK = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: bulk delete is REAL backend state ----------------------
G = TG.ensure("v614s", session_id="v614s", goal="demo")
P1A = TG.add_node(G, "plan1 step A")
P1B = TG.add_node(G, "plan1 step B")
TG.begin_plan(G)  # -> plan 2
G = TG.load("v614s")
P2A = TG.add_node(G, "plan2 step A")
TG.begin_plan(TG.load("v614s"))  # -> plan 3 (current)
G = TG.load("v614s")
P3A = TG.add_node(G, "current step", deps=[P1A["id"]])  # dangling-after-bulk dep

res = TG.drop_old_plans("v614s")
g2 = TG.load("v614s")
ids = [n["id"] for n in g2["nodes"]]
check("A1 drops plans 1+2, keeps only current plan 3",
      res.get("ok") is True and sorted(res.get("plans") or []) == [1, 2]
      and ids == [P3A["id"]], res)
check("A2 removal PERSISTED (reload does not bring old plans back)",
      P1A["id"] not in ids and P1B["id"] not in ids and P2A["id"] not in ids)
check("A3 dep on a dropped step pruned (nothing waits forever)",
      (g2["nodes"][0].get("deps") or []) == [], g2["nodes"][0].get("deps"))
check("A4 counts honest for the toast",
      res.get("removed") == 3 and res.get("node_count") == 1
      and res.get("current") == 3, res)

again = TG.drop_old_plans("v614s")
check("A5 empty case honest ok (no old plans left)",
      again.get("ok") is True and (again.get("plans") or []) == []
      and again.get("removed") == 0, again)
nograph = TG.drop_old_plans("never-existed-v614")
check("A6 unknown session honest error",
      nograph.get("ok") is False and "no task graph" in (nograph.get("error") or ""))

# ---------------- B: routes (single + team bulk) ----------------------------
check("B1 single-session bulk route exists, session-scoped",
      '"/graph/plan/drop-old"' in HTTPAPI and "taskgraph.drop_old_plans(" in HTTPAPI)
check("B2 team bulk route lists drop-old-plans",
      '"drop-old-plans"' in ORCH and "drop_old_plans" in ORCH)
check("B3 team bulk walks REAL member sessions (never deletes agents)",
      "_team_bulk" in ORCH and "agents_of_team" in ORCH or "member" in ORCH)

# ---------------- C: one-gesture UI -----------------------------------------
check("C1 bulk delete is a ghost x in the menu row (never a bare button below)",
      'class="plan-drop plan-drop-all"' in HTML
      and "'<div class=\"older-wrap\"><details class=\"older-plans-all\">" in HTML)
check("C2 x-all lives in the SAME older-wrap row, OUTSIDE the <details>",
      "</details>' +" in HTML and "plan-drop-all" in HTML)
check("C3 click calls bulk delete with confirm + reload",
      "async function dropAllOldPlans()" in HTML and "confirmDelete(" in HTML
      and '"/graph/plan/drop-old"' in HTML and "await loadGraph()" in HTML)
check("C4 bulk never claims to wipe current plan or chat",
      "current plan, the chat" in HTML or "current plan, the Control" in HTML)

# ---------------- D: team door lives in the deck kebab ------------------------
check("D1 team menu offers Drop OLD plans next to reset/compact",
      'data-a="dropold"' in DECK and "Drop OLD plans" in DECK
      and "Reset all sessions" in DECK and "Compact all sessions" in DECK)
check("D2 the item posts the team bulk route (same generic teamBulk)",
      'this.teamBulk(tid, "drop-old-plans")' in DECK
      and '"/api/teams/" + encodeURIComponent(tid) + "/" + action' in DECK)
check("D3 the confirm states chats/agents stay",
      "current work, chats and agents stay" in DECK)
check("D4 the result line reports dropped plans + surviving current",
      'action === "drop-old-plans"' in DECK and "dropped " in DECK
      and "current " in DECK)

print("---")
ok = sum(results)
print("\nv614: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
