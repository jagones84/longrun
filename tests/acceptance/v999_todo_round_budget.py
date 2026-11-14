#!/usr/bin/env python3
"""v999 — a round the harness REJECTED is not charged to the work budget (JAG-402).

Measured live on session `b7329cccf94c` (2026-11-14 13:21:45-13:26:00 CET, run
`bdb5d6e5fff5`): the agent wrote an 8-step plan, worked it (22 tool calls, CH1
fully probed) and stopped after 253.9 s with

    plan.stopped {"reason": "budget", "open": 5, "total": 8, "rounds": 10}

publishing, as the turn's reply, the message it was in the middle of writing
("Triggering a recall — …"). Of the 10 continuation rounds it was charged, 4 were
rounds in which the harness itself REJECTED the model's final answer:

    "STOP — your final answer was REJECTED because your TASK LIST still has 8 open step(s)"

That forcing has its OWN dedicated budget (`_close_todo_max`), and keepgoing.py's
JAG-402 note says it overrides the normal stop reasons "up to a small dedicated
budget". Charging those rounds to `_kg_rounds` as well bounds one behaviour twice:
the WORK budget is spent on the anti-stop policy, so the plan dies unfinished.

Deterministic: scripted model, isolated state, no network, no server, no model.

Run: python3 tests/acceptance/v999_todo_round_budget.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v999-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
registry._external_tools = lambda: {}             # noqa: E731
from longrun.core import server                   # noqa: E402
from longrun.agent import agent as A              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# The budget is the only number under test: the shipped config with keepgoing_max
# pinned, difficulty scaling off (JAG-134 would multiply it) and no best-of-N, so
# every count is exact. The rest of the tree's config stays live (the tools list
# included — without it a turn has no tool context and never reaches the loop).
def scoped(keepgoing_max):
    base = registry.load_config()
    cfg = dict(base)
    cfg["runtime"] = dict(base.get("runtime") or {}, keepgoing_max=keepgoing_max)
    cfg["difficulty"] = dict(base.get("difficulty") or {}, enabled=False)
    cfg["bestofn"] = dict(base.get("bestofn") or {}, n=1)
    return cfg

PLAN = ('{"action":"write_todos","todos":[{"label":"step one"},'
        '{"label":"step two"},{"label":"step three"}]}')
# Plain prose that no other gate owns (`_narrates_intent`, `_claims_action`,
# `_looks_like_promise`, the evidence gate all stay silent): the ONLY thing the
# loop can do with it is the open-todos decision under test.
WAIT = "Attendo un tuo segnale prima di procedere."


def run_turn(sid, script, keepgoing_max):
    """Drive one full turn with a scripted model. Returns the event list."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    def fake_gated(tool, args, **kw):
        return {"status": "executed", "observation": "[stub] ok",
                "result": {"ok": True, "exit_code": 0, "stdout": "", "stderr": "",
                           "backend": "stub"}}

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    with registry.scoped_config(scoped(keepgoing_max)):
        server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go",
                         model="mock", on_delta=lambda c, t: None,
                         on_event=lambda kind, **d: events.append((kind, d)))
    return events


WORK = '{"action":"tool","tool":"shell","args":{"command":"echo work"}}'


def script(n):
    """A model that WORKS and then announces: one tool call, then a prose answer
    that leaves the list open (the live pattern — 22 tool calls around the
    rejected answers, so the rounds are never `no_progress`)."""
    if n == 0:
        return PLAN
    return WORK if n % 2 else WAIT


def texts(events, needle):
    return [d.get("text") or "" for k, d in events
            if k == "harness.inject" and needle in (d.get("text") or "")]


# ---- the close-todos forcing keeps its own budget --------------------------
ev = run_turn("v999a", script, keepgoing_max=2)
rejected = texts(ev, "final answer was REJECTED")
check("A1 the rejected-answer forcing still fires (its own budget is untouched)",
      len(rejected) == 4, "rejected=%d (the dedicated budget is 4)" % len(rejected))

# ---- the rejections do NOT consume the work budget ------------------------
continued = texts(ev, "CONTINUE — your TASK LIST still has")
check("B1 the work budget survives the rejections (it still grants rounds)",
      len(continued) >= 2,
      "generic_continues=%d (expected >= keepgoing_max=2)" % len(continued))

stopped = [d for k, d in ev if k == "plan.stopped"]
check("B2 the turn still ends with a typed stop", bool(stopped), stopped)
if stopped:
    rounds = stopped[-1].get("rounds")
    check("B3 the stop reports the HONEST continuation count, not the charged one",
          isinstance(rounds, int) and rounds >= len(rejected) + 2,
          "rounds=%s rejected=%d" % (rounds, len(rejected)))

# ---- the budget itself is still a budget ---------------------------------
ev2 = run_turn("v999b", script, keepgoing_max=1)
stopped2 = [d for k, d in ev2 if k == "plan.stopped"]
check("C1 a smaller budget still stops the turn (no unbounded loop)",
      bool(stopped2) and stopped2[-1].get("reason") == "budget", stopped2)
c1 = len(texts(ev2, "CONTINUE — your TASK LIST still has"))
check("C2 the extra rounds scale with the configured budget", c1 < len(continued),
      "kg1=%d kg2=%d" % (c1, len(continued)))

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
