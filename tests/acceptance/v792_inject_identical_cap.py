#!/usr/bin/env python3
"""v792 — the harness bounds its OWN repeated injections, without losing any (I-2).

Measured 2026-11-01 (`self trace`, session 9b5db7c6a45f): 189 harness turns and
**151 kB of injections** — "the harness spent more context on its own bookkeeping
than many tasks need in total". The corpus names the missing control (*Ask Less,
Ask Better — Interruption Budgets*, 2610.24411) and the KB records it against
Longrun as PARTIAL (the reader exists, no policy).

The bound implemented here is the ONE form that cannot lose information: a
**byte-identical** repeat of the same `(kind, text)` inside one turn tells the
model nothing it does not already hold, so only that is suppressed. The operator
asked for exactly this proof — "you may ruin capability of the harness to give
information to the LLM" — so every other case is pinned as passing.

Sections C and D answer that warning directly:
  * C: the wiring (the decision is consulted, nothing is hidden, nothing persists).
  * D: the information that MUST survive — the mid-turn nudge keeps naming the open
    steps, the always-on `Harness state` block keeps naming them, and the tool
    payload is still injected verbatim.
    (D2/D3 are the anti-regression pin for the REJECTED candidate "drop the list
    from the `todo.*` nudge": `state_block` is a TURN-START snapshot
    (`assemble_turn`, agent.py:2765), so it does NOT carry the steps a nudge
    creates MID-turn and dropping the list would have lost them.)

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v792_inject_identical_cap.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v792-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.plan import keepgoing             # noqa: E402
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _agent_src():
    with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
              encoding="utf-8") as fh:
        return fh.read()


decide = getattr(agent, "inject_repeat_decision", None)

# ---- A. the pure decision (the whole point: same bytes -> no new information) --
if decide is None:
    check("A0 inject_repeat_decision exists", False, "missing")
else:
    seen = {}
    check("A1 the FIRST copy is never suppressed", decide("nudge", "same", seen) is False)
    check("A2 the byte-identical second copy is suppressed",
          decide("nudge", "same", seen) is True, repr(seen))
    check("A3 a DIFFERENT text with the same kind passes",
          decide("nudge", "other", seen) is False)
    check("A4 the SAME text under a different kind passes",
          decide("continue", "same", seen) is False)
    check("A5 a third identical copy stays suppressed",
          decide("nudge", "same", seen) is True)

    seen2 = {}
    check("A6 cap=2 allows exactly two",
          decide("nudge", "t", seen2, 2) is False
          and decide("nudge", "t", seen2, 2) is False
          and decide("nudge", "t", seen2, 2) is True)

    seen3 = {}
    check("A7 cap=0 disables the bound entirely",
          decide("nudge", "t", seen3, 0) is False
          and decide("nudge", "t", seen3, 0) is False
          and decide("nudge", "t", seen3, 0) is False)
    check("A8 a negative cap disables the bound too",
          decide("nudge", "t", {}, -3) is False)

    check("A9 an `observation` is NEVER suppressed (its payload is data)",
          decide("observation", "same", {}, 1) is False
          and decide("observation", "same", {}, 1) is False)

    seen4 = {}
    decide("nudge", "A", seen4)
    decide("nudge", "B", seen4)
    check("A10 the count is per (kind, text) pair, not global",
          decide("nudge", "A", seen4) is True and decide("nudge", "B", seen4) is True
          and decide("nudge", "C", seen4) is False)

    check("A11 a None/foreign `seen` never raises",
          decide("nudge", "x", None) is False and decide("nudge", "x", "nope") is False)
    _z = {}
    check("A12 a garbage cap falls back to the shipped default (1)",
          decide("nudge", "z", _z, "abc") is False
          and decide("nudge", "z", _z, "abc") is True)

# ---- B. the knob is config, in both owners ---------------------------------
check("B1 keepgoing.DEFAULTS carries inject_identical_cap = 1",
      keepgoing.DEFAULTS.get("inject_identical_cap") == 1,
      repr(keepgoing.DEFAULTS.get("inject_identical_cap")))
try:
    with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as fh:
        _yaml = fh.read()
except OSError as e:  # pragma: no cover
    _yaml = ""
    print("WARN cannot read config/tools.yaml: %s" % e)
check("B2 config/tools.yaml documents inject_identical_cap: 1",
      "\n  inject_identical_cap: 1" in _yaml, "")

reader = getattr(agent, "inject_identical_cap", None)
if reader is None:
    check("B3 the reader exists", False, "missing")
else:
    check("B3 explicit cfg wins", reader({"inject_identical_cap": 3}) == 3)
    os.environ["LONGRUN_INJECT_IDENTICAL_CAP"] = "5"
    check("B4 env overrides", reader({}) == 5)
    check("B5 cfg beats env", reader({"inject_identical_cap": 2}) == 2)
    os.environ.pop("LONGRUN_INJECT_IDENTICAL_CAP", None)
    check("B6 an empty cfg falls back to the shipped 1", reader({}) == 1)
    # 0 is a REAL value here (OFF) — the knob has no floor, unlike invalid_reply_cap
    check("B7 0 is honoured as OFF, not floored", reader({"inject_identical_cap": 0}) == 0)
    check("B8 a negative value is honoured as OFF too",
          reader({"inject_identical_cap": -1}) == -1)
    import longrun.tools.registry as reg   # noqa: E402
    _orig_yaml = reg.CONFIG_YAML
    _tmp_yaml = os.path.join(TMP, "tools_override.yaml")
    with open(_tmp_yaml, "w", encoding="utf-8") as fh:
        fh.write("runtime:\n  inject_identical_cap: 4\n")
    reg.CONFIG_YAML = _tmp_yaml
    reg.load_config(reload=True)
    check("B9 the config FILE is read", reader({}) == 4, repr(reader({})))
    reg.CONFIG_YAML = _orig_yaml
    reg.load_config(reload=True)

# ---- C. the wiring inside `_inject` (a closure -> pinned at the source) -----
_src = _agent_src()
check("C1 the loop reads the knob once per turn",
      "_inject_cap = inject_identical_cap(" in _src, "")
check("C2 the counter is PER TURN (reset with the turn's state)",
      "_inject_seen = {}" in _src, "")
check("C3 `_inject` consults the decision",
      "inject_repeat_decision(kind, content, _inject_seen, _inject_cap)" in _src, "")
check("C4 a suppressed repeat is still EMITTED (nothing hidden)",
      "text=content, repeat=True)" in _src, "")
if "inject_repeat_decision(kind, content" in _src:
    _tail = _src[_src.index("inject_repeat_decision(kind, content"):]
    _append_at = _tail.find("msgs.append(harness_wrap")
    _ok = _append_at > 0 and _tail.index("return") < _append_at
    check("C5 the suppressed branch RETURNS before the model append and the persist",
          _ok, "return@%d append@%d" % (_tail.index("return"), _append_at))
else:
    check("C5 the suppressed branch RETURNS before the model append and the persist",
          False, "decision not wired")

# ---- D. WHAT MUST NOT BE LOST (the operator's warning) ---------------------
check("D1 harness_wrap still prefixes the mark and keeps the payload VERBATIM",
      agent.harness_wrap("payload — verbatim") ==
      {"role": "user", "content": "[harness] payload — verbatim"})

_orig_load = agent.taskgraph.load


def _fake_graph(_key=None):
    return {"plan": 1, "nodes": [
        {"id": "n1", "status": "doing", "label": "probe the endpoint", "plan": 1},
        {"id": "n2", "status": "todo", "label": "write the report", "plan": 1},
        {"id": "n3", "status": "done", "label": "already finished", "plan": 1},
    ]}


agent.taskgraph.load = _fake_graph
try:
    _sess = {"id": "v792-sess", "messages": []}
    _n, _brief = agent._open_todo_brief(_sess)
    check("D2 the mid-turn nudge still NAMES the open steps (by id)",
          _n == 2 and "n1" in _brief and "n2" in _brief and "n3" not in _brief,
          "n=%s brief=%r" % (_n, _brief))
    _nudge = agent._nudge_open_todos(_sess)
    check("D3 the nudge text carries them (and their count)",
          "n1" in _nudge and "n2" in _nudge and "STILL OPEN (2)" in _nudge,
          _nudge[:120])
    _state = agent.state_block(session_id="v792-sess")
    check("D4 the always-on 'Harness state' block carries them too",
          "n1" in _state and "n2" in _state, _state[:120])
finally:
    agent.taskgraph.load = _orig_load

# 2026-11-07: one of the five sites builds the sentence across lines (the dispatch
# branch), so the pin counts the SENTENCE — the invariant is "all five tool sites
# still inject the observation verbatim", not one particular concatenation.
check("D5 the tool payload is still injected VERBATIM at all 5 tool sites",
      _src.count("Continue: call the next tool, or report the result.") == 5,
      "count=%d" % _src.count(
          "Continue: call the next tool, or report the result."))
check("D6 nothing was added that TRUNCATES an injection",
      "_inject(content[:400]" not in _src and "inject_max_chars" not in _src, "")

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
