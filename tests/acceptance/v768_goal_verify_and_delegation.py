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
check("F3 the objective is read/edited in a real editor window (no duplicate block)",
      'id="goalEditPanel"' in ui and 'id="goalEditBox"' in ui
      and "<textarea" in ui[ui.find('id="goalEditPanel"'):ui.find('id="goalEditPanel"') + 700]
      and 'id="goalFull"' not in ui and "function goalExpand" not in ui)
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

# F9-F11 (JAG-504/JAG-2, operator report): the bar must not overflow a narrow chat,
# the objective opens a real multi-line editor WINDOW, and the verdict is closable AND
# re-openable.
check("F9 the goal bar wraps instead of overflowing a narrow chat",
      "flex-wrap: wrap" in ui and "max-width: 100%" in ui
      and ".gb-editor" in ui and ".gb-editor[hidden]" in ui)
check("F10 the editor is a scrollable multi-line window (no modal prompt)",
      "min-height: 96px" in ui and "overflow: auto" in ui and "resize: vertical" in ui
      and "function goalEditSave" in ui and "function goalEditCancel" in ui
      and "prompt(" not in ui[ui.find("function goalEdit()"):ui.find("function goalEditCancel")])
check("F11 the verdict is a compact badge whose detail opens on demand",
      'id="goalVerdictBadge"' in ui and "function goalVerdictToggle" in ui
      and "function goalVerdictClose" in ui and "_goalVerdictOpen" in ui
      and ".gb-badge[hidden]" in ui and ".gb-verdict[hidden]" in ui
      and 'id="goalVerdictChip"' not in ui)
check("F11b the verdict block says WHOSE check it is (not the agent's claim)",
      "harness's independent check" in ui and "NOT the agent's claim" in ui)
check("F11c the goal row stays one line: no turn counter, actionable counts only",
      "p.struck" in ui and '" dropped"' in ui and "g.turns || 1" not in ui
      and 'class="ghost gb-act"' in ui)

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

# ============================================================================
# H — the CLOSURE layer (JAG-504): answer the ORIGINAL request, close the todos,
#     and a FURTHER control on the goal before a `/goal` turn may close.
# ============================================================================
from longrun.core import server as _srv                                # noqa: E402,F401
from longrun.agent import agent as _ag                                 # noqa: E402

# H1: the enforced closure verdict is anchored to the operator's ORIGINAL request.
_req = "rename the widget and re-run its tests"
_p = _ag._closure_check_prompt(_req)
check("H1 the closure verdict names the ORIGINAL request",
      _req in _p and "ORIGINAL request" in _p and "finish" in _p, _p[:80])
# H2: with no request it keeps the original wording (v584 pins that string).
check("H2 no-arg closure prompt is unchanged",
      _req not in _ag._closure_check_prompt()
      and "COMPLETE" in _ag._closure_check_prompt()
      and "keep working" in _ag._closure_check_prompt())
# H3: the goal-closure layer is anchored to BOTH the request and the objective.
_gp = _ag._goal_closure_prompt(_req, "ship the widget")
check("H3 the goal-closure layer anchors request AND objective",
      _req in _gp and "ship the widget" in _gp and "OBJECTIVE" in _gp)
# H4: the standing CLOSING CONTRACT is a policy bullet every model sees.
check("H4 the closing contract is a standing task-policy rule",
      "CLOSING CONTRACT" in _ag.TASK_POLICY
      and "ORIGINAL" in _ag.TASK_POLICY and "superseded" in _ag.TASK_POLICY)
# H5/H6: the goal-closure round is real, bounded once per turn, and gated on goal
#         mode + evidence-backed completion — wired at every acceptance point.
_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()
_gr = _src[_src.find("def _goal_close_round():"):]
_gr = _gr[:_gr.find("def _trim_midturn():")]
check("H5 the round is once-per-turn and gated on goal mode + completion",
      "nonlocal _goal_close_used" in _gr and "_goal_close_used = True" in _gr
      and "not goal_mode" in _gr and "goal_complete(" in _gr)
check("H6 it is wired at every acceptance point (>=4 call sites)",
      _src.count("if _goal_close_round():") >= 4, _src.count("if _goal_close_round():"))
check("H7 the goal-closure prompt is the one it injects",
      "_goal_closure_prompt(" in _gr and "_goal_rec_objective(" in _gr)

# H8/H9 (JAG-3): the verdict is a REAL object the AGENT can read — injected into the
# per-turn harness state, not only rendered in the bar. Deterministic: L1 is switched
# off so no sandbox command runs; L2 (artefacts on disk) is what fails here.
_saved_vc = G.verify_config
G.verify_config = lambda: {"acceptance": False, "judge": False, "judge_model": ""}
G.complete(sid, "force a verdict")
G.verify(sid)                       # stores the verdict on the goal record
G.verify_config = _saved_vc
_blk = _ag._goal_block(sid)
check("H8a the goal + its independent verdict reach the agent's context",
      "GOAL (" in _blk and "objective:" in _blk and "INDEPENDENT verification" in _blk,
      _blk[:120])
