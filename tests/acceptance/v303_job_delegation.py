#!/usr/bin/env python3
"""v303 — coordinator delegation: each worker gets ONLY its own assignment (JAG-303).

Observed live on J2: every worker received the WHOLE plan as "Your assignment"
(all four bullets, including the other agents' parts), so the workers had to guess
which slice was theirs and redid each other's work. Locked here:
  * `JobRegistry._assignment_for` returns the single plan line naming the agent;
  * it falls back to the whole plan when the agent is not named, and to "" on empty;
  * the worker message is built from that single line.

Deterministic, no live model. Run: python3 tests/v303_job_delegation.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.orchestrate.jobs import JobRegistry  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

PLAN = ("- A3 (orchestrator): Define scope, assign the four deliverables, coordinate.\n"
        "- A4 (analyst): Identify core use cases, Book fields, validation rules.\n"
        "- A5 (api-designer): Design endpoints, schema, errors, and examples.\n"
        "- A6 (reviewer): Validate REST conventions and completeness.")

a4 = JobRegistry._assignment_for(PLAN, "A4")
check("A4 gets its own line only", a4 == "- A4 (analyst): Identify core use cases, Book fields, validation rules.",
      "got %r" % a4)
check("A4's line does NOT contain another agent's part", "A5" not in a4 and "A6" not in a4)
a5 = JobRegistry._assignment_for(PLAN, "A5")
check("A5 gets its own line only", a5.startswith("- A5 (api-designer)") and "A6" not in a5, "got %r" % a5)
a6 = JobRegistry._assignment_for(PLAN, "A6")
check("A6 gets its own line only", a6.startswith("- A6 (reviewer)"), "got %r" % a6)
check("A3 (the coordinator) also resolves to its line",
      JobRegistry._assignment_for(PLAN, "A3").startswith("- A3 (orchestrator)"))

# when the agent is not named, fall back to the whole plan (never give it nothing)
check("an unnamed agent falls back to the whole plan",
      JobRegistry._assignment_for(PLAN, "A9") == PLAN.strip())
check("an empty plan yields an empty string", JobRegistry._assignment_for("", "A4") == "")
check("a plan with no bullets still returns something",
      JobRegistry._assignment_for("do the thing", "A4") == "do the thing")

# a token match, not a substring one: A4 must not match "A40"
check("matching is token-based (A4 != A40)",
      JobRegistry._assignment_for("- A40 (x): other", "A4") == "- A40 (x): other")

# --- _best_reply: keep the deliverable, drop the trailing harness summary ------
TURN = [
    {"role": "user", "content": "[harness] That was not a valid action."},
    {"role": "assistant", "content": "# Deliverable\n" + ("content " * 60)},
    {"role": "user", "content": "[harness] Answer the user now in plain text."},
    {"role": "assistant", "content": "The design is complete.", "reasoning": "x" * 500},
]
best = JobRegistry._best_reply(TURN)
check("the substantial reply wins over the trailing summary",
      best.startswith("# Deliverable") and "complete" not in best, "got %r" % best[:40])
check("reasoning is ignored (it is a separate field)",
      JobRegistry._best_reply([{"role": "assistant", "content": "hi", "reasoning": "z" * 900}]) == "hi")
check("no assistant message -> empty",
      JobRegistry._best_reply([{"role": "user", "content": "x"}]) == "")
check("an empty turn -> empty", JobRegistry._best_reply([]) == "")

# --- one shared reply extractor: the job path and `dispatch` must not diverge ---
from longrun.memory import stores as _stores
check("the shared turn-reply extractor exists", callable(getattr(_stores, "turn_reply", None)))
check("turn_reply(last) keeps the trailing message",
      _stores.turn_reply(TURN) == "The design is complete.")
check("turn_reply(longest) keeps the deliverable",
      _stores.turn_reply(TURN, longest=True).startswith("# Deliverable"))
check("turn_reply ignores empty/foreign messages",
      _stores.turn_reply([{"role": "user", "content": "x"},
                          {"role": "assistant", "content": "  "},
                          "not-a-dict"]) == "")
check("_best_reply delegates to the shared extractor",
      "stores.turn_reply(messages, longest=True)" in read("src", "longrun", "orchestrate/jobs.py"))
check("the dispatch tool delegates to the shared extractor",
      "_stores.turn_reply(turn)" in read("src", "longrun", "agent/agent.py"))

# --- _close_open_todos: the coordinator's plan is closed after the team ran ----
SID = "v303close"
g = tg.ensure(SID, session_id=SID, goal="x")
tg.add_node(g, "assign A4 to analyse")
tg.add_node(g, "already finished step", status="done", evidence="did it")
closed = JobRegistry._close_open_todos(SID)
nodes = {n["label"]: n["status"] for n in tg.load(SID)["nodes"]}
check("an open step is closed after the team ran", nodes["assign A4 to analyse"] == "done")
check("an already-done step is untouched", nodes["already finished step"] == "done")
check("the close count reports the steps closed", closed == 1, "closed=%d" % closed)
check("no open node remains in the plan",
      all(n["status"] not in tg.OPEN_STATUSES for n in tg.plan_nodes(tg.load(SID))))
check("closing again is a no-op", JobRegistry._close_open_todos(SID) == 0)
check("an unknown session is safe", JobRegistry._close_open_todos("no-such-session") == 0)

# ------------------------------------------------------------- source locks
j = read("src", "longrun", "orchestrate/jobs.py")
check("the assignment extractor exists", "def _assignment_for(plan, aid)" in j)
check("the worker message uses the per-agent line", "self._assignment_for(plan, aid)" in j)
check("the worker is told its part is ONLY its own", "Your assignment (yours only):" in j)
check("the worker is told not to do the others' parts", "NOT do the other agents' parts" in j)
check("the reply extractor exists", "def _best_reply(messages)" in j)
check("_run_agent keeps the turn's substantial reply",
      '_best_reply(s.get("messages", [])[before:])' in j)
check("the turn boundary is captured",
      'before = len((srv.load_session(sid) or {}).get("messages", []))' in j)
check("the open-todo closer exists", "def _close_open_todos(sid)" in j)
check("the coordinator closes its plan before synthesis",
      "self._close_open_todos(sessions[coord])" in j)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

