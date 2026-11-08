#!/usr/bin/env python3
"""v900 — a child run's step budget is CONFIG, never a literal `4`.

Evidence (2026-11-07): session job SJ1.1 (`sub_3f8156c3a6.json`) ended with
`termination: max_steps`, `steps: 5`, `max_steps: 4` — the research child was
stopped one turn before its final answer because every call path that omitted
`max_steps` inherited a hardcoded 4 (spawn default, the model's `subagent`
action, the run-loop action, a Session Job subjob, the MCP tool, the HTTP
endpoints, the swarm workers, the schema repair).

Contract pinned here:
  A) `config/subagents.yaml` ships `max_steps`, and `subagent.default_steps()`
     is the ONE reader of it.
  B) A spawn that passes no `max_steps` hands the configured value to the child.
  C) A Session Job subjob without `max_steps` records the configured value.
  D) No call path defaults to a literal 4 any more.
  E) The dispatched-teammate budget stays coherent: `chat_tool_iters` must not
     preempt the continuation loop (`steps x keepgoing_max`), and one chat turn
     must be big enough for a research/verify delegate.

Deterministic: no model, no server, no network.
Run: python3 tests/acceptance/v900_subagent_step_budget.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-900-")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import subagent as SA           # noqa: E402
from longrun.agent import session_jobs as SJ      # noqa: E402
from longrun.model import context_limits as CL    # noqa: E402
from longrun.plan import keepgoing as KG          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- A) the shipped row + the one reader -----------------------------------
_shipped = _read("config", "subagents.yaml")
_row = re.search(r"^max_steps:\s*(\d+)\s*$", _shipped, re.M)
check("A1 config/subagents.yaml ships a max_steps row", _row is not None)
check("A2 the shipped budget is bigger than the 4 that cut SJ1.1 off",
      _row is not None and int(_row.group(1)) >= 6,
      _row.group(1) if _row else "missing")

_cfg = dict(SA.load_cfg())
_cfg["max_steps"] = 7
SA.save_cfg(_cfg)
check("A3 default_steps() reads the config row",
      SA.default_steps() == 7, SA.default_steps())
_cfg.pop("max_steps", None)
SA.save_cfg(_cfg)
check("A4 a config without the row falls back to the shipped default",
      SA.default_steps() == int(SA.DEFAULT_CFG["max_steps"]) and SA.default_steps() >= 6,
      SA.default_steps())

# ---- B) a spawn with no max_steps carries the configured value -------------
_cfg = dict(SA.load_cfg())
_cfg.update({"max_steps": 9, "max_parallel": 0, "max_per_run": 0})
SA.save_cfg(_cfg)
_seen = {}
_orig_run = SA.api_v02.agent_run_v2


def _stub_run(goal, max_steps=1, model=None, on_event=None, run_id=None, **_k):
    _seen["max_steps"] = max_steps
    return {"status": "done", "trace": [], "summary": "stub"}


SA.api_v02.agent_run_v2 = _stub_run
try:
    _sp = SA.spawn("v900 probe")
    _entry = SA._running.get(_sp.get("subagent_id")) or {}
    _entry.get("done") and _entry["done"].wait(5)
finally:
    SA.api_v02.agent_run_v2 = _orig_run
check("B1 spawn() without max_steps uses the configured budget",
      _seen.get("max_steps") == 9, _seen.get("max_steps"))
check("B2 and the record shows the same number",
      (_entry or {}).get("max_steps") == 9, (_entry or {}).get("max_steps"))

# ---- C) a Session Job subjob inherits it too --------------------------------
check("C1 _steps(None) resolves through the config",
      SJ._steps(None) == 9, SJ._steps(None))
_created = SJ.create("sess_v900", "v900 job", [{"label": "a", "goal": "look it up"}])
_doc = SJ._load("sess_v900") or {}
_sub = (_doc.get("subjobs") or {}).get("SJ1.1") or {}
check("C2 an SJ subjob without max_steps records the configured budget",
      bool(_created.get("ok")) and _sub.get("max_steps") == 9, _sub.get("max_steps"))
check("C3 an explicit subjob value still wins",
      SJ._steps(3) == 3, SJ._steps(3))

# ---- D) no call path still defaults to a literal 4 -------------------------
_FILES = (("src", "longrun", "agent", "subagent.py"),
          ("src", "longrun", "agent", "agent.py"),
          ("src", "longrun", "agent", "session_jobs.py"),
          ("src", "longrun", "agent", "swarm.py"),
          ("src", "longrun", "core", "api_v02.py"),
          ("src", "longrun", "interop", "mcp.py"),
          ("src", "longrun", "core", "forge.py"))
_offenders = []
for _parts in _FILES:
    for _line in _read(*_parts).splitlines():
        _code = _line.split("#", 1)[0]
        if "max_steps" not in _code:
            continue
        if re.search(r"max_steps\s*[=:,]\s*4\b", _code) or re.search(r"or\s+4\b", _code):
            _offenders.append("%s: %s" % (_parts[-1], _code.strip()))
check("D1 every spawn/HTTP/MCP/CLI call path resolves its default from config",
      not _offenders, _offenders[:3])

# ---- E) the dispatched-teammate budget is coherent -------------------------
_steps = CL.get("chat_tool_steps")
_iters = CL.get("chat_tool_iters")
_rounds = int(KG.cfg()["keepgoing_max"])
check("E1 one chat turn fits a research/verify delegate (>= 10 real tool calls)",
      _steps >= 10, _steps)
check("E2 the iterations backstop never preempts the continuation loop",
      _iters >= _steps * _rounds, (_steps, _iters, _rounds))
check("E3 a delegated child is awaited long enough to finish its steps",
      CL.get("subagent_wait_secs") >= 300, CL.get("subagent_wait_secs"))
check("E4 a plan-only turn keeps its deliberately narrow budget",
      CL.get("plan_tool_steps") < _steps, (CL.get("plan_tool_steps"), _steps))

_bad = results.count(False)
print("\n%d/%d checks passed%s" % (len(results) - _bad, len(results),
                                  "" if not _bad else " — FAILED"))
sys.exit(1 if _bad else 0)
