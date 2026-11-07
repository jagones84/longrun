#!/usr/bin/env python3
"""v860 — a FORCED close is verified too: the one close that happens outside the
loop was the only one with no verify-class message at all.

Measured 2026-11-07 on the durable event log (3 days, 62 turns): 40 turns wrote
or delegated something, and 12 of them closed without a single `review` /
`closure-check` message. The hole is this path — when the model never produces a
valid action the harness forces a prose answer AFTER the loop, so every gate
inside the loop is unreachable. The verdict is folded into the same model call
(`_inject` only appends to `msgs`), so the fix costs zero extra rounds.

  A) a turn that exhausted its tool budget still gets a `closure-check` whose
     body quotes the operator's ORIGINAL request;
  B) it lands BEFORE the `final` instruction of the forced close, in the same
     model call;
  C) a turn that did NO work never gets it (a verdict with nothing to grade is
     invented work);
  D) the forced-close verdict never offers the `finish` action: the loop is over,
     an envelope would be delivered verbatim as the answer.

Deterministic: the model and the tool gate are mocked, temp data dirs, no
network, no router, no server.
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-860-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(tmp, "ws")
# ONE real tool step per turn: the loop exhausts immediately, which is exactly the
# state that reaches the forced close.
os.environ["LONGRUN_CHAT_TOOL_STEPS"] = "1"
os.environ["LONGRUN_CHAT_TOOL_ITERS"] = "6"
for d in ("cfg", "sessions", "graphs", "edits", "runs", "ws"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.agent import agent as A     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CALL = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'
REQUEST = "build the report from the two sheets and name the totals"


def run_turn(sid, script, message=REQUEST):
    """Drive one real turn with a scripted model. Returns the emitted events."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    def fake_gated(tool, args, **kw):
        return {"status": "executed",
                "observation": "[shell] exit=0 backend=stub sandboxed=False\nstdout: hi",
                "result": {"ok": True, "exit_code": 0, "stdout": "hi", "stderr": "",
                           "backend": "stub"}}

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, message,
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


def kinds_of(events, kind):
    return [d for k, d in events if k == kind]


# ---- A/B: real work, budget exhausted, forced close -------------------------
def script_work_then_answer(n):
    return CALL if n < 2 else "Report written from both sheets: totals 3 and 5."


ev = run_turn("v860-work", script_work_then_answer)
injects = kinds_of(ev, "harness.inject")
cc = [d for d in injects if d.get("inject_kind") == "forced-close-verify"]
fin = [d for d in injects if d.get("inject_kind") == "final"]
check("A0 the turn really did work (a tool ran)",
      len(kinds_of(ev, "tool.call")) >= 1, "tools=%d" % len(kinds_of(ev, "tool.call")))
check("A1 the forced close carries its OWN verdict (not a plain closure-check)", bool(cc),
      "n=%d" % len(cc))
check("A2 the verdict quotes the operator's ORIGINAL request",
      bool(cc) and REQUEST in (cc[0].get("text") or ""),
      (cc[0].get("text") or "")[:120] if cc else "no inject")
check("A3 the forced-final instruction still exists", bool(fin), "n=%d" % len(fin))
if cc and fin:
    order = [d.get("inject_kind") for d in injects]
    check("B1 the verdict lands BEFORE the answer instruction",
          order.index("forced-close-verify") < len(order) - 1 - order[::-1].index("final"),
          order)
    check("B2 both travel in the same model call (one round, no extra latency)",
          order.count("forced-close-verify") == 1 and order[-1] == "final", order[-3:])
else:
    check("B1 the verdict lands BEFORE the answer instruction", False, "missing inject")
    check("B2 both travel in the same model call (one round, no extra latency)", False, "missing inject")

sess = server.load_session("v860-work") or {}
last = (sess.get("messages") or [{}])[-1]
check("A4 the answer is still delivered",
      last.get("role") == "assistant" and "totals" in (last.get("content") or ""),
      "%s: %r" % (last.get("role"), (last.get("content") or "")[:60]))

# ---- C: no work at all -> never invent a verdict ---------------------------
# An IMPERATIVE request: the evidence gate (an information request answered with
# zero tools) is a different gate and must not be confused with this one.
EV = "rename the helper in src/x.py"
ev0 = run_turn("v860-nowork", lambda n: "Renamed it.", message=EV)
cc0 = [d for d in kinds_of(ev0, "harness.inject")
       if "This turn did real work" in (d.get("text") or "")]
check("C1 a turn with zero work gets no forced-close verdict", not cc0,
      "n=%d" % len(cc0))

# ---- D: the forced-close wording ------------------------------------------
txt = A._forced_close_verify_text(REQUEST)
check("D1 the helper names the request", REQUEST in txt, txt[:80])
check("D2 an empty request yields no message at all", A._forced_close_verify_text("") == "")
check("D3 it never offers the finish action (the loop is over)",
      '"finish"' not in txt and "action" not in txt, txt[-90:])
check("D4 it asks for prose, which is what the forced close accepts",
      "plain prose" in txt)

src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D5 the guard requires real work, an unverified turn and no abort",
      "_total_work_steps and not _request_verified" in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
