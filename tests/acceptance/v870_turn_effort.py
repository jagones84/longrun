#!/usr/bin/env python3
"""v870 — the scaffolding adapts to the turn, not to the operator's patience.

Problem measured 2026-11-07: a request that fits in one tool call (`out/hello.txt`
containing `ok`) paid 12-15 model calls, and a single-artefact task ran the same
read-back + close verdict + verify gate as a multi-artefact delivery. The gates
were never wrong — they were simply spent where nothing was left to prove.

Two sources fix the shape (arXiv 2610.34491, 2610.35767): start at the LOWEST
effort and escalate only after a VERIFIED failure; a harness that prescribes fewer
model calls is more accurate, and more effort mostly buys more self-verification.

So: `_turn_effort()` decides 'full' or 'lite' from FACTS (never the model's opinion
of its own difficulty), `_review_for_effort()` runs the mechanical gap audit in
'lite' and ESCALATES the whole turn back to 'full' the moment it finds a gap.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v870-")
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
from longrun.agent import agent                # noqa: E402
from longrun.plan import artifacts as ART      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ws = tempfile.mkdtemp(prefix="v870-ws-")
SESS = {"id": "v870-sess", "messages": [], "workspace": ws}

# ---- A. the tier is decided from facts ------------------------------------
check("A1 a one-artefact short request is lite",
      agent._turn_effort(SESS, "Create `out/hello.txt` containing exactly: ok") == "lite")
check("A2 two named artefacts are full",
      agent._turn_effort(SESS, "write `out/a.json` and `out/b.md`") == "full")
check("A3 a long request is full",
      agent._turn_effort(SESS, "please " * 70) == "full")
check("A4 a goal / autonomous / plan-only turn is always full",
      agent._turn_effort(SESS, "ok", goal_mode=True) == "full"
      and agent._turn_effort(SESS, "ok", autonomous=True) == "full"
      and agent._turn_effort(SESS, "ok", plan_only=True) == "full")

_orig_load = agent.taskgraph.load
try:
    agent.taskgraph.load = lambda sid: {"nodes": [
        {"id": "n1", "status": "todo", "label": "a"},
        {"id": "n2", "status": "doing", "label": "b"},
        {"id": "n3", "status": "todo", "label": "c"}]}
    check("A5 three open steps escalate the whole turn to full",
          agent._turn_effort(SESS, "ok") == "full")
    agent.taskgraph.load = lambda sid: {"nodes": [
        {"id": "n1", "status": "todo", "label": "a"},
        {"id": "n2", "status": "done", "label": "b"}]}
    check("A6 one open step does NOT force the full scaffolding",
          agent._turn_effort(SESS, "ok") == "lite")
    def _boom(_sid):
        raise RuntimeError("graph unreadable")
    agent.taskgraph.load = _boom
    check("A7 an unreadable plan fails SCRUPULOUS, not cheap",
          agent._turn_effort(SESS, "ok") == "full")
finally:
    agent.taskgraph.load = _orig_load

# ---- B. lite keeps the MECHANICAL audit and escalates on a gap ------------
with open(os.path.join(ws, "report.csv"), "w", encoding="utf-8") as fh:
    fh.write("id,amount\nA,10\n")

_orig_gaps = ART.gaps
try:
    ART.gaps = lambda *a, **k: []
    _txt, _tier = agent._review_for_effort(SESS, "write a csv", 0.0, {"left": 1}, "lite")
    check("B1 a clean lite turn spends no round on the read-back",
          _txt is None and _tier == "lite", (_txt, _tier))

    ART.gaps = lambda *a, **k: ["report.csv is empty"]
    _txt2, _tier2 = agent._review_for_effort(SESS, "write a csv", 0.0, {"left": 1}, "lite")
    check("B2 a mechanical gap escalates the turn to full AND sends the read-back",
          _tier2 == "full" and bool(_txt2) and "READ-BACK" in str(_txt2), (_tier2, str(_txt2)[:60]))

    def _boom_gaps(*a, **k):
        raise RuntimeError("audit failed")
    ART.gaps = _boom_gaps
    _txt3, _tier3 = agent._review_for_effort(SESS, "write a csv", 0.0, {"left": 1}, "lite")
    check("B3 an audit that cannot run escalates to full rather than skipping",
          _tier3 == "full" and bool(_txt3), (_tier3, str(_txt3)[:40]))
finally:
    ART.gaps = _orig_gaps

_txt4, _tier4 = agent._review_for_effort(SESS, "write a csv", 0.0, {"left": 1}, "full")
check("B4 'full' behaves exactly as before", _tier4 == "full" and "READ-BACK" in str(_txt4))

# ---- C. the gates are wired to the tier on EVERY close path --------------
_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("C1 every read-back call site goes through the tier",
      _SRC.count("_review_for_effort(") >= 4
      and "_drv = _deliverable_review_text(" not in _SRC,
      _SRC.count("_review_for_effort("))
check("C2 the verify gate is tier-gated",
      '_effort == "full" and _review_action_owed(_deliv_state)' in _SRC)
check("C3 every close verdict is tier-gated",
      _SRC.count('_effort == "full" and not _request_verified') == 3,
      _SRC.count('_effort == "full" and not _request_verified'))
check("C4 the citation check stays UNCONDITIONAL (it catches fabrication)",
      "_cite = _citation_gate_text(" in _SRC
      and '_effort == "full" and not _cite' not in _SRC)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
