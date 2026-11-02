#!/usr/bin/env python3
"""v767 — `workspace.set`: an orchestrator re-roots its WHOLE org subtree.

Operator request (2026-11-02): an orchestrator in a team must be able to change
the workspace of its subordinates, at EVERY level below it — an intermediate
orchestrator's own reports included, not only its direct reports.

Contract:
  A  the base tool is registered, enabled, canonical (`workspace.set`, no
     `action` in the call shape) and its handler is dispatched;
  B  scope=subtree re-roots the agent AND every descendant at every level,
     writing BOTH stores (agent record + session, the runtime authority);
  C  scope=self touches one agent only (the subtree keeps its folder);
  D  a teammate may only re-root itself or a subordinate — a peer target is
     refused, and the supervisor may target anyone;
  E  invalid requests are refused (missing folder with create=false, a file as
     folder, unknown scope);
  F  `agent.update {workspace}` writes the session too (one truth, regression
     guard for the record-only write).

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v767_agent_workspace_subtree.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v767-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as A                  # noqa: E402
from longrun.agent import longrun_agent as LRA         # noqa: E402
from longrun.memory import stores                      # noqa: E402
from longrun.tools import registry                     # noqa: E402
from longrun.tools import tools as T                   # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def agent(tool, args):
    return LRA.execute(tool, args, run_id="longrunAgent")


def mk(name, reports_to=None):
    args = {"name": name}
    if reports_to:
        args["reports_to"] = reports_to
    res = agent("agent.create", args)
    assert res.get("ok"), res
    return res


LRA.ensure_system_session()

# --- A: the base tool exists ------------------------------------------------
spec = registry.tool_spec("workspace.set")
check("A1 workspace.set is a registered, enabled base tool",
      bool(spec and spec.get("enabled")), spec and spec.get("approval"))
schema = (spec or {}).get("schema") or {}
check("A2 the canonical call shape has no `action` and requires the path",
      "action" not in (schema.get("properties") or {})
      and schema.get("required") == ["workspace"], sorted(schema.get("properties") or {}))
check("A3 the legacy namespace call canonicalises to the same tool",
      registry.canonical_name("workspace", {"action": "set"}) == "workspace.set")
check("A4 the handler is dispatched (not only advertised)",
      T._DISPATCH.get("workspace.set") is not None)

# --- B: a three-level org, subtree re-root ----------------------------------
orch = mk("Orchestrator")
mid = mk("Middle Orchestrator", orch["agent"]["id"])
leaf1 = mk("Leaf One", mid["agent"]["id"])
leaf2 = mk("Leaf Two", mid["agent"]["id"])
peer = mk("Peer Root")
org_ids = [orch["agent"]["id"], mid["agent"]["id"],
           leaf1["agent"]["id"], leaf2["agent"]["id"]]
check("B0 the org is three levels deep under the root",
      len(A.REGISTRY.subtree(orch["agent"]["id"])) == 4,
      A.REGISTRY.subtree(orch["agent"]["id"]))

ws_sub = os.path.join(TMP, "ws", "team-subtree")
res = T.execute("workspace.set",
                {"agent": orch["agent"]["id"], "workspace": ws_sub,
                 "scope": "subtree"},
                run_id=orch["session"])
check("B1 the orchestrator re-roots its whole subtree", res.get("ok"), res.get("error"))
check("B2 all four agents (every level) were changed",
      res.get("count") == 4 and sorted(a["agent"] for a in res.get("agents") or []) == sorted(org_ids),
      res.get("agents"))

recs = {a["id"]: a for a in A.REGISTRY.list()["agents"]}
check("B3 every AGENT record points at the new folder",
      all(recs[i].get("workspace") == ws_sub for i in org_ids),
      {i: recs[i].get("workspace") for i in org_ids})
check("B4 every SESSION (the runtime authority) points at the new folder",
      all((stores.load_session(recs[i]["session"]) or {}).get("workspace") == ws_sub
          for i in org_ids),
      {i: (stores.load_session(recs[i]["session"]) or {}).get("workspace") for i in org_ids})
check("B5 the unrelated root is untouched",
      recs[peer["agent"]["id"]].get("workspace") == peer["workspace"],
      recs[peer["agent"]["id"]].get("workspace"))

# --- C: scope=self touches one agent only -----------------------------------
ws_self = os.path.join(TMP, "ws", "leaf-self")
res = T.execute("workspace.set", {"workspace": ws_self},
                run_id=leaf1["session"])
check("C1 scope defaults to self and targets the CALLING agent",
      res.get("ok") and res.get("count") == 1
      and (res.get("agents") or [{}])[0].get("agent") == leaf1["agent"]["id"],
      res.get("agents"))
check("C2 the caller's sibling kept the subtree folder",
      A.REGISTRY.resolve(leaf2["agent"]["id"]).get("workspace") == ws_sub)

# --- D: hierarchy authority -------------------------------------------------
hijack_path = os.path.join(TMP, "ws", "hijack")
res = T.execute("workspace.set",
                {"agent": peer["agent"]["id"], "workspace": hijack_path},
                run_id=leaf1["session"])
check("D1 a leaf cannot re-root an unrelated root (and nothing is created)",
      not res.get("ok") and "not above" in str(res.get("error"))
      and not os.path.exists(hijack_path), res.get("error"))

res = T.execute("workspace.set",
                {"agent": mid["agent"]["id"], "workspace": os.path.join(TMP, "ws", "mid-subtree"),
                 "scope": "subtree"},
                run_id=mid["session"])
check("D2 an INTERMEDIATE orchestrator re-roots its own subtree",
      res.get("ok") and res.get("count") == 3, res.get("agents"))

res = T.execute("workspace.set",
                {"agent": leaf2["agent"]["id"], "workspace": os.path.join(TMP, "ws", "peer-by-supervisor")},
                run_id="longrunAgent")
check("D3 the supervisor may re-root any agent", res.get("ok"), res.get("error"))

# --- E: bad requests are refused -------------------------------------------
res = T.execute("workspace.set",
                {"workspace": os.path.join(TMP, "ws", "missing"), "create": False,
                 "agent": orch["agent"]["id"]},
                run_id=orch["session"])
check("E1 create=false on a missing folder is refused",
      not res.get("ok") and "no such folder" in str(res.get("error")), res.get("error"))

afile = os.path.join(TMP, "a-file.txt")
with open(afile, "w", encoding="utf-8") as fh:
    fh.write("x")
res = T.execute("workspace.set", {"workspace": afile}, run_id=orch["session"])
check("E2 a FILE is never accepted as a workspace",
      not res.get("ok") and "not a folder" in str(res.get("error")), res.get("error"))

res = T.execute("workspace.set", {"workspace": ws_sub, "scope": "galaxy"},
                run_id=orch["session"])
check("E3 an unknown scope is refused",
      not res.get("ok") and "scope must be" in str(res.get("error")), res.get("error"))

# --- F: agent.update keeps both stores in lockstep (regression) -------------
ws_update = os.path.join(TMP, "ws", "by-agent-update")
res = agent("agent.update", {"agent": leaf2["agent"]["id"], "workspace": ws_update})
check("F1 agent.update accepts the workspace", res.get("ok"), res.get("error"))
rec_leaf2 = A.REGISTRY.resolve(leaf2["agent"]["id"])
sess_leaf2 = stores.load_session(leaf2["session"]) or {}
check("F2 agent.update writes the RECORD and the SESSION together",
      rec_leaf2.get("workspace") == ws_update and sess_leaf2.get("workspace") == ws_update,
      (rec_leaf2.get("workspace"), sess_leaf2.get("workspace")))

# --- G: the caller's cwd is NEVER injected as an object's target folder -----
import inspect                                     # noqa: E402

from longrun.core import api_v02                   # noqa: E402

sites = (inspect.getsource(api_v02.tool_action)
         + inspect.getsource(api_v02.gated_call))
check("G1 both workspace-injection sites skip object-field tools",
      sites.count("_workspace_is_object_field(tool)") == 2)
OBJECT_TOOLS = ("agent.create", "agent.update", "session.create", "workspace.set")
check("G2 object-field tools are recognised (target folder, not a cwd)",
      all(api_v02._workspace_is_object_field(t) for t in OBJECT_TOOLS),
      [t for t in OBJECT_TOOLS if not api_v02._workspace_is_object_field(t)])
check("G3 a working-directory tool still receives the session workspace",
      not api_v02._workspace_is_object_field("index.search"))

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
