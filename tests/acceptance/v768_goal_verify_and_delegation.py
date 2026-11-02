#!/usr/bin/env python3
"""v768 — a GOAL is verified INDEPENDENTLY; the bar never lies; work is delegated.

Operator report (2026-11-02), five incoherences turned into contracts:

  1. a running tool card shows its INPUT at once and its OUTPUT as it arrives;
  2. an orchestrator must DELEGATE to its whole team (every level), not do it all;
  3. best-of-N and the verifier are ON by default (checked in the Harness panel);
  4. every agent is TOLD to point its workspace at the task, and `workspace.set`
     is approval-gated by default;
  5. the GOAL bar can be read in full, pause/resume always works, and completion
     needs an INDEPENDENT check — not just "the todo list is closed".

This test pins the backend contracts (deterministic, no live model, no network).
Run: python3 tests/acceptance/v768_goal_verify_and_delegation.py
"""
import atexit
import inspect
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v768-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT", "GOALS_DIR"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as A              # noqa: E402
from longrun.memory import stores                  # noqa: E402
from longrun.model import prompt as P              # noqa: E402
from longrun.plan import goal as G                 # noqa: E402
from longrun.plan import taskgraph as TG           # noqa: E402
from longrun.tools import registry, sandbox, term, tools as T  # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- helpers ----------------------------------------------------------------
def mk_session(title):
    s = stores.get_or_create_session(None, title)
    return s["id"]


def write_graph(sid, nodes, goal_text="do the thing"):
    g = {"key": sid, "run_id": sid, "session_id": sid, "plan": 1,
         "goal": goal_text, "plan_base": 1, "nodes": nodes}
    TG.save(g)
    return g


def node(nid, status, sources=None, text="did it"):
    ev = {"ts": 1.0, "text": text}
    if sources is not None:
        ev["sources"] = [{"path": p} for p in sources]
    return {"id": nid, "label": nid, "status": status, "plan": 1, "evidence": [ev]}


# ============================================================================
# A — independent goal verification
# ============================================================================
sid = mk_session("verify-goal")
ws = os.path.join(TMP, "wsA")
os.makedirs(ws, exist_ok=True)
sess = stores.load_session(sid)
sess["workspace"] = ws
stores.save_session(sess)
open(os.path.join(ws, "out.txt"), "w", encoding="utf-8").write("done")

# A1: an OPEN plan is not a finished goal.
write_graph(sid, [node("n1", "done", ["out.txt"]), node("n2", "todo")])
v = G.verify(sid)
check("A1 an open plan fails verification", v["verified"] is False
      and any("not complete" in m for m in v["missing"]), v["missing"][:2])

# A2: a closed plan whose cited ARTEFACT exists verifies.
write_graph(sid, [node("n1", "done", ["out.txt"]), node("n2", "done", ["out.txt"])])
v = G.verify(sid)
check("A2 a closed plan with real artefacts verifies", v["verified"] is True, v["missing"])

# A3: a DONE step that cites a file that does not exist fails (the claim is checked).
write_graph(sid, [node("n1", "done", ["out.txt"]), node("n2", "done", ["ghost.md"])])
v = G.verify(sid)
check("A3 a cited-but-missing artefact fails verification",
      v["verified"] is False and any("ghost.md" in m for m in v["missing"]), v["missing"][:3])

# A4: the configured acceptance command is an independent authority (L1).
write_graph(sid, [node("n1", "done", ["out.txt"])])
_real_cfg = G.__dict__.get("verify_config")
G.verify_config = lambda: {"acceptance": True, "judge": False, "judge_model": ""}
_real_verify_cfg = __import__("longrun.plan.verify", fromlist=["cfg"]).cfg
__import__("longrun.plan.verify", fromlist=["cfg"]).cfg = lambda override=None: {
    "enabled": True, "command": "pytest -q", "timeout_secs": 5, "paths": []}
_real_run = sandbox.run
sandbox.run = lambda *a, **k: {"exit_code": 1, "stdout": "1 failed"}
v = G.verify(sid)
check("A4a a FAILING acceptance command blocks completion",
      v["verified"] is False and any("acceptance" in m for m in v["missing"]), v["missing"][:3])
sandbox.run = lambda *a, **k: {"exit_code": 0, "stdout": "ok"}
v = G.verify(sid)
check("A4b a PASSING acceptance command allows completion", v["verified"] is True, v["missing"])
sandbox.run = _real_run
__import__("longrun.plan.verify", fromlist=["cfg"]).cfg = _real_verify_cfg
G.verify_config = _real_cfg

