#!/usr/bin/env python3
"""v729 — a headless caller never parks for a human, and its prompt stays verbatim.

Found by running the JobBench sweep (EV-23d): `statisticians/task2` spent 339 s
building its analysis, stopped with two open plan steps, and the REST reply the
benchmark read was

    "⏸ Paused: 2 open step(s) await your decision (see the HUMAN IN THE LOOP card)"

i.e. a 78-character stub in place of the model's report — so the judge scored a
rubric-weighted ZERO for an arm that HAD worked. The gate is right for an
operator sitting in the WebUI and wrong for a script, a benchmark or another
agent: nobody is attached to answer it.

`autonomous=True` already suppressed the gate, but it ALSO wraps the message in
" AUTONOMOUS GOAL MODE ... GOAL: <message>", which would rewrite the verbatim
upstream instruction a benchmark compares two harnesses on. One flag, two
unrelated questions. `headless` answers only the human question.

Deterministic, no model, no network, isolated state.

Run: python3 tests/acceptance/v729_headless_turn.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v729-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client  # noqa: E402
from longrun.core import server  # noqa: E402,F401  (breaks the agent<->server cycle)
from longrun.agent import agent as A  # noqa: E402
from longrun.plan import keepgoing  # noqa: E402

# never start MCP servers from a test
_offline = mcp_client.MCPClientManager()
_offline.start_all = lambda: None
mcp_client.get_manager = lambda: _offline

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# --- 1. the two questions, separated ---------------------------------------
check("A1 a headless turn does NOT wrap the caller's message",
      A._turn_flags(headless=True) == (False, True), A._turn_flags(headless=True))
check("A2 a headless turn still gets the loop's autonomy (no gate, no dispatch)",
      A._turn_flags(headless=True)[1] is True)
check("A3 the legacy autonomous turn is unchanged (wrapper + autonomy)",
      A._turn_flags(autonomous=True) == (True, True), A._turn_flags(autonomous=True))
check("A4 goal mode always wraps, headless or not",
      A._turn_flags(goal_mode=True) == (True, True)
      and A._turn_flags(goal_mode=True, headless=True) == (True, True))
check("A5 plan-only never wraps and never claims autonomy",
      A._turn_flags(plan_only=True, goal_mode=True) == (False, False),
      A._turn_flags(plan_only=True, goal_mode=True))
check("A6 a plain operator turn is a plain turn",
      A._turn_flags() == (False, False), A._turn_flags())

# --- 2. the pause card cannot fire without a human -------------------------
_open = [{"id": "1", "label": "build the workbook"}, {"id": "2", "label": "write the memo"}]
check("B1 an operator turn with open steps DOES gate (the behaviour was right)",
      keepgoing.hitl_gate("budget", _open, autonomous=False) is True)
check("B2 a headless turn with open steps NEVER gates",
      keepgoing.hitl_gate("budget", _open, autonomous=A._turn_flags(headless=True)[1])
      is False)

# --- 3. the rule reaches the wire ------------------------------------------
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
check("C1 both POST chat doors read the caller's `headless` flag",
      HTTP.count('body.get("headless")') >= 2, HTTP.count('body.get("headless")'))
import re as _re  # noqa: E402
_stream_sig = _re.search(r"def chat_stream_gen\(([^)]*)\)", HTTP, _re.S)
check("C2 the SSE generator carries it into the turn",
      bool(_stream_sig) and "headless" in _stream_sig.group(1)
      and "headless=headless" in HTTP,
      "chat_stream_gen must accept and forward headless")

ADAPTER = open(os.path.join(REPO, "benchmarks", "longrun_adapter.py"),
               encoding="utf-8").read()
check("C3 the benchmark arm declares itself headless, and not as goal mode",
      '"headless": True' in ADAPTER and '"mode": "goal"' not in ADAPTER)

# --- 4. a failed task is re-runnable by NAME -------------------------------
sys.path.insert(0, REPO)
from benchmarks import jobbench_compare as JC  # noqa: E402

_all = [{"id": "statisticians/task1"}, {"id": "statisticians/task2"},
        {"id": "statisticians/task3"}]
check("D1 a re-run targets the task that failed, by name",
      [t["id"] for t in JC.select_tasks(_all, ["task2"])] == ["statisticians/task2"],
      [t["id"] for t in JC.select_tasks(_all, ["task2"])])
check("D2 a full id and a bare suffix mean the same task",
      JC.select_tasks(_all, ["statisticians/task3"])
      == JC.select_tasks(_all, ["task3"]))
check("D3 without a name, `--tasks N` still means the first N",
      [t["id"] for t in JC.select_tasks(_all, [], 2)]
      == ["statisticians/task1", "statisticians/task2"])

print("\n---\nv729: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
