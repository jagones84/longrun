#!/usr/bin/env python3
"""v672 — I-1: a delegated role can only call the tools its role was granted.

Longrun delegates through SEVERAL paths — the in-session `subagent` tool, the
in-session Session Job (`session_jobs` → `subagent.spawn`), a team job assigned
to another agent's session (`jobs.dispatch` → `chat_stream_gen` → `chat_once`),
and agent-to-agent messaging. They must not each invent their own rule:

  * ONE resolver  `subagent.role_tools(role)`  (config/subagents.yaml)
  * ONE predicate `registry.in_scope(tool, allow)` (exact name or namespace)
  * ONE rule       `registry.classify(..., allow=...)` — denied BEFORE every
                   other gate, including `approvals.mode=full`
  * TWO readers    `tool_action` (v2 loop: subagents, session jobs) reads
                   `RunState.tool_allow`; `gated_call` (chat + jobs + REST) reads
                   `api_v02._session_scope(session)` — the assignee agent's role
  * ONE writer     `subagent.merge_roles` for both settings writers and the
                   Subagents panel, so an edit never deletes a scope it does not
                   render.

A role WITHOUT a `tools` key stays unrestricted (the pre-I-1 behaviour).
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v672-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: F401,E402 — breaks the import cycle
from longrun.agent import agents as AGENTS      # noqa: E402
from longrun.agent import session_jobs as SJ    # noqa: E402
from longrun.agent import subagent as SUB       # noqa: E402
from longrun.core import api_v02 as API         # noqa: E402
from longrun.tools import registry              # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------------------------------------------------------- A. parsing --
def _roles_probe(roles):
    """{name: (brief, tools)} against a temporary roles map (module cache)."""
    old = getattr(SUB.load_cfg, "_cache", None)
    SUB.load_cfg._cache = {"roles": roles}
    try:
        return {n: (SUB.role_brief(n), SUB.role_tools(n)) for n in roles}
    finally:
        SUB.load_cfg._cache = old


check("A1 an unknown role is unrestricted", SUB.role_tools("no-such-role") is None)
check("A2 a role without a `tools` key is unrestricted (coder)",
      SUB.role_tools("coder") is None, SUB.role_tools("coder"))
_rs = SUB.role_tools("researcher")
check("A3 the shipped researcher role is scoped, read-only",
      isinstance(_rs, list) and "fs.read" in _rs and "fs.write" not in _rs
      and "shell" not in _rs, _rs)
_p = _roles_probe({"strrole": {"brief": "b", "tools": "fs.read"},
                   "emptyrole": {"brief": "b", "tools": []},
                   "legacyrole": "do the legacy thing"})
check("A4 a bare-string `tools` value is accepted", _p["strrole"][1] == ["fs.read"])
check("A5 an EMPTY `tools` list means unrestricted, not 'nothing allowed'",
      _p["emptyrole"][1] is None)
check("A6 a legacy bare-string role keeps its brief and stays unrestricted",
      _p["legacyrole"] == ("do the legacy thing", None), _p["legacyrole"])

# ------------------------------------------------------------- B. the rule --
check("B1 a namespace entry admits its whole namespace",
      registry.in_scope("fs.write", ["fs"]) and registry.in_scope("fs.read", ["fs"]))
check("B2 an exact entry admits only itself",
      registry.in_scope("fs.read", ["fs.read"])
      and not registry.in_scope("fs.write", ["fs.read"]))
check("B3 `*` admits everything", registry.in_scope("shell", ["*"]))
check("B4 None means unrestricted", registry.in_scope("shell", None))
_d, _why = registry.classify("fs.write", {"path": "x"}, None, None, allow=_rs,
                             scope_name="researcher")
check("B5 a scoped call outside the list is denied with a role_scope reason",
      _d == "denied" and "role_scope:researcher" in _why, (_d, _why))
_d2, _why2 = registry.classify("fs.read", {"path": "README.md"}, None, None,
                               allow=_rs, scope_name="researcher")
check("B6 an allowed tool keeps its normal decision", _d2 in ("auto", "required"), _d2)


def _mode_full(fn):
    orig = registry.load_config
    registry.load_config = lambda: {"approvals": {"mode": "full"}, "tools": {}}
    try:
        return fn()
    finally:
        registry.load_config = orig


_mf = _mode_full(lambda: registry.classify("fs.write", {"path": "x"}, None, None,
                                           allow=_rs, scope_name="researcher"))
check("B7 approvals.mode=full does NOT bypass a role scope", _mf[0] == "denied", _mf)

# --------------------------------------------------------- C. the v2 reader --
st = API.new_run("scope probe", "m", 2)
st.role = "researcher"
st.tool_allow = _rs
_events = []
_obs, _meta = API.tool_action(st, "fs.write", {"path": "v672-should-not-exist.txt",
                                               "content": "nope"},
                              lambda kind, **d: _events.append((kind, d)))
check("C1 the loop refuses a tool outside the run's role scope",
      "role_scope:researcher" in str(_obs), str(_obs)[:160])
check("C2 the refusal is published as tool.blocked",
      any(k == "tool.blocked" and "role_scope" in str(d.get("reason"))
          for k, d in _events), _events[-2:])
check("C3 an unrestricted run is unchanged (no scope, no refusal)",
      API.tool_action(API.new_run("g", "m", 1), "fs.read", {"path": "README.md"},
                      lambda *a, **k: None)[0] != "")

# -------------------------------------------- D. the chat/dispatch reader --
_reg = AGENTS.REGISTRY.designate("sess_v672_researcher", name="V672 Researcher",
                                 role="researcher")
check("D0 the agent registry really carries the role",
      _reg.get("ok") and (AGENTS.REGISTRY.get("sess_v672_researcher") or {}).get("role")
      == "researcher", _reg)
_allow, _role = API._session_scope("sess_v672_researcher")
check("D1 the session scope resolves to the assignee agent's role",
      _allow == _rs and _role == "researcher", (_allow, _role))
check("D2 an ordinary session has no scope", API._session_scope("sess_unregistered")
      == (None, None))
_res = API.gated_call("fs.write", {"path": "v672-gated.txt", "content": "x"},
                      run_id="sess_v672_researcher")
check("D3 a delegated chat turn (job/dispatch) is blocked by the same rule",
      _res.get("status") == "blocked" and "role_scope:researcher" in str(_res.get("reason")),
      _res.get("status"), )
_ok = API.gated_call("fs.read", {"path": "README.md"}, run_id="sess_v672_researcher")
check("D4 the same turn may still read", _ok.get("status") == "executed", _ok.get("status"))

# ---------------------------------------------------------- E. the spawner --
_orig_run = SUB.api_v02.agent_run_v2


def _stub_run(goal, max_steps=1, model=None, on_event=None, run_id=None, **_k):
    return {"status": "done", "trace": [], "summary": "stub"}


SUB.api_v02.agent_run_v2 = _stub_run
try:
    _sp = SUB.spawn("v672 researcher probe", role="researcher")
    _state = (SUB._running.get(_sp.get("subagent_id")) or {}).get("state")
    _state and (SUB._running[_sp["subagent_id"]]["done"].wait(2))
    check("E1 spawn stamps the role's scope onto the child run",
          _state is not None and _state.tool_allow == _rs and _state.role == "researcher",
          _state and (_state.role, _state.tool_allow))
    _sp2 = SUB.spawn("v672 coder probe", role="coder")
    _state2 = (SUB._running.get(_sp2.get("subagent_id")) or {}).get("state")
    _state2 and (SUB._running[_sp2["subagent_id"]]["done"].wait(2))
    check("E2 a role without `tools` stays unrestricted",
          _state2 is not None and _state2.tool_allow is None, _state2 and _state2.tool_allow)
finally:
    SUB.api_v02.agent_run_v2 = _orig_run

# ------------------------------------------- F. in-session subjobs use the same funnel --
_c = SJ.create("sess_v672_sj", "v672 subjobs", [
    {"label": "a", "goal": "look it up", "role": "researcher"},
    {"label": "b", "goal": "write it", "role": "coder"}])
_seen = []


def _spawn_fn(goal, parent_run_id=None, role=None, **_k):
    _seen.append(role)
    return {"subagent_id": "sub_%d" % len(_seen)}


SJ.run("sess_v672_sj", spawn_fn=_spawn_fn,
       collect_fn=lambda sid, timeout=None: {"status": "done", "summary": "ok"})
check("F1 a Session Job hands its subjob role to the SAME spawner",
      set(_seen) == {"researcher", "coder"}, _seen)

# ------------------------------------------------------------ G. the writers --
_cur = {"researcher": {"brief": "old", "tools": ["fs.read"]}}
_merged = SUB.merge_roles(_cur, {"researcher": "new brief"})
check("G1 editing a role's brief keeps its tool scope",
      _merged["researcher"].get("tools") == ["fs.read"]
      and _merged["researcher"].get("brief") == "new brief", _merged)
_merged2 = SUB.merge_roles(_cur, {"coder": "write code"})
check("G2 a new role lands as a plain brief",
      _merged2.get("coder") == "write code", _merged2)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    _ui = f.read()
check("G3 the panel renders the brief, not the object",
      "function subRoleBrief(" in _ui and "ta.value = subRoleBrief(" in _ui)
check("G4 the panel states the real scope and preserves it on edit",
      "tools restricted to: " in _ui and "Object.assign({}, cur, { brief: ta.value })" in _ui)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