check("H8b the injected text says the check is the harness's, not the agent's claim",
      "NOT your own claim" in _blk and "NOT VERIFIED" in _blk, _blk[-160:])
check("H8c what the check could NOT confirm is listed, with the instruction to fix it",
      "could NOT confirm" in _blk and "do not close the goal by restating" in _blk)
check("H8d a session with no goal injects nothing", _ag._goal_block("") == "")
check("H9 context_summary injects the goal block with the task list",
      "goal_block = _goal_block(" in _src)

# ============================================================================
# I — the goal IS the loop's contract (JAG-10, operator report): the counts are the
#     actionable ones, a durable ACTIVE goal owns EVERY turn of its session, and the
#     verdict is re-computed at EVERY goal turn end (never a stale badge).
# ============================================================================
from longrun.core import httpapi as H                              # noqa: E402

# I1: cancelled/superseded steps are not work the goal still owes.
_sid2 = mk_session("counts")
write_graph(_sid2, [node("n1", "done", ["out.txt"]),
                    node("n2", "done", ["out.txt"]),
                    {"id": "n3", "label": "n3", "status": "superseded", "plan": 1,
                     "reason": "no longer needed"},
                    {"id": "n4", "label": "n4", "status": "cancelled", "plan": 1},
                    node("n5", "todo")])
_pr = G.progress(_sid2)
check("I1a the denominator counts only ACTIONABLE steps (2 done + 1 open = 3)",
      _pr["steps"] == 3 and _pr["done"] == 2 and _pr["open"] == 1, _pr)
check("I1b struck (cancelled+superseded) steps are reported apart, not as open",
      _pr["struck"] == 2 and _pr["total"] == 5, _pr)
write_graph(_sid2, [node("n1", "done", ["out.txt"]),
                    {"id": "n2", "label": "n2", "status": "superseded",
                     "plan": 1, "reason": "not needed"}])
_pr2 = G.progress(_sid2)
check("I1c a plan whose only remaining work was superseded is COMPLETE",
      _pr2["steps"] == 1 and _pr2["open"] == 0 and _pr2["complete"] is True, _pr2)

# I2: the durable goal is the AUTHORITY — an ordinary message inside an ACTIVE goal is
#     a goal turn; a PAUSED or COMPLETED goal never hijacks the chat.
_sid3 = mk_session("durable")
G.start(_sid3, "finish the widget")
check("I2a an ACTIVE goal makes every turn a goal turn (no /goal flag needed)",
      H._goal_mode_of({"id": _sid3}, False) is True)
check("I2b a requested /goal is a goal turn even with no record",
      H._goal_mode_of({"id": mk_session("none")}, True) is True)
check("I2c a session without a goal runs a normal turn",
      H._goal_mode_of({"id": mk_session("plain")}, False) is False)
G.pause(_sid3)
check("I2d a PAUSED goal does not hijack an ordinary message",
      H._goal_mode_of({"id": _sid3}, False) is False)
G.resume(_sid3)
G.complete(_sid3, "done")
check("I2e a COMPLETED goal does not hijack an ordinary message",
      H._goal_mode_of({"id": _sid3}, False) is False)

# I3: an ordinary message inside an active goal must NOT replace its objective.
_sid4 = mk_session("objective-kept")
G.start(_sid4, "the real objective")
H._goal_begin({"id": _sid4}, True, "just a normal follow-up question",
              requested=False)
check("I3 an ordinary message keeps the goal's objective",
      (G.load(_sid4) or {}).get("objective") == "the real objective",
      (G.load(_sid4) or {}).get("objective"))

# I4: the verdict is re-computed at EVERY goal turn end, not only on a complete plan.
_sid5 = mk_session("verdict-always")
ws5 = os.path.join(TMP, "wsI5")
os.makedirs(ws5, exist_ok=True)
_s5 = stores.load_session(_sid5)
_s5["workspace"] = ws5
stores.save_session(_s5)
write_graph(_sid5, [node("n1", "done", ["out.txt"]), node("n2", "todo")])
G.start(_sid5, "ship it")
_one = {"id": _sid5, "workspace": ws5}
_saved_vc2 = G.verify_config
G.verify_config = lambda: {"acceptance": False, "judge": False, "judge_model": ""}
H._goal_end(_one, True)
G.verify_config = _saved_vc2
_rec5 = G.load(_sid5) or {}
check("I4 a goal turn with an OPEN plan still records a fresh verdict",
      bool(_rec5.get("verification"))
      and _rec5["verification"].get("verified") is False
      and _rec5.get("status") == "active", _rec5.get("verification"))
check("I4b the unverified goal keeps a note naming the first gap",
      "unverified" in str(_rec5.get("note") or ""), _rec5.get("note"))

# I5: the loop's own decision — an active goal with open steps CONTINUES.
from longrun.plan import keepgoing as KG                            # noqa: E402
_dec = KG.decide(open_nodes=2, rounds=1, stale=0,
                 started=__import__("time").time(), goal_mode=True,
                 goal_complete=False)
check("I5 a goal turn cannot stop on open steps (the loop insists)",
      _dec["continue"] is True, _dec)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
