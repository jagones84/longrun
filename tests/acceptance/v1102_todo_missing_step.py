#!/usr/bin/env python3
"""v1102 — a missing step names the steps that exist.

Round 33, measured 2026-11-18 over the live store: `todo.update` answered
`step 'n1' not found` in 2 cards / 2 sessions and neither recovered; one of them was
the FIRST card of its session, i.e. the model addressed `n1` before any plan
existed. The observation renders the whole list, but the refusal line itself said
nothing, so the retry guessed again. Same rule as the argument contract (round
30): the refusal names what is REAL.

  A  an unknown id over a live plan names the OPEN ids (and not the closed ones)
  B  no plan at all names the writer to use instead
  C  a valid id is not touched (no false refusal)
  D  no open step falls back to every id
  E  more than six ids are capped, with the remainder counted
  F  the surface: the tool card carries the hint too

Deterministic: temp graph dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1102_todo_missing_step.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1102-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402
from longrun.plan import taskgraph as TG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def run(sid, steps):
    sess = {"id": sid, "title": sid, "messages": []}
    ev = []
    _n, errs = S._apply_chat_todo_updates(sess, {"steps": steps},
                                          lambda kind, **d: ev.append((kind, d)))
    return errs, ev


# ------------------------------------------------- A: unknown id, live plan ---
g = TG.ensure("s1", session_id="s1")
TG.add_node(g, "read the schema")
TG.add_node(g, "fix the call")
TG.add_node(g, "close the issue")
TG.update_node(TG.load("s1"), "n3", status="superseded", reason="dropped")
errs, ev = run("s1", [{"id": "n9", "status": "doing"}])
msg = errs[0] if errs else ""
check("A1 the refusal still says 'not found'", "not found" in msg, msg)
check("A2 and names the OPEN ids",
      "the open steps are n1, n2" in msg, msg)
check("A3 a CLOSED id is not offered", "n3" not in msg.split("the open steps")[-1], msg)
check("A4 it keeps the index fallback",
      "`index` for the position in the OPEN list" in msg, msg)

# ------------------------------------------------------ B: no plan at all ----
errs, ev = run("s2", [{"id": "n1", "status": "doing"}])
msg = errs[0] if errs else ""
check("B1 an empty plan is named as such",
      "no plan yet" in msg, msg)
check("B2 and names the writer that creates the steps",
      '"action":"todo.write"' in msg and '"todos"' in msg, msg)
check("B3 and does not offer ids that do not exist",
      "the open steps are" not in msg and "the steps are" not in msg, msg)

# ------------------------------------------------------ C: a valid id works --
errs, ev = run("s1", [{"id": "n1", "status": "doing"}])
check("C1 a valid id updates with no error", errs == [], errs)
check("C2 and the step really moved",
      (TG.find(TG.load("s1"), node_id="n1") or {}).get("status") == "doing",
      TG.find(TG.load("s1"), node_id="n1"))

# ------------------------------------------------ D: no open step left --------
g3 = TG.ensure("s3", session_id="s3")
TG.add_node(g3, "only one")
TG.update_node(TG.load("s3"), "n1", status="done", evidence="done in the test")
errs, ev = run("s3", [{"id": "n7", "status": "doing"}])
msg = errs[0] if errs else ""
check("D1 with nothing open every id is offered",
      "the steps are n1" in msg and "the open steps are" not in msg, msg)

# ------------------------------------------------------------ E: the cap -----
g4 = TG.ensure("s4", session_id="s4")
for i in range(8):
    TG.add_node(g4, "step %d" % i)
errs, ev = run("s4", [{"id": "n99", "status": "doing"}])
msg = errs[0] if errs else ""
check("E1 six ids are shown and the rest are counted",
      "n1, n2, n3, n4, n5, n6 +2 more" in msg
      and "n7" not in msg and "n8" not in msg, msg)

# ------------------------------------------------------------ F: the card ----
outs = [d.get("output", "") for k, d in ev if k == "tool.result"]
check("F1 the tool card carries the hint (the model reads the observation)",
      bool(outs) and "the open steps are n1, n2, n3, n4, n5, n6" in outs[0],
      outs[0][:300] if outs else "")

print("\n---\nv1102: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
