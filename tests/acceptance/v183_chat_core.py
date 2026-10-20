#!/usr/bin/env python3
"""v183 — chat-loop core: a turn runs, concludes, and never loops forever on a
call that already failed (JAG-183).

Deterministic: the LLM and the tool gate are MOCKED (no router, no GPU, no
network, isolated temp data dir). Two scenarios on two sessions:

  A) a NORMAL turn: the model asks for a tool -> it runs -> the model concludes ->
     the assistant reply is PERSISTED (proves the loop + the "no request without
     an answer" contract).
  B) a STUCK model: it re-issues the EXACT same FAILED call five times. The harness
     must execute it ONCE, then BLOCK the verbatim re-runs with a directive.
     Before JAG-183 it executed it every time and the model resigned.
  C) DELEGATION (JAG-189): the model emits {"action":"subagent",...} -> exactly ONE
     child run is spawned, its summary is fed back, and the turn concludes.
  D) STALE PLAN (JAG-189): a turn that OPENS with an open task list from an earlier
     request and answers in plain prose must NOT be force-continued onto that list.

Run:  python3 tests/v183_chat_core.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import atexit  # noqa: E402
import shutil  # noqa: E402
tmp = tempfile.mkdtemp(prefix="sf-183-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile  # noqa: E402
py_compile.compile(os.path.join(REPO, "src", "longrun", "core/server.py"), doraise=True)
print("[compile] server.py OK")

from longrun.core import server  # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))

CALL_OK = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'
CALL_BAD = '{"action":"tool","tool":"shell","args":{"command":"adb -s dev input tap 100 200"}}'


def run_turn(sid, script, gated):
    """Drive chat_once with a scripted model (`script(n)` -> text) and a mocked
    tool gate (`gated()` -> result dict). Returns (events, execution count)."""
    state = {"n": 0}
    execs = {"n": 0}

    def fake_gated(tool, args, **kw):
        execs["n"] += 1
        return gated()

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events, execs["n"]


def blocked(events):
    return [d for k, d in events
            if k == "harness.inject" and "CALL BLOCKED" in (d.get("text") or "")]


# ---- scenario A: a normal turn ---------------------------------------------
def gated_ok():
    return {"status": "executed",
            "observation": "[shell] exit=0 backend=stub sandboxed=False\nstdout: hi",
            "result": {"ok": True, "exit_code": 0, "stdout": "hi", "stderr": "",
                       "backend": "stub"}}


def script_ok(n):
    return CALL_OK if n == 0 else "fatto: comando eseguito."


ev_a, ex_a = run_turn("v183a", script_ok, gated_ok)
check("A1 tool executed exactly once", ex_a == 1, "execs=%d" % ex_a)
check("A2 tool.call card emitted", len([1 for k, _ in ev_a if k == "tool.call"]) == 1)
check("A3 no spurious block on a normal turn", not blocked(ev_a), "blocked=%d" % len(blocked(ev_a)))
sess = server.load_session("v183a") or {}
msgs = sess.get("messages", [])
last = msgs[-1] if msgs else {}
check("A4 assistant reply persisted",
      last.get("role") == "assistant" and "fatto" in (last.get("content") or ""),
      "%s: %r" % (last.get("role"), (last.get("content") or "")[:40]))


# ---- scenario B: stuck model, anti-loop (JAG-183) --------------------------
def gated_bad():
    err = "RuntimeError: adb: unknown command input"
    return {"status": "executed",
            "observation": "[shell] exit=1 backend=stub sandboxed=False\nstderr: " + err,
            "result": {"ok": False, "exit_code": 1, "stdout": "", "stderr": err,
                       "backend": "stub"}}


def script_bad(n):
    return CALL_BAD if n <= 4 else "mi fermo e chiedo."


ev_b, ex_b = run_turn("v183b", script_bad, gated_bad)
check("B1 failed call executed only ONCE", ex_b == 1, "execs=%d" % ex_b)
check("B2 verbatim re-runs BLOCKED (JAG-183)", len(blocked(ev_b)) >= 1,
      "blocked=%d" % len(blocked(ev_b)))


# ---- scenario C: delegation to ONE subagent (JAG-189) ----------------------
from longrun.agent import subagent as subagent_mod  # noqa: E402

def script_sub(n):
    return ('{"action":"subagent","goal":"summarize server.py","max_steps":2}'
            if n == 0 else "delegato e riassunto: fatto.")

_spawns = {"n": 0}
_orig_spawn = subagent_mod.spawn
_orig_collect = subagent_mod.collect

def _fake_spawn(goal, **kw):
    _spawns["n"] += 1
    return {"subagent_id": "sub_test", "run_id": "sub_test", "goal": goal}

def _fake_collect(sid, timeout=None):
    return {"ok": True, "status": "done", "steps": 2, "subagent_id": sid,
            "summary": "server.py = HTTP+SSE loop", "trace": []}

subagent_mod.spawn = _fake_spawn
subagent_mod.collect = _fake_collect
try:
    ev_c, _ = run_turn("v183c", script_sub, gated_ok)
finally:
    subagent_mod.spawn = _orig_spawn
    subagent_mod.collect = _orig_collect
check("C1 subagent spawned exactly once", _spawns["n"] == 1, "spawns=%d" % _spawns["n"])
check("C2 subagent result fed back to the model",
      any(k == "harness.inject" and "server.py = HTTP+SSE loop" in (d.get("text") or "")
          for k, d in ev_c),
      "injects=%d" % len([1 for k, _ in ev_c if k == "harness.inject"]))
check("C3 subagent tool card emitted",
      any(k == "tool.call" and d.get("tool") == "subagent" for k, d in ev_c))
_cs = (server.load_session("v183c") or {}).get("messages", [{}])[-1]
check("C4 reply persisted after delegation",
      _cs.get("role") == "assistant" and "fatto" in (_cs.get("content") or ""),
      "%r" % (_cs.get("content") or "")[:40])
_ccards = (server.load_session("v183c") or {}).get("tool_cards", [])
check("C5 subagent card PERSISTED for reload (JAG-190)",
      any(c.get("tool") == "subagent" for c in _ccards),
      "cards=%s" % [c.get("tool") for c in _ccards])


# ---- scenario D: a fresh user message is not hijacked by a stale plan ------
_gd = server.taskgraph.ensure("v183d", session_id="v183d")
server.taskgraph.add_node(_gd, "old step from an earlier request")

def script_plain(n):
    return "risposta diretta all'utente, nessun tool."

ev_d, _ = run_turn("v183d", script_plain, gated_ok)
_cont = [d for k, d in ev_d if k == "harness.inject"
         and "still has" in (d.get("text") or "")]
check("D1 stale plan does NOT force a continuation (JAG-189)", not _cont,
      "continue_injects=%d" % len(_cont))
_ds = (server.load_session("v183d") or {}).get("messages", [{}])[-1]
check("D2 the direct answer is persisted",
      _ds.get("role") == "assistant" and "risposta diretta" in (_ds.get("content") or ""),
      "%r" % (_ds.get("content") or "")[:40])


# ---- scenario E: harness-action cards are PERSISTED for reload (JAG-190) ---
_PLAN = '{"action":"write_todos","todos":[{"label":"step one"},{"label":"step two"}]}'
_DONE0 = '{"action":"update_todos","steps":[{"index":0,"status":"done","evidence":"did one"}]}'
_DONE1 = '{"action":"update_todos","steps":[{"index":1,"status":"done","evidence":"did two"}]}'

def script_plan(n):
    return (_PLAN, _DONE0, _DONE1)[n] if n < 3 else "piano chiuso."

run_turn("v183e", script_plan, gated_ok)
_ecards = (server.load_session("v183e") or {}).get("tool_cards", [])
_tools = [c.get("tool") for c in _ecards]
check("E1 todo.write card persisted (JAG-190)", "todo.write" in _tools,
      "cards=%s" % _tools)
check("E2 todo.update card persisted (JAG-190)", "todo.update" in _tools,
      "cards=%s" % _tools)


# ---- scenario F: relative fs paths bind to the session workspace (JAG-191) --
# Before the fix, fs.write {"path":"HELLO.txt"} on a session whose workspace was
# /…/TESTS/harness-e2e wrote to the HARNESS REPO instead. Relative paths must
# resolve against the workspace (like the shell tool's cwd), not REPO.
from longrun.tools import registry as _reg  # noqa: E402
from longrun.tools import tools as _tools  # noqa: E402
_ws = os.path.join(REPO, "data", "v183ws-%d" % os.getpid())
os.makedirs(_ws, exist_ok=True)
atexit.register(lambda: shutil.rmtree(_ws, ignore_errors=True))
_rp, _rerr = _reg.resolve_path("HELLO.txt", _reg.tool_spec("fs.write")["roots"],
                               base=_ws)
check("F1 relative path resolves under the workspace",
      _rerr is None and _rp == os.path.join(_ws, "HELLO.txt"),
      "%s err=%s" % (_rp, _rerr))
_rw = _tools.execute("fs.write", {"path": "HELLO.txt", "content": "hi\n",
                                  "workspace": _ws})
check("F2 fs.write lands in the workspace, not the repo",
      _rw.get("ok") and _rw.get("path") == os.path.join(_ws, "HELLO.txt"),
      "%s" % _rw.get("path"))
check("F3 the file really exists in the workspace",
      os.path.isfile(os.path.join(_ws, "HELLO.txt")))
_abs = _tools.execute("fs.read", {"path": os.path.join(_ws, "HELLO.txt"),
                                  "workspace": "/nope-191"})
check("F4 absolute paths are unaffected by the workspace base",
      _abs.get("ok") and "hi" in (_abs.get("content") or ""),
      "%s" % _abs.get("error"))


# ---- scenario G: reload boundaries spread across a turn (JAG-192) -----------
# Every card/inject of a multi-step turn used to be persisted with the SAME
# `after` (the turn-start transcript length, because the turn's history is
# flushed into sess["messages"] only at the end). A reload then stacked the
# whole turn at the top and pushed the user prompts to the bottom. The boundary
# must INCREASE within the turn. `node` must be a node id string, never a dict.
_g_cards = (server.load_session("v183e") or {}).get("tool_cards", [])
_g_inj = (server.load_session("v183e") or {}).get("injects", [])
_a_cards = [c.get("after") for c in _g_cards]
_a_inj = [r.get("after") for r in _g_inj]
check("G1 every card/inject carries an int 'after'",
      (_a_cards + _a_inj) and all(isinstance(a, int) for a in (_a_cards + _a_inj)),
      "cards=%s inj=%s" % (_a_cards, _a_inj))
check("G2 boundaries INCREASE across the turn (JAG-192)",
      _a_cards == sorted(_a_cards) and _a_inj == sorted(_a_inj)
      and len(set(_a_cards + _a_inj)) > 1, "cards=%s inj=%s" % (_a_cards, _a_inj))
_node_types = set(type(c.get("node")).__name__ for c in _g_cards)
check("G3 card 'node' is an id string or None, never a dict (JAG-192)",
      _node_types <= {"str", "NoneType"}, "types=%s" % _node_types)


# ---- scenario H: a new task keeps the old plan's nodes + fresh ids (JAG-194) --
# A finished task used to hard-`reset` the graph (nodes deleted, ids restarted at
# n1), so the transcript's old cards resolved to the NEW nodes (wrong labels).
# A new plan must bump `plan`, KEEP the old nodes, and number new ones
# monotonically; render_todos must show only the current plan.
from longrun.plan import taskgraph as _tg  # noqa: E402
_gk = "v183h"
_g = _tg.ensure(_gk)
_a = _tg.add_node(_g, "old step one", status="done", evidence="did it")
_b = _tg.add_node(_g, "old step two", status="done", evidence="did it")
check("H1 old plan nodes tagged plan 0",
      _a.get("plan") == 0 and _b.get("plan") == 0,
      "a=%s b=%s" % (_a.get("plan"), _b.get("plan")))
check("H2 all_done on the finished plan", _tg.all_done(_g) is True)
_plan = _tg.begin_plan(_g)
_g = _tg.load(_gk)
_c = _tg.add_node(_g, "new step", status="todo")
check("H3 new plan KEEPS the old nodes (no hard reset)",
      len(_g.get("nodes", [])) == 3, "nodes=%d" % len(_g.get("nodes", [])))
check("H4 the new node gets a FRESH id (old ids not reused)",
      _c["id"] == "n3", "id=%s" % _c["id"])
check("H5 the new node is tagged with the new plan",
      _c.get("plan") == _plan and _plan == 1,
      "plan=%s node_plan=%s" % (_plan, _c.get("plan")))
_rt = _tg.render_todos(_g)
check("H6 render_todos shows ONLY the current plan",
      "new step" in _rt and "old step one" not in _rt,
      _rt.splitlines()[0] if _rt else "")


# ---- scenario I: a final answer with OPEN todos is REJECTED (JAG-402) -------
# The model writes a todo list, then tries to give a final answer WITHOUT
# closing the steps. Before JAG-402 the answer was accepted and the todos
# stayed open forever. Now the harness REJECTS the final answer and forces the
# model to close every step (done / superseded) before its reply reaches the
# user. Stale plans from a previous turn (JAG-189 pivot) are still allowed.
_I_PLAN = '{"action":"write_todos","todos":[{"label":"do thing one"},{"label":"do thing two"}]}'
_I_DONE0 = '{"action":"update_todos","steps":[{"index":0,"status":"done","evidence":"ran cmd X"}]}'
_I_DONE1 = '{"action":"update_todos","steps":[{"index":1,"status":"done","evidence":"ran cmd Y"}]}'


def script_close_todos(n):
    seq = (_I_PLAN, "finito, tutto fatto.", _I_DONE0, _I_DONE1, "tutto chiuso, risultato finale.")
    return seq[n] if n < len(seq) else "tutto chiuso, risultato finale."


ev_i, _ = run_turn("v183i", script_close_todos, gated_ok)
_rej = [d for k, d in ev_i if k == "harness.inject"
        and "REJECTED" in (d.get("text") or "")]
check("I1 final answer with open todos is REJECTED (JAG-402)",
      len(_rej) >= 1, "rejected_injects=%d" % len(_rej))
_si = (server.load_session("v183i") or {}).get("messages", [{}])[-1]
check("I2 the accepted final answer comes AFTER the todos were closed",
      _si.get("role") == "assistant" and "tutto chiuso" in (_si.get("content") or ""),
      "%r" % (_si.get("content") or "")[:50])
_gi = _tg.load("v183i") or {}
_open_i = [n for n in _tg.plan_nodes(_gi) if n.get("status") in _tg.OPEN_STATUSES]
check("I3 no todo is left open at the end of the turn",
      len(_open_i) == 0, "open=%d" % len(_open_i))


print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

