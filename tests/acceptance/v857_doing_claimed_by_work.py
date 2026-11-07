#!/usr/bin/env python3
"""v857 — the DOING marker is a fact of the turn, not a model courtesy.

`doing` used to exist only if the MODEL remembered a `todo.update`. Measured on
20 000 non-delta feed rows (2026-11-06 21:48 → 11-07 18:02): 45 turn windows ran
real tools and **11 published ZERO `doing`** — `5033e643711a` worked 509 s with 16
tools, `271dcb827fad` ran 51 tools, and the plan stayed a flat grey list. The
operator: "e scomparso il DOING dai cazzo dei todo … deve essere sync con cio che
sta effettivamente facendo l'LLM e con lo stato di run".

The harness already decides which step it is working: `_cur_node()` is the node
every card is nested under. This test pins the missing half:

  A) real work promotes the current open step `todo -> doing`, with its event;
  B) a claim the MODEL already made wins (never a second `doing`);
  C) claiming twice is a no-op (one `doing`, one event);
  D) a `blocked` step is never promoted (that would erase "waiting on something");
  E) no plan / no open step / an EMPTY current plan claims nothing;
  F) the v811 turn bracket still demotes it when the turn ends (run-state sync);
  G) the loop actually calls it: single tool, batch, subagent, dispatch.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v857-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.core import events               # noqa: E402
from longrun.plan import taskgraph            # noqa: E402
from longrun.agent import agent as A          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# never touch the store / the feed: record instead
SEEN = []
events.publish = lambda kind, **d: SEEN.append(kind)
taskgraph._publish = lambda kind, **d: None


def _nodes(sid):
    return {n["id"]: n for n in (taskgraph.load(sid) or {}).get("nodes", [])}


def _claim(sid):
    got = []
    nid = A._claim_step({"id": sid}, on_event=lambda kind, **kw: got.append((kind, kw)))
    return nid, got


# ------------------------------- A. real work promotes the current open step --
g = taskgraph.ensure("ds-a", session_id="ds-a")
a = taskgraph.add_node(g, "step one")
b = taskgraph.add_node(g, "step two")
nid, got = _claim("ds-a")
n = _nodes("ds-a")
check("A1 the first open step becomes 'doing'",
      nid == a["id"] and n[a["id"]]["status"] == "doing",
      (nid, n[a["id"]]["status"]))
check("A2 the claim names itself as the source",
      n[a["id"]].get("source") == "harness:work-start", n[a["id"]].get("source"))
check("A3 it is not a close (no evidence invented)",
      not (n[a["id"]].get("evidence") or []), n[a["id"]].get("evidence"))
check("A4 one event, kind graph.node.updated, status change only",
      len(got) == 1 and got[0][0] == "graph.node.updated"
      and got[0][1].get("changes") == ["status"]
      and (got[0][1].get("node") or {}).get("id") == a["id"],
      got)
check("A5 the sibling stays todo", n[b["id"]]["status"] == "todo", n[b["id"]]["status"])
check("A6 the plan did not move", n[a["id"]]["plan"] == g["plan"], n[a["id"]]["plan"])

# ------------------------------- B. a claim the MODEL made wins --------------
g1 = taskgraph.ensure("ds-b", session_id="ds-b")
c = taskgraph.add_node(g1, "the one the model chose")
d = taskgraph.add_node(g1, "another open step")
taskgraph.update_node(g1, c["id"], status="doing", source="model:update_todos")
nid, got = _claim("ds-b")
n = _nodes("ds-b")
check("B1 the model's own claim is kept",
      nid == c["id"] and n[c["id"]]["status"] == "doing", nid)
check("B2 no silent second 'doing' is created", n[d["id"]]["status"] == "todo",
      n[d["id"]]["status"])
check("B3 nothing is republished when nothing changed", got == [], got)

# ------------------------------- C. claiming twice is a no-op ----------------
before = len(SEEN)
nid2, got2 = _claim("ds-a")
n = _nodes("ds-a")
check("C1 the same step is returned", nid2 == a["id"], nid2)
check("C2 still exactly one 'doing'",
      [k for k, v in n.items() if v["status"] == "doing"] == [a["id"]],
      {k: v["status"] for k, v in n.items()})
check("C3 an already-claiming turn publishes no event", got2 == [], got2)

# ------------------------------- D. a blocked step is never promoted --------
g2 = taskgraph.ensure("ds-d", session_id="ds-d")
e1 = taskgraph.add_node(g2, "waiting on the operator")
taskgraph.update_node(g2, e1["id"], status="blocked", reason="needs credentials")
nid, got = _claim("ds-d")
check("D1 a blocked-only plan claims nothing",
      nid is None and _nodes("ds-d")[e1["id"]]["status"] == "blocked",
      (nid, _nodes("ds-d")[e1["id"]]["status"]))
check("D2 and publishes nothing", got == [], got)

# ------------------------------- E. nothing to claim is a clean no-op --------
nid, got = _claim("ds-no-graph")
check("E1 a session with no plan claims nothing", nid is None and got == [], (nid, got))

g3 = taskgraph.ensure("ds-e", session_id="ds-e")
old = taskgraph.add_node(g3, "an abandoned step of the previous plan")
taskgraph.begin_plan(g3)
nid, got = _claim("ds-e")
check("E2 an EMPTY current plan is not filled from an older plan",
      nid is None and _nodes("ds-e")[old["id"]]["status"] == "todo", nid)

# ------------------------------- F. the v811 bracket still releases it ------
tok = events.turn_begin("ds-a")
check("F1 the turn is running", "ds-a" in events._ACTIVE_CHAT)
events.turn_end("ds-a", tok)
n = _nodes("ds-a")
check("F2 the ended turn demotes the claimed step back to todo",
      n[a["id"]]["status"] == "todo", n[a["id"]]["status"])
check("F3 it is the turn-end correction, not a close",
      n[a["id"]].get("source") == "harness:turn-end" and not n[a["id"]].get("evidence"),
      (n[a["id"]].get("source"), n[a["id"]].get("evidence")))

# ------------------------------- G. the loop really calls it ----------------
src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
check("G1 the single tool path claims before running a non-todo tool",
      "if not str(_raw_tool or \"\").startswith(\"todo.\"):" in src
      and "_claim_step(sess, on_event)" in src, src.count("_claim_step(sess, on_event)"))
check("G2 the batch path claims once for its tool items",
      "_claim_step(sess, on_event)" in src.split("def _apply_chat_batch")[1][:6000])
check("G3 subagent and dispatch turns claim their step",
      src.count("_claim_step(sess, on_event)") >= 4,
      src.count("_claim_step(sess, on_event)"))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