# ============================================================================
# B — truthfulness: a completed goal whose plan REOPENED is not "done"
# ============================================================================
# B1: a goal stored "completed" whose plan has an OPEN step reports "reopened".
write_graph(sid, [node("n1", "done", ["out.txt"]), node("n2", "todo")])
G.start(sid, "ship it")
G.complete(sid, "plan complete with evidence")   # force a stale completion
st = G.status(sid)
check("B1 a completed goal with a reopened plan reports 'reopened'",
      st["effective_status"] == "reopened", st["effective_status"])
check("B3 a stored 'verified' is invalidated once the plan reopened",
      (st.get("verification") is None) or (st["verification"].get("verified") is False))
# settle writes the truth back; resume works on a reopened goal
G.settle(sid)
check("B4 settle flips the stale 'completed' back to 'active'",
      (G.load(sid) or {}).get("status") == "active")
G.complete(sid, "again")
rec = G.resume(sid)
check("B5 resume works on a completed-but-reopened goal",
      rec is not None and rec.get("status") == "active", rec)
# start() on a reopened goal keeps the SAME goal (objective kept, turns++)
turns_before = (G.load(sid) or {}).get("turns")
G.complete(sid, "x")
write_graph(sid, [node("n1", "done", ["out.txt"]), node("n2", "todo")])
G.start(sid, "")
check("B6 start() continues a reopened goal (no objective reset, turns++)",
      (G.load(sid) or {}).get("status") == "active"
      and (G.load(sid) or {}).get("turns") == (turns_before or 0) + 1,
      G.load(sid))

# The API exposes the verify action + status carries the verdict.
_ga = inspect.getsource(__import__("longrun.core.api_v02", fromlist=["_goal_action"])._goal_action)
check("B7 POST /api/goal exposes a 'verify' action", '"verify"' in _ga or "'verify'" in _ga)
_h = inspect.getsource(__import__("longrun.core.httpapi", fromlist=["_goal_end"])._goal_end)
check("B8 the goal closes only on an independent verdict (goal.verify)",
      "verify(" in _h and "verified" in _h)

# ============================================================================
# C — delegation: the orchestrator sees EVERY level and is told to delegate
# ============================================================================
def agent(name, reports_to=None):
    sid_ = mk_session(name)
    A.REGISTRY.designate(sid_, name=name, role="role-" + name, reports_to=reports_to)
    return A.REGISTRY.get(sid_)["id"], sid_


top_id, top_sid = agent("Top Orchestrator")
mid_id, _ = agent("Middle Manager", top_id)
leaf_id, _ = agent("Deep Leaf", mid_id)
txt = P.render_sections(sess={"id": top_sid, "title": "Top"}, ws=None, tool_ctx="TOOLS")
check("C1 the team block lists EVERY level below the orchestrator, not only direct reports",
      mid_id in txt and leaf_id in txt, "%s/%s" % (mid_id, leaf_id))
check("C2 it states that delegation is the job",
      "ORCHESTRATOR" in txt and "DELEGATE" in txt)
check("C2b it tells the truth that `dispatch` reaches DIRECT reports only",
      "DIRECT reports ONLY" in txt and "DIRECT report>" in txt)
check("C2c it says a deeper agent is reached by telling its owner to delegate",
      "delegate in turn" in txt and "chain of command" in txt)
check("C2d the org list distinguishes direct (un-indented) from nested",
      "entries WITHOUT an indent are your DIRECT reports" in txt)
check("C3 it points at workspace.set for the whole subtree",
      "workspace.set" in txt and "subtree" in txt)
check("C4 EVERY agent is told to point its workspace at the task",
      "## Your workspace" in txt and "workspace.set" in txt)
leaf_txt = P.render_sections(sess={"id": stores.load_session(
    A.REGISTRY.resolve(leaf_id)["session"])["id"]}, ws=None, tool_ctx="TOOLS")
check("C5 a leaf has no team block but still gets the workspace rule",
      "## Your team" not in leaf_txt and "## Your workspace" in leaf_txt)

# ============================================================================
# D — defaults: workspace.set is approval-gated; best-of-N/verifier are ON
# ============================================================================
cfg = registry.load_config()
ws_tool = (cfg.get("tools") or {}).get("workspace") or {}
check("D1 workspace.set requires approval by default",
      ws_tool.get("enabled") is True and ws_tool.get("approval") == "required", ws_tool)
