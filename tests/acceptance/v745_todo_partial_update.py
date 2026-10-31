#!/usr/bin/env python3
"""v745 — todo.update accepts a PARTIAL step (proof/sources) and status aliases.

Measured 2026-10-31 in all three kept benchmark sessions: the model attached the
sources it had collected with a step that carried no `status`, and the harness
refused the whole call with `bad status ''` — the provenance was thrown away.
A step is not required to move to be updated, and the six accepted words are not
the words models write.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v745-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph             # noqa: E402
from longrun.tools import registry             # noqa: E402
from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _sess(sid):
    return {"id": sid, "messages": [], "workspace": ""}


def _node(sid):
    g = taskgraph.ensure(sid, session_id=sid)
    return taskgraph.add_node(g, "a step", status="doing")


def _apply(sid, steps):
    return agent._apply_chat_todo_updates(_sess(sid), {"steps": steps},
                                          lambda *a, **k: None)


# ---- A. the normaliser ------------------------------------------------------
check("A1 'in_progress' means doing", taskgraph.normalize_status("in_progress") == "doing")
check("A2 'Completed' means done", taskgraph.normalize_status("Completed") == "done")
check("A3 'in-progress' (dash) is normalised", taskgraph.normalize_status("in-progress") == "doing")
check("A4 'pending' means todo", taskgraph.normalize_status("pending") == "todo")
check("A5 junk is not a status", taskgraph.normalize_status("wat") == "")
check("A6 absent is not a status", taskgraph.normalize_status(None) == "")

# ---- B. a sources-only step is a real update --------------------------------
n = _node("upd-sources")
changed, errors = _apply("upd-sources", [{"id": n["id"],
                                          "sources": ["task_folder/x.csv"]}])
stored = taskgraph.find(taskgraph.load("upd-sources"), node_id=n["id"])
check("B1 a sources-only step is accepted", changed == 1 and not errors, errors)
check("B2 its sources are stored",
      bool(stored.get("evidence")) and stored["evidence"][-1].get("sources"),
      stored.get("evidence"))
check("B3 the step did NOT move", stored.get("status") == "doing", stored.get("status"))

# ---- C. an evidence-only step is a real update ------------------------------
n = _node("upd-evidence")
changed, errors = _apply("upd-evidence", [{"id": n["id"], "evidence": "read the ledger"}])
stored = taskgraph.find(taskgraph.load("upd-evidence"), node_id=n["id"])
check("C1 an evidence-only step is accepted", changed == 1 and not errors, errors)
check("C2 the evidence is stored",
      any("read the ledger" in str(e.get("text")) for e in stored.get("evidence") or []),
      stored.get("evidence"))
check("C3 the step is still doing", stored.get("status") == "doing", stored.get("status"))

# ---- D. aliases move the step ----------------------------------------------
n = _node("upd-alias")
changed, errors = _apply("upd-alias", [{"id": n["id"], "status": "in_progress"}])
check("D1 'in_progress' advances the step", changed == 1 and not errors, errors)

# ---- E. an empty step is still an error, and says what to send -------------
n = _node("upd-empty")
changed, errors = _apply("upd-empty", [{"id": n["id"]}])
check("E1 an empty step is refused", changed == 0 and errors, errors)
check("E2 the refusal names what to send",
      bool(errors) and "status" in errors[0] and "evidence" in errors[0], errors)

n = _node("upd-bad")
changed, errors = _apply("upd-bad", [{"id": n["id"], "status": "wat"}])
check("E3 a junk status is refused with the accepted list",
      changed == 0 and bool(errors) and "doing" in errors[0], errors)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
