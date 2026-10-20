#!/usr/bin/env python3
"""v449 — a turn NEVER ends on the model's OWN open todos (JAG-449).

Observed live: the "Master" room finished a turn reporting "audit complete" while
4 of its 6 todo steps were still open, with NO human-in-the-loop card — the user
had nothing to act on. Root cause: the loop's close-todos/HITL enforcement lives
in the keepgoing STOP block, but the loop can also end by exhausting its tool
iteration budget (`while iters < CHAT_TOOL_MAX_ITERS`) or via an early artifact /
term-action acceptance — paths that never reach that block, so `_hitl` stayed unset.

Also fixed here: when a `done` close is REFUSED (e.g. a failed delegation), the
reason was surfaced only in the tool CARD, so the model saw "STILL OPEN" but not
WHY it could not close and then flailed. The reasons now ride the model-facing
nudge.

Deterministic, no model. Run: python3 tests/acceptance/v449_open_todos_gate.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-449-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server          # noqa: E402
from longrun.plan import taskgraph       # noqa: E402
from longrun.agent import agent as A     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ev = []
on_event = lambda kind, **kw: ev.append((kind, kw))  # noqa: E731

SID = "v449"
sess = {"id": SID, "messages": []}
g = taskgraph.ensure(SID, session_id=SID, goal="audit the repo")
NID = taskgraph.add_node(g, "Audit tests, CI, packaging, startup")["id"]
OID = taskgraph.add_node(g, "Run baseline checks")["id"]

# ---- A: a refused close (failed delegation) is returned to the caller --------
taskgraph.record_delegation(taskgraph.load(SID), NID, False, error="subagent failed",
                            subagent_id="sub_x")
ev.clear()
cnt, errs = server._apply_chat_todo_updates(
    sess, {"steps": [{"id": NID, "status": "done", "evidence": "did it myself"}]}, on_event)
check("A1 a refused close reports 0 changes", cnt == 0, cnt)
check("A2 the refusal reason is RETURNED to the caller", bool(errs) and "refusing" in errs[0],
      errs)

# ---- B: the nudge carries the refusal reason (model can retry correctly) -----
nudge = A._nudge_open_todos(sess, errors=errs)
check("B1 the nudge includes the refusal reason", "REFUSED" in nudge and "refusing" in nudge,
      nudge[:200])
check("B2 the nudge still names the open steps", "STILL OPEN" in nudge)
# backward-compat: the old call signature still returns a string
check("B3 _nudge_open_todos still works with no errors arg",
      isinstance(A._nudge_open_todos(sess), str))

# ---- C: a second (corrected) close is accepted and reports no errors ---------
cnt2, errs2 = server._apply_chat_todo_updates(
    sess, {"steps": [{"id": NID, "status": "done", "evidence": "did it myself"}]}, on_event)
check("C1 the one-shot retry is accepted", cnt2 == 1, cnt2)
check("C2 no errors on the accepted retry", errs2 == [], errs2)

# ---- D: static wiring of the turn-end HITL gate ------------------------------
src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D1 the turn-end gate is present (truthful stop reason)",
      '_reason2 = _kg_stop_reason or "open_todos"' in src
      and "reason=_reason2" in src)
check("D2 the gate reuses the open-node scan", "_open2" in src and "OPEN_STATUSES" in src)
check("D3 the gate excludes plan-only turns", "not plan_only" in src)
check("D4 the gate excludes a stale pivot + headless turn",
      "not _user_pivot" in src and "not autonomous" in src)
check("D5 the caller forwards the refusal reasons to the nudge",
      "errors=_errs" in src)

# ---- E: the WebUI no longer prints the non-actionable nudge bubble ----------
idx = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the improve.nudge chat bubble is gone",
      'who("ai", "\U0001F4A1 self-improvement' not in idx)
check("E2 the nudge still refreshes the Improvement panel + toasts",
      "improve.nudge" in idx and "loadImprovement();" in idx
      and "Settings \u25B8 Improvement" in idx)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