check("D2 the verifier is enabled by default", bool((cfg.get("verifier") or {}).get("enabled")))
check("D3 best-of-N is enabled by default", bool((cfg.get("bestofn") or {}).get("enabled")))
# The block must be REACHABLE: `_merge_into` walks a fixed section list, so a new
# block the list does not name is silently dropped — tools.yaml would hold it,
# `load_config()` would not, and `section_config(...)` would fall back to defaults
# (a saved Goal-verification setting could never take effect).
check("D4 the goal_verify block in tools.yaml is really merged, not dropped",
      bool(cfg.get("goal_verify")), cfg.get("goal_verify"))
check("D5 goal.verify_config() reflects the YAML block",
      G.verify_config().get("acceptance") is True
      and G.verify_config().get("judge") is False, G.verify_config())

# ============================================================================
# E — live tool output plumbing
# ============================================================================
check("E1 Shell.run_capture accepts an on_output callback",
      "on_output" in inspect.signature(term.Shell.run_capture).parameters)
check("E2 the shell tool passes a streaming callback",
      "on_output=" in inspect.getsource(T._shell))
check("E3 the harness forwards output inside the shell's live sink",
      "tool.output" in inspect.getsource(T._shell))
_attach = __import__("longrun.core.httpapi", fromlist=["_ATTACH_KINDS"])._ATTACH_KINDS
check("E4 tool.output is replayed on a chat re-attach", "tool.output" in _attach)

# ============================================================================
# F — WebUI wiring (static contract on webui/index.html)
# ============================================================================
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("F1 the tool card shows its INPUT as soon as it starts",
      'toolCard(d.tool, d.args, d.ts)' in ui)
check("F2 tool.output streams into the card", "liveToolOutput" in ui
      and 'addEventListener("tool.output"' in ui)
check("F3 the goal objective is expandable",
      'id="goalFull"' in ui and "function goalExpand" in ui)
check("F4 the goal bar offers an independent verify",
      'id="goalVerify"' in ui and "function goalVerify" in ui)
check("F5 the bar renders the EFFECTIVE status (reopened is not done)",
      "effective_status" in ui and '"reopened"' in ui)
check("F6 verifier + best-of-N checkboxes default checked",
      'id="vfOn" type="checkbox" checked' in ui
      and 'id="bnOn" type="checkbox" checked' in ui)
check("F7 the Harness panel exposes Goal verification (acceptance + judge)",
      'id="gvAcc"' in ui and 'id="gvJudge"' in ui
      and "function loadGoalVerify" in ui and "function saveGoalVerify" in ui)

# The config block is owned by a documented dedicated panel (v491 contract).
from longrun.core import settings as S                   # noqa: E402
check("F8 goal_verify is owned by Settings ▸ Harness",
      (S.DEDICATED.get("tools.yaml") or {}).get("goal_verify") == "Settings ▸ Harness")

# ============================================================================
# G — the OWN-turn stream carries the tool output (the gap the first pass missed)
# ============================================================================
# The page renders its OWN turn from `/api/chat/stream`; `/api/chat/attach` only
# serves a refresh. Wiring `tool.output` into the attach kinds alone left the card
# blank until `tool.result`. The active turn now registers its `_emit` as the
# session's render sink, and the shell prints into it line by line.
from longrun.core import events as EV                    # noqa: E402
_tok = EV.turn_begin("v768-sink")
_seen = []
EV.set_turn_sink("v768-sink", lambda kind, **d: _seen.append((kind, d)))
check("G1 the active turn's sink is retrievable", EV.turn_sink("v768-sink") is not None)
_sres = T.execute("shell", {"command": "printf V768SENTINEL"}, run_id="v768-sink")
check("G2 a running shell streams its output into the turn sink",
      any(k == "tool.output" and "V768SENTINEL" in str(d.get("text")) for k, d in _seen),
      _seen[:2])
EV.turn_end("v768-sink", _tok)
check("G3 the sink is dropped when the turn ends", EV.turn_sink("v768-sink") is None)
_http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("G4 the chat stream registers its _emit as the turn sink",
      'set_turn_sink(sess["id"], _emit)' in _http)
check("G5 the shell prefers the turn sink and falls back to publish",
      "turn_sink(_sid)" in inspect.getsource(T._shell)
      and "publish(\"tool.output\"" in inspect.getsource(T._shell))

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
