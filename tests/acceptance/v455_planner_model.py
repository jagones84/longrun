#!/usr/bin/env python3
"""v455 — ONE model per turn: the planner is the session's chat model (JAG-455).

Reported live: benchmark sessions whose model read `deepseek-reasoner` while the DGX
GPU was busy, and "the planner is not the same model as the session chat". Root cause
(one, several symptoms): the plan was routed by a SEPARATE `planner` role whose
`pattern: qwen` matched the LOCAL weights, so a session pinned to a cloud model still
made a local model call (the router's autoload then loaded it).

The fix removes the planner role entirely: the plan runs on the turn's own model
(`routing.turn_model`), everywhere. It also pins the delete lifecycle (a deleted
session can neither be resurrected by a live turn nor grow a look-alike row).

Deterministic: no model, no network, no server.
Run: python3 tests/acceptance/v455_planner_model.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-455-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server    # noqa: E402 — must precede httpapi (circular import)
from longrun.core import httpapi   # noqa: E402
from longrun.model import routing  # noqa: E402
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


class _FakeSrv:
    """Router-facing stub: a known session pin, a distinct harness default."""

    DEFAULT = "default:cloud-model"

    def load_session(self, sid):
        return {"id": sid, "model": "session-pinned:model"} if sid == "known" else None

    def default_model(self):
        return self.DEFAULT


real_pick = routing.pick
real_srv = routing._srv
try:
    # The role pattern resolves to a LOCAL alias we must NEVER see used again.
    routing.pick = lambda role, preferred=None: "local-qwen-alias"
    routing._srv = lambda: _FakeSrv()

    # ---- A: the planner model IS the turn's model ----------------------------
    got = httpapi._planner_model({"model": "deepseek:deepseek-reasoner"},
                                 "deepseek:deepseek-reasoner")
    check("A1 an explicit request model wins", got == "deepseek:deepseek-reasoner", got)
    got = httpapi._planner_model({"model": "deepseek:deepseek-reasoner"}, None)
    check("A2 the session pin is used when the request has no model",
          got == "deepseek:deepseek-reasoner", got)
    got = httpapi._planner_model({"model": "deepseek:deepseek-reasoner"}, "explicit:model")
    check("A3 the explicit request model beats the session pin", got == "explicit:model", got)
    got = httpapi._planner_model("known", None)
    check("A4 a session ID (str) resolves to that session's pin",
          got == "session-pinned:model", got)
    got = httpapi._planner_model("unknown", None)
    check("A5 an unknown session id falls back to the harness default",
          got == _FakeSrv.DEFAULT, got)
    got = httpapi._planner_model({}, None)
    check("A6 with NO pin the planner is the harness default — NEVER the role pattern",
          got == _FakeSrv.DEFAULT and got != "local-qwen-alias", got)
    check("A7 a missing session does not blow up",
          httpapi._planner_model(None, None) == _FakeSrv.DEFAULT)

    def _boom(role, preferred=None):
        raise RuntimeError("router unreachable")

    routing.pick = _boom
    check("A8 an unroutable role never breaks the turn",
          httpapi._planner_model({"model": "x"}, None) == "x")
    check("A9 turn_model never consults a planner role",
          routing.turn_model({"model": "x"}, None) == "x")
finally:
    routing.pick = real_pick
    routing._srv = real_srv

# ---- B: every planner call site is wired to the turn model -------------------
http_src = _read("src", "longrun", "core", "httpapi.py")
tg_src = _read("src", "longrun", "plan", "taskgraph.py")
ag_src = _read("src", "longrun", "agent", "agent.py")
dc_src = _read("src", "longrun", "model", "decision.py")
rt_src = _read("src", "longrun", "model", "routing.py")
av_src = _read("src", "longrun", "core", "api_v02.py")

check("B1 the sync /api/chat planner uses _planner_model",
      '_planner_model(sess, body.get("model"))' in http_src)
check("B2 the planner and the ANSWER share ONE model variable",
      'start_run_graph(sess["id"], message, sess["id"], _tm,' in http_src
      and "chat_once(sess, message, _tm," in http_src)
check("B3 the plan (write_todos) uses the session's model",
      "m = routing.turn_model(session_id, model)" in tg_src)
check("B4 the RE-plan uses the session's model",
      'm = routing.turn_model(graph.get("session_id"), model)' in tg_src)
check("B5 the legacy planner uses the turn model, not a planner role",
      "model = routing.turn_model(None, model)" in ag_src)
check("B6 the heuristic router has no planner branch",
      'role = "planner" if' not in dc_src and "role = ctx.role or \"agent\"" in dc_src)
check("B7 api_v02 never overrides an EXPLICIT model with a route hint",
      # JAG-478: the hint moved into ONE resolver (`_routed_agent_model`) that the
      # run loop, the HTTP route and the session recorder all share; an explicit
      # model is still returned FIRST and untouched.
      "model = model or _routed_agent_model(goal)" in av_src
      and "if explicit:\n        return explicit" in av_src
      and "_hint.model\n" not in av_src
      and "getattr(_hint, \"model\", \"\")" in av_src)

# ---- C: the planner ROLE is gone from the config ----------------------------
check("C1 DEFAULT_CONFIG has no planner role", '"planner"' not in rt_src)
routing_cfg = _read("config", "routing.yaml")
check("C2 config/routing.yaml has no planner role", "planner:" not in routing_cfg)
check("C3 turn_model exists and documents the one-model rule",
      "def turn_model(" in rt_src and "NO separate planner model" in rt_src)
check("C4 no source file still calls pick(\"planner\")",
      not any('pick("planner")' in _read("src", "longrun", p)
              for p in ("core/httpapi.py", "plan/taskgraph.py", "agent/agent.py",
                        "model/decision.py", "core/api_v02.py")))
# C5: `routing.update()` CREATES a missing role on demand, so a bench arm that still
# pins the deleted `planner` role silently puts it BACK into config/routing.yaml.
check("C5 the bench arm does not resurrect a planner role in the config",
      '"planner"' not in _read("benchmarks", "longrun_adapter.py"))

# ---- D: the DELETE lifecycle cannot resurrect a session ---------------------
st_src = _read("src", "longrun", "memory", "stores.py")
check("D1 a deleted transcript is MOVED to trash/, not unlinked",
      "TRASH_DIR" in st_src and "os.replace(path, dest)" in st_src
      and "_trash_move(f)" in st_src)
check("D2 the trash is pruned (bounded)", "_prune_trash()" in st_src
      and "_TRASH_KEEP" in st_src)
check("D3 a deleted id is REFUSED by the chat surface — no look-alike row",
      "def _open_session(" in http_src and "return get_or_create_session(sid, title" in http_src)
check("D4 every chat path resolves through _open_session and 404s when it is gone",
      http_src.count("_open_session(") >= 4 and '"session was deleted"' in http_src)
check("D5 DELETE still 404s on an already-gone session (idempotent)",
      "if not os.path.isfile(fpath):" in http_src and '"session not found"' in http_src)
check("D6 the tombstone is still RETAINED on delete (v222/v315 contract kept)",
      "_DELETED_SESSIONS.add(sid)" in http_src and "_persist_tombstones()" in http_src)

# ---- D functional: a deleted id can never grow a look-alike row -------------
with stores._deleted_lock:
    stores._DELETED_SESSIONS.add("deadbeefcafe")
try:
    check("D7 _open_session REFUSES a tombstoned id (returns None, no new row)",
          httpapi._open_session("deadbeefcafe") is None)
    check("D8 _open_session still opens a session when no id is given",
          bool((httpapi._open_session(None, "t455") or {}).get("id")))
finally:
    with stores._deleted_lock:
        stores._DELETED_SESSIONS.discard("deadbeefcafe")

print("---")
okc = sum(results)
print("\nv455: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)