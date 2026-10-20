#!/usr/bin/env python3
"""v512 — delete an older plan for real, compact Workspace rail, clickable policy (JAG-514).

Three operator asks, each pinned at the level where it can actually regress:

  A  an "older plan" can be DELETED — not hidden. The nodes ARE the plan (the tasks
     panel, the model prompt and the Control constellation all read the same graph),
     so dropping them clears every surface at once, dangling deps are pruned, the
     CURRENT plan is refused, and the write is persisted + published;
  B  the UI offers the ✕ per older plan (OUTSIDE the <details>, so it is clickable
     while the group is collapsed) and posts to the session-scoped endpoint;
  C  the right rail lost the duplicate card: save sits next to the path, the editor
     hand-off sits next to browse, and the old Files card is gone from markup AND code;
  D  the auto-compact policy names the file in force AND links it into the editor.

Deterministic: temp graph dir, no server, no model, no network.
Run: python3 tests/acceptance/v512_plan_delete_workspace.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v512-")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "data")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "appdata"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph as TG   # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
HTTPAPI = _read("src", "longrun", "core", "httpapi.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------------------- A: deleting a plan is REAL ------
G = TG.ensure("v512s", session_id="v512s", goal="demo")
OLD = TG.add_node(G, "old plan step")
OLD2 = TG.add_node(G, "old plan step 2")
TG.begin_plan(G)                                   # -> plan 1 (current)
NEW = TG.add_node(G, "current step", deps=[OLD["id"]])   # a dep that will dangle

res = TG.drop_plan("v512s", 0)
g2 = TG.load("v512s")
ids = [n["id"] for n in g2["nodes"]]
check("A1 drop_plan removes every node of that plan from the graph",
      res.get("ok") is True and res.get("removed") == 2 and ids == [NEW["id"]],
      res)
check("A2 the removal is PERSISTED (a reload does not bring the plan back)",
      OLD["id"] not in ids and OLD2["id"] not in ids)
check("A3 a dep pointing at a dropped step is pruned (nothing waits forever)",
      g2["nodes"][0]["deps"] == [], g2["nodes"][0]["deps"])
check("A4 it reports what it did (counts for the toast)",
      res.get("plan") == 0 and res.get("node_count") == 1, res)

cur = TG.drop_plan("v512s", 1)
check("A5 the CURRENT plan is refused (the model may be working on it)",
      cur.get("ok") is False and "CURRENT" in (cur.get("error") or ""), cur.get("error"))
missing = TG.drop_plan("v512s", 9)
check("A6 a plan with no steps is refused, not silently 'ok'",
      missing.get("ok") is False and "no steps" in (missing.get("error") or ""))
nograph = TG.drop_plan("never-existed", 0)
check("A7 an unknown session is an honest error",
      nograph.get("ok") is False and "no task graph" in (nograph.get("error") or ""))

# --------------------------------- B: the UI wires the ✕ to that route ------
check("B1 the panel renders a ✕ per older plan",
      '<button class="plan-drop" data-plan="' in HTML)
check("B2 the ✕ sits OUTSIDE the <details> (a closed group hides its children)",
      '<div class="older-wrap"><details class="older-plans">' in HTML
      and ".older-wrap > .plan-drop" in HTML)
check("B3 clicking it calls the delete, with a confirm (no accidental wipe)",
      "async function dropPlan(p)" in HTML and "confirmDelete(" in HTML
      and '"/graph/plan/drop"' in HTML)
check("B4 the endpoint exists server-side, session-scoped",
      '"/graph/plan/drop"' in HTTPAPI and "taskgraph.drop_plan(" in HTTPAPI)
check("B5 the click does not toggle the <details> around it",
      "e.preventDefault(); e.stopPropagation(); dropPlan(" in HTML)

# ------------------------------------------- C: the rail lost the copy ------
check("C1 the duplicate Files card is gone from the markup",
      'Files · workspace' not in HTML and 'id="filesRoot"' not in HTML
      and 'id="fileMsg"' not in HTML)
check("C2 no dead references to the removed card remain in the code",
      'filesRoot' not in HTML and 'fileMsg' not in HTML)
check("C3 save sits on the same row as the path (vertical space saved)",
      'id="wsSave"' in HTML[HTML.index('id="wsPath"'):HTML.index('id="wsPath"') + 420])
check("C4 the editor hand-off moved next to browse",
      'data-call="SparkEditorToggle"' in HTML[HTML.index('id="wsCard"'):HTML.index('<h2>Pending changes')])
check("C5 the hand-off still goes through ONE function (no inline handler)",
      HTML.count("window.SparkEditor.toggle()") == 1
      and HTML.count('data-call="SparkEditorToggle"') == 2)

# ------------------------------- D: the policy file is clickable ------------
check("D1 the auto-compact policy links the file that is in force",
      'a.className = "filelink"' in HTML and '"(config/" +' in HTML,
      "")
check("D2 the link opens it in the editor",
      'openInEditor(f, { mode: "code" })' in HTML)
check("D3 the link prefers the WebUI overlay when it exists",
      "p.local_exists ? (p.local || p.source) : p.source" in HTML)

print("---")
ok = sum(results)
print("\nv512: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
