#!/usr/bin/env python3
"""v861 — the three leftovers from the arXiv alignment check, pinned.

The operator, after the mapping: "fix tutto quello che non va bene per cortesia".
Three mechanisms were missing or misaligned; this test is their contract.

  A) `verifier.closeout` has THREE states and a safe default: `"auto"` runs the
     check when a command resolves and lets the step close UNVERIFIED when none
     does — `true` keeps the old fail-closed refusal, `false` is off;
  B) a step that edited the TEST SETUP is `tainted`: its own suite cannot prove
     it, so it never counts as green (the held-out gap SpecBench measures);
  C) the closure verdict CARRIES the read-back's concrete findings, so the check
     names the defect instead of asking the producer for an opinion;
  D) each gated turn publishes ONE `harness.gates` event and the panel's
     aggregation (`cycle.gate_stats`) reports what each gate is worth.

Deterministic: temp dirs, mocked model/tool gate, no network, no router.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-861-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(tmp, "ws")
os.environ["LONGRUN_CHAT_TOOL_STEPS"] = "1"
os.environ["LONGRUN_CHAT_TOOL_ITERS"] = "6"
for d in ("cfg", "sessions", "graphs", "edits", "runs", "ws"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.agent import agent as A     # noqa: E402
from longrun.plan import verify as V     # noqa: E402
from longrun.harness import cycle as HC  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def green(workspace=None, c=None, run_id=None):
    return True, "ok"


# ------------------------------------------------ A: the three closeout states
V.reset_closeout_memo()
check("A1 closeout defaults to 'auto' (never a silent off, never a trap)",
      V.DEFAULTS.get("closeout") == "auto", V.DEFAULTS.get("closeout"))

node = {"id": "n1", "mutated": 11, "paths": ["src/app.py"]}
ok, rep, obs = V.closeout_gate(node, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": "auto", "command": ""}, check=green)
check("A2 auto with no command closes UNVERIFIED, never blocks",
      ok is True and rep.get("unavailable") is True and obs is False and rep.get("ran") is False,
      rep)

ok, rep, obs = V.closeout_gate(node, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": True, "command": ""}, check=green)
check("A3 strict keeps the old fail-closed refusal",
      ok is False and rep.get("ran") is False and "command" in str(rep.get("error")), rep)

ok, rep, obs = V.closeout_gate(node, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": "auto", "command": "true"}, check=green)
check("A4 auto runs the check when a command resolves",
      ok is True and obs is True and rep.get("green") is True, rep)

ok, rep, obs = V.closeout_gate(node, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": False, "command": "true"}, check=green)
check("A5 off stays off", ok is True and rep.get("ran") is False and obs is False, rep)

# a check that burns its whole budget proves nothing: auto says UNVERIFIED,
# strict keeps the red (there the operator asked for a verdict).
_slow = lambda **k: (False, "still running")  # noqa: E731
V.reset_closeout_memo()
ok, rep, obs = V.closeout_gate({"id": "n4", "mutated": 5, "paths": ["src/a.py"]},
                               workspace=os.path.join(tmp, "bare"),
                               c={"closeout": "auto", "command": "true",
                                  "timeout_secs": 0.001}, check=_slow)
check("A6 auto treats a budget-exhausted check as UNVERIFIED, not a permanent red",
      ok is True and obs is False and rep.get("unavailable") is True, rep)
V.reset_closeout_memo()
ok, rep, obs = V.closeout_gate({"id": "n5", "mutated": 6, "paths": ["src/a.py"]},
                               workspace=os.path.join(tmp, "bare"),
                               c={"closeout": True, "command": "true",
                                  "timeout_secs": 0.001}, check=_slow)
check("A7 strict keeps the red even when the check ran out of budget",
      ok is False and obs is False, rep)

# ------------------------------------------------------- B: the held-out guard
V.reset_closeout_memo()
tests_node = {"id": "n2", "mutated": 3, "paths": ["tests/test_app.py", "src/app.py"]}
ok, rep, obs = V.closeout_gate(tests_node, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": "auto", "command": "true"}, check=green)
check("B1 a step that edited the tests is tainted, never 'green'",
      ok is True and obs is False and rep.get("tainted") is True
      and "tests/test_app.py" in (rep.get("paths") or []), rep)
check("B2 tainting does not block the close (it reports, it does not refuse)", ok is True)

plain = {"id": "n3", "mutated": 4, "paths": ["src/app.py", "docs/readme.md"]}
ok, rep, obs = V.closeout_gate(plain, workspace=os.path.join(tmp, "bare"),
                               c={"closeout": "auto", "command": "true"}, check=green)
check("B3 a step that touched only source is verified normally",
      ok is True and obs is True and not rep.get("tainted"), rep)

# --------------------------------------------- C: the verdict carries findings
gap = "gap: output/report.csv has 3 rows, the request asked for 40"
v = A._closure_check_prompt("build the report", known=gap)
check("C1 the verdict names the operator's request", "build the report" in v)
check("C2 the verdict carries the harness's own finding", gap in v, v[-160:])
check("C3 the finding is appended once, never twice",
      A._with_known_gaps(v, gap).count(gap) == 1)
check("C4 no finding -> the verdict is unchanged",
      "THE HARNESS ALREADY CHECKED" not in A._closure_check_prompt("build the report"))
check("C5 the forced-close verdict carries it too",
      gap in A._forced_close_verify_text("build the report", known=gap))
check("C6 the finding never replaces the instruction to answer in prose",
      "plain prose" in A._forced_close_verify_text("build the report", known=gap))

# --------------------------------------------------------- D: the measurement
CALL = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'


def run_turn(sid, script):
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
    server.chat_once({"id": sid, "messages": [], "workspace": ""},
                     "build the report from the two sheets", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


ev = run_turn("v861-turn", lambda n: ['{"action":"nope"}', CALL, "Report written."][min(n, 2)])
gated = [d for k, d in ev if k == "harness.gates"]
check("D1 one harness.gates event per gated turn", len(gated) == 1, len(gated))
fired = (gated[0].get("fired") if gated else []) or []
check("D2 it lists the gates that fired with their outcome",
      bool(fired) and all("kind" in f and "work_after" in f for f in fired), fired[:3])
check("D3 a gate that was followed by real work is marked work_after=true",
      any(f.get("work_after") for f in fired), fired[:3])

# the aggregation the panel reads (fed with the same shape the turn emits)
from longrun.core import events as EV  # noqa: E402
EV.publish("harness.gates", session="v861-stats",
           work_steps=2,
           fired=[{"kind": "closure-check", "work_after": True},
                  {"kind": "review", "work_after": False}])
st = HC.gate_stats(days=1)
by = {k["kind"]: k for k in st["kinds"]}
check("D4 gate_stats counts firings", by.get("closure-check", {}).get("fired", 0) >= 1, st)
check("D5 gate_stats counts the ones that changed the work",
      by.get("closure-check", {}).get("changed", 0) >= 1, by.get("closure-check"))
check("D6 the payload is JSON-serialisable (the panel renders it, no stub)",
      isinstance(json.dumps(st), str) and isinstance(st.get("kinds"), list))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
