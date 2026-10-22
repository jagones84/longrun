#!/usr/bin/env python3
"""v529 — Session Jobs (SJ): dependency-ordered subagents INSIDE one session.

Deterministic — no model, no server, no network. Covers:
  A) `create` validation: >=1 subjob, unique labels, known deps, no cycles.
  B) the ledger is a real per-session file (saved + deleted with the session).
  C) the ready-queue scheduler: a dependent subjob STARTS only after its deps
     finished and receives their output; independent items start together;
     a failed dependency BLOCKS its dependents (never an infinite wait).
  D) subagent results are DURABLE (survive losing the in-memory entry).
  E) the shared `util.dag` primitives back BOTH engines (no duplicated logic).
  F) the wiring: batch subagent items -> SJ, `self {action:"sj"}`, the REST
     route, and the session-delete cascade.
"""
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Sandbox the stores BEFORE importing anything from longrun (the module-level
# constants are bound at import time).
TMP = tempfile.mkdtemp(prefix="sf-v529-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# core/server.py imports the prompt constants out of agent.py, so import it first.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.agent import session_jobs as SJ  # noqa: E402
from longrun.agent import subagent as SUB  # noqa: E402
from longrun.util import dag  # noqa: E402

SID = "s_v529"

# ------------------------------------------------------------------ A: create --
check("A1 an SJ needs at least one subjob",
      SJ.create(SID, "g", []).get("ok") is False)
check("A2 duplicate labels are refused",
      SJ.create(SID, "g", [{"label": "a", "goal": "x"},
                           {"label": "a", "goal": "y"}]).get("ok") is False)
check("A3 a dep on an unknown label is refused",
      SJ.create(SID, "g", [{"label": "a", "goal": "x", "deps": ["nope"]}]).get("ok") is False)
check("A4 a dependency CYCLE is refused",
      SJ.create(SID, "g", [{"label": "a", "goal": "x", "deps": ["b"]},
                           {"label": "b", "goal": "y", "deps": ["a"]}]).get("ok") is False)
made = SJ.create(SID, "the goal", [{"label": "a", "goal": "TASK a"},
                                   {"label": "b", "goal": "TASK b", "deps": ["a"]}])
check("A5 a valid plan returns SJ1 with SJ1.1 / SJ1.2 and the label map",
      made.get("ok") is True and made.get("job") == "SJ1"
      and made.get("subjobs") == ["SJ1.1", "SJ1.2"]
      and made.get("labels") == {"SJ1.1": "a", "SJ1.2": "b"},
      str(made))

# --------------------------------------------------------------- B: storage ---
ledger = SJ.path_for(SID)
_sessions_dir = os.environ["LONGRUN_SESSIONS_DIR"]
check("B1 the ledger gets its OWN directory (never inside data/sessions/)",
      os.path.isfile(ledger)
      and os.path.basename(ledger) == SID + ".json"
      and os.path.realpath(os.path.dirname(ledger)) != os.path.realpath(_sessions_dir),
      ledger)
check("B2 the ledger is the persisted SJ graph, not an in-memory stub",
      "SJ1.2" in open(ledger, encoding="utf-8").read())

# B3 — REGRESSION (live, 2026-10-22): writing the ledger INTO data/sessions made
# `stores.list_sessions()` raise KeyError: 'id' (it globs *.json there and reads
# s["id"]), so /api/sessions answered an EMPTY response and the WebUI showed
# "Sessions unavailable". A foreign JSON in that directory must be ignored.
from longrun.memory import stores as ST  # noqa: E402
with open(os.path.join(_sessions_dir, "stray_not_a_session.sj.json"), "w",
          encoding="utf-8") as _f:
    _f.write('{"seq": 1, "jobs": {}}')
with open(os.path.join(_sessions_dir, "real_session.json"), "w",
          encoding="utf-8") as _f:
    _f.write('{"id": "s_probe", "title": "probe", "messages": []}')
_rows = ST.list_sessions()
check("B3 a foreign JSON in data/sessions does not break the session list",
      any(r.get("id") == "s_probe" for r in _rows)
      and all(r.get("id") for r in _rows),
      "%d rows" % len(_rows))

# ------------------------------------------------------------- C: scheduler ---
class FakeWorkers:
    """A deterministic stand-in for the subagent layer (no model involved)."""

    def __init__(self, delay=0.12):
        self.lock = threading.Lock()
        self.delay = delay
        self.inflight = 0
        self.maxinflight = 0
        self.started = []            # the prompt of every spawn, in order
        self.by_id = {}

    def spawn(self, goal, parent_run_id=None, max_steps=4, model=None, depth=0,
              role=None):
        tid = "sb_%d" % (len(self.by_id) + 1)
        with self.lock:
            self.inflight += 1
            self.maxinflight = max(self.maxinflight, self.inflight)
            self.started.append(goal)
            self.by_id[tid] = goal
        return {"subagent_id": tid, "run_id": "run_" + tid}

    def collect(self, sub_id, timeout=None):
        time.sleep(self.delay)
        with self.lock:
            self.inflight -= 1
            goal = self.by_id.get(sub_id, "")
        ok = "FAILME" not in goal
        first = goal.split("\n")[0][:60]
        return {"ok": ok, "summary": "out:%s" % first,
                "error": None if ok else "boom"}


# C1/C3 — a dependency orders the start AND feeds the output forward
SJ.delete(SID)
order_plan = SJ.create(SID, "ordered", [
    {"label": "a", "goal": "TASK a"},
    {"label": "b", "goal": "TASK b", "deps": ["a"]}])
hooks = []
w1 = FakeWorkers()
res1 = SJ.run(SID, order_plan["job"], hook=lambda k, s: hooks.append((k, s.get("label"))),
              spawn_fn=w1.spawn, collect_fn=w1.collect, cap=4)
check("C1 a dependent subjob starts only AFTER its dependency finished",
      len(w1.started) == 2 and "TASK a" in w1.started[0] and "TASK b" in w1.started[1],
      str(w1.started))
check("C2 the dependent received its dependency's output as input",
      "## Input from dependencies" in w1.started[1]
      and "out:TASK a" in w1.started[1], w1.started[1][-200:])
check("C3 the SJ finishes `done` and reports both subjobs",
      res1.get("status") == "done" and len(res1.get("subjobs") or []) == 2,
      str(res1.get("status")))
check("C4 the hook fired start+done per subjob",
      sorted(hooks) == [("done", "a"), ("done", "b"), ("start", "a"), ("start", "b")],
      str(hooks))

# C5 — independent items really run together (parallel, under the cap)
SJ.delete(SID)
par_plan = SJ.create(SID, "parallel", [
    {"label": "p", "goal": "TASK p"}, {"label": "q", "goal": "TASK q"}])
w2 = FakeWorkers()
SJ.run(SID, par_plan["job"], spawn_fn=w2.spawn, collect_fn=w2.collect, cap=2)
check("C5 independent subjobs are in flight TOGETHER (max in-flight == 2)",
      w2.maxinflight == 2, "max=%s" % w2.maxinflight)

# C6 — a failed dependency BLOCKS its dependents (no infinite wait)
SJ.delete(SID)
fail_plan = SJ.create(SID, "failing", [
    {"label": "a", "goal": "TASK a FAILME"},
    {"label": "b", "goal": "TASK b", "deps": ["a"]}])
w3 = FakeWorkers(delay=0.01)
res3 = SJ.run(SID, fail_plan["job"], spawn_fn=w3.spawn, collect_fn=w3.collect, cap=4)
blocked = [s for s in res3.get("subjobs") or [] if s.get("label") == "b"]
check("C6 a failed dependency marks its dependent `blocked` with the reason",
      # nothing succeeded (a failed, b blocked) -> the SJ is `error`, and b is
      # blocked naming the FAILED subjob id, never left running forever.
      res3.get("status") == "error" and blocked
      and blocked[0].get("status") == "blocked"
      and "dependency failed: SJ1.1" in str(blocked[0].get("error")),
      "%s | %s" % (res3.get("status"), res3.get("subjobs")))

# C7 — a raising spawn_fn is reported as a failed subjob, never propagated
SJ.delete(SID)
boom_plan = SJ.create(SID, "boom", [{"label": "a", "goal": "TASK a"},
                                    {"label": "b", "goal": "TASK b"}])


def _boom(goal, **kw):
    raise RuntimeError("no workspace")


res7 = SJ.run(SID, boom_plan["job"], spawn_fn=_boom,
              collect_fn=lambda *a, **k: {"ok": True}, cap=2)
check("C7 a raising spawn is recorded as a failed subjob, not propagated",
      # BOTH items raise (no deps between them), so both are `error` with the real
      # reason — a stale "blocked / dependency never satisfied" would be a lie.
      res7.get("status") == "error"
      and all(s.get("status") == "error" for s in res7.get("subjobs") or [])
      and all("spawn raised" in str(s.get("error"))
              for s in res7.get("subjobs") or []),
      str(res7.get("subjobs")))

# ------------------------------------------------------- D: durable results ---
rec = SUB._persist({"id": "sb_durable", "parent": SID, "status": "done",
                    "summary": "durable summary", "steps": 3})
got = SUB.collect("sb_durable", timeout=1)
check("D1 a subagent result survives losing the in-memory entry (served from disk)",
      got.get("ok") is True and got.get("summary") == "durable summary"
      and got.get("from_disk") is True, str(got))
check("D2 a session's subagent records die with it (purge_parent)",
      bool(SUB.purge_parent(SID)) and SUB.load_record("sb_durable") is None)

# ---------------------------------------------------------------- E: shared ---
from longrun.orchestrate import jobs as JOBS  # noqa: E402
check("E1 both engines use the SAME waves() (re-exported, not duplicated)",
      JOBS.waves is dag.waves)
check("E2 waves order a diamond correctly and break a cycle instead of hanging",
      dag.waves(["a", "b", "c"], {"a": [], "b": ["a"], "c": ["a"]}) == [["a"], ["b", "c"]]
      and len(dag.waves(["a", "b"], {"a": ["b"], "b": ["a"]})) == 2)
check("E3 has_cycle is the strict twin of waves",
      dag.has_cycle(["a", "b"], {"a": ["b"], "b": ["a"]}) is True
      and dag.has_cycle(["a", "b"], {"a": [], "b": ["a"]}) is False)
check("E4 ready() returns only the items whose deps are ALL done",
      dag.ready(["b", "c"], {"b": ["a"], "c": ["b"]}, ["a"]) == ["b"]
      and dag.ready(["b", "c"], {"b": ["a"], "c": ["b"]}, ["a", "b"]) == ["b", "c"])
check("E5 blockers_state fails a dependent on error/partial, missing = satisfied",
      dag.blockers_state(["x"], {"x": "partial"}) == (False, ["x"])
      and dag.blockers_state(["gone"], {}) == (True, []))

# --------------------------------------------------------------- F: wiring ----
agent_src = _read("src", "longrun", "agent", "agent.py")
tools_src = _read("src", "longrun", "tools", "tools.py")
reg_src = _read("src", "longrun", "tools", "registry.py")
http_src = _read("src", "longrun", "core", "httpapi.py")
stores_src = _read("src", "longrun", "memory", "stores.py")
api_src = _read("src", "longrun", "core", "api_v02.py")
check("F1 a batch's subagent items are routed through the SJ engine",
      "from longrun.agent import session_jobs as _sj" in agent_src
      and "_sj.create(" in agent_src and "_sj.run(" in agent_src
      and "_spawn_batch_subagent" not in agent_src)
check("F2 `self {action:'sj'}` is implemented, documented and accepted",
      'action in ("sj", "session-jobs"' in tools_src
      and '"sj", "session-jobs", "sessionjobs", "subjobs"' in tools_src
      and '"sj": ["session", "job"]' in reg_src
      and '"info", "diagnose", "logs", "context", "tools", "sj"' in reg_src)
check("F3 the WebUI/REST surface exists: GET /api/sessions/<sid>/sj",
      'path.endswith("/sj")' in http_src and "session_jobs as _sj" in http_src)
check("F4 deleting a session drops its SJ ledger and its subagent records",
      "session_jobs.path_for(sid)" in stores_src
      and "subagent_mod.purge_parent(sid)" in stores_src)
check("F5 the prompt teaches label/deps/input_from (and no invented order)",
      "`label` names the item" in api_src
      and "Input from dependencies" in api_src and '"deps":["data"]' in api_src)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
