#!/usr/bin/env python3
"""v809 — a todo can be ABANDONED with a why from the panel (not just cancelled).

`update_node` has required a `reason` for `superseded` since JAG-266/JAG-269, but
`graph_post` never forwarded the field: the operator-facing endpoint answered 400
for the ONE state that records WHY a step is no longer needed. The UI had no
control for it either, so the only reachable close was `cancel` — the state that
stores no reason. This test locks the whole path:

  A) the API forwards `reason`; superseded succeeds WITH a why and is refused
     without one (and without a "still open" fake why);
  B) `cancel` stays the silent close (no reason required);
  C) the panel offers `⊘ superseded`, asks for the why, and sends it;
  D) the six states are explained where they are shown, and the old-plan lines
     carry how much work is still open there.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v809-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph             # noqa: E402
from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _graph(sid):
    g = taskgraph.ensure(sid, session_id=sid)
    return taskgraph.add_node(g, "a step the operator no longer wants", status="todo")


# ------------------------------------------- A. superseded needs a WHY --------
n = _graph("sum-with-why")
res, err, code = agent.graph_post("sum-with-why", {
    "action": "update", "id": n["id"], "status": "superseded",
    "reason": "the operator withdrew the deliverable"})
check("A1 superseded is accepted with a reason", code == 200 and not err, err)
check("A2 the node stores the closed status",
      (res or {}).get("status") == "superseded", res)
check("A3 the WHY is stored on the node",
      (res or {}).get("reason") == "the operator withdrew the deliverable", res)

n2 = _graph("sum-no-why")
res2, err2, code2 = agent.graph_post("sum-no-why", {
    "action": "update", "id": n2["id"], "status": "superseded"})
check("A4 superseded without a reason is refused", code2 == 400 and err2, (code2, err2))
check("A5 the refusal names the missing reason",
      "reason" in str((err2 or {}).get("error", "")), err2)
check("A6 the node stayed untouched",
      taskgraph.find(taskgraph.load("sum-no-why"), node_id=n2["id"])["status"] == "todo")

n3 = _graph("sum-vague")
res3, err3, code3 = agent.graph_post("sum-vague", {
    "action": "update", "id": n3["id"], "status": "superseded",
    "reason": "the work is still open and remains to be finished"})
check("A7 a 'still pending' reason is refused (it is not an abandonment)",
      code3 == 400 and "no longer" in str((err3 or {}).get("error", "")), err3)

# ------------------------------------- B. cancel is still the silent close ----
n4 = _graph("plain-cancel")
res4, err4, code4 = agent.graph_post("plain-cancel", {
    "action": "cancel", "id": n4["id"]})
check("B1 cancel needs no reason", code4 == 200 and not err4, err4)
check("B2 cancel closes the node", (res4 or {}).get("status") == "cancelled", res4)

# ------------------------------------------------ C. blocked keeps its why ----
n5 = _graph("blocked-why")
res5, err5, code5 = agent.graph_post("blocked-why", {
    "action": "update", "id": n5["id"], "status": "blocked",
    "reason": "waiting on the model download"})
check("C1 blocked carries what it waits on",
      code5 == 200 and (res5 or {}).get("reason") == "waiting on the model download",
      (code5, res5))

# ----------------------------------------------- D. the panel offers it -------
UI = os.path.join(REPO, "webui", "index.html")
ui = open(UI, encoding="utf-8").read()
check("D1 the detail panel offers superseded", 'data-a="superseded"' in ui)
check("D2 the button asks WHY before sending",
      'why is' in ui and "no longer needed? (required)" in ui)
check("D3 the action sends the reason field", 'body.reason = why.trim()' in ui)
check("D4 an empty why is refused in the panel, not silently cancelled",
      "a superseded step needs a why" in ui)
check("D5 the six states are explained where they are shown",
      'todo: "open, not started"' in ui and 'superseded: "abandoned, reason recorded"' in ui)
check("D6 an old-plan line says how much work is still open there",
      "_openOld" in ui and "' open' : 'all closed'" in ui)
check("D7 the detail panel states the close rules",
      "superseded needs a why" in ui and "cancel closes silently" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
