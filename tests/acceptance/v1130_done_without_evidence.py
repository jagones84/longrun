#!/usr/bin/env python3
"""v1130 — a step marked DONE with no tool call is a claim, not an open plan item.

Round 64, from arXiv:2611.21407 ("Harness Leverage Across Model Size"): of 357
graded cells, 127 left none of their declared artifacts and 85 of those exited
normally — "a scorer that reads exit status credits work that was never written".
Longrun's own store shows the same shape: measured 2026-11-18, 528 of 912 planned
nodes are marked done with ZERO tool calls, and the tree called all of them
"planned but never executed" — the same words for a turn that had not started and
a turn that had declared it finished.

`runtree.build` now keeps the two apart: `claimed` (status done/completed, no
call) and `open` (no call, not done), with `counts.claimed` and one `claim_note`
line. Nothing is judged — the turn may legitimately have reported rather than
acted; the harness only stops calling a claim "not started".

  A  a done node with no call is `claimed`, a todo node with no call is `open`
  B  a done node WITH a call is a normal stage (never a claim)
  C  a failed call under a done node is a failure, not a claim
  D  a session with no plan claims nothing and says nothing
  E  every planned node lands in exactly one of stage/claimed/open (no loss)
  F  the note counts what it names

Deterministic: the tree is built from synthetic cards and graphs; no store, no
model, no network.
Run: python3 tests/acceptance/v1130_done_without_evidence.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1130-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import runtree as RT  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def card(tool="fs.read", ok=True, node=None, after=1, **kw):
    c = {"tool": tool, "ok": ok, "node": node, "after": after,
         "result": "", "error": "", "exit_code": 0}
    c.update(kw)
    return c


# --- A: the two facts are kept apart -----------------------------------------
graph = {"nodes": [{"id": "n1", "label": "did work", "status": "done"},
                   {"id": "n2", "label": "said done, called nothing", "status": "done"},
                   {"id": "n3", "label": "never started", "status": "todo"}]}
t = RT.build({"id": "sA", "tool_cards": [card(node="n1", after=2)]}, graph)
check("A1 the done-with-no-call node is a claim",
      [s["id"] for s in t["claimed"]] == ["n2"], t["claimed"])
check("A2 the not-started node is open",
      [s["id"] for s in t["open"]] == ["n3"], t["open"])
check("A3 the counts carry both", t["counts"]["claimed"] == 1 and t["counts"]["open"] == 1,
      t["counts"])
check("A4 the worked node is a normal stage", [s["id"] for s in t["stages"]] == ["n1"],
      [s["id"] for s in t["stages"]])

# --- B: a done node with a call is never a claim ------------------------------
t2 = RT.build({"id": "sB", "tool_cards": [card(node="n1", after=1)]},
              {"nodes": [{"id": "n1", "label": "done with work", "status": "done"}]})
check("B1 a done node with a call is a stage", [s["id"] for s in t2["stages"]] == ["n1"],
      t2["stages"])
check("B2 and is not claimed", t2["claimed"] == [] and t2["counts"]["claimed"] == 0,
      t2["claimed"])

# --- C: a FAILED call is a failure, not a claim ------------------------------
t3 = RT.build({"id": "sC", "tool_cards": [
    card(tool="shell.exec", ok=False, error="boom", exit_code=1, node="n1", after=1)]},
    {"nodes": [{"id": "n1", "label": "tried", "status": "done"}]})
check("C1 the failed call is a stage with a failure",
      t3["stages"] and t3["counts"]["failed"] == 1, t3["counts"])
check("C2 it is not claimed", t3["claimed"] == [], t3["claimed"])
check("C3 the onset names it", (t3["onset"] or {}).get("tool") == "shell.exec", t3["onset"])

# --- D: no plan, no claim ----------------------------------------------------
t4 = RT.build({"id": "sD", "tool_cards": [card(after=1)]})
check("D1 an unplanned session claims nothing", t4["claimed"] == [], t4["claimed"])
check("D2 and says nothing about claims", t4["claim_note"] == "", t4["claim_note"])

# --- E: nothing is lost ------------------------------------------------------
nodes = (graph["nodes"]
         + [{"id": "n4", "label": "completed", "status": "completed"},
            {"id": "n5", "label": "done", "status": "done"}])
t5 = RT.build({"id": "sE", "tool_cards": [card(node="n1", after=1),
                                          card(node="n5", after=2)]}, {"nodes": nodes})
seen = ([s["id"] for s in t5["stages"]] + [s["id"] for s in t5["claimed"]]
        + [s["id"] for s in t5["open"]])
check("E1 every planned node lands in exactly one list",
      sorted(seen) == sorted(n["id"] for n in nodes) and len(seen) == len(nodes), seen)
check("E2 'completed' is a done status too", [s["id"] for s in t5["claimed"]] == ["n2", "n4"],
      t5["claimed"])

# --- F: the note counts what it names ---------------------------------------
n = t5["counts"]["claimed"]
check("F1 the note states the count", ("%d step(s)" % n) in t5["claim_note"], t5["claim_note"])
check("F2 and what is missing", "nothing on disk proves them" in t5["claim_note"],
      t5["claim_note"])

print("\n---\nv1130: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
