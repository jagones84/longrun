#!/usr/bin/env python3
"""v1073 — a done-claim with an UNRESOLVED failure earns one structured round.

Failure-Transparent Agents (arXiv:2609.35732) measures the defect this closes:
a tool fails, the agent reports success anyway. 3,600 annotated responses —
false-success 22.8 % baseline, 9.3 % with a transparency instruction, 0.8 %
with a structured evidence contract; useful responses 74.9 % → 98.8 %.

Longrun's existing closure gate (`agent.py:6625`, `:7014`) fires only when the
LAST call failed (`_last_failed_err and not _last_tool_ok`). The unguarded
quadrant is a failure EARLIER in the turn that a later success of a different
tool hides, closed by a reply that claims the work is done.

Contract:
  F1 that quadrant injects exactly ONE `failure-contract` round
  F2 the round names the tool that failed
  F3 it does not name a tool that succeeded
  F4 a turn with only successful calls gets no contract
  F5 a failure retried to success by the SAME tool gets no contract
  F6 the text asks for a per-entry verdict, never a narration
  F7 both close paths carry the gate, one flag, never a loop

Deterministic: the model and the tool gate are mocked, temp data dirs, no
network, no router, no server.
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1073-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = TMP
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
os.environ["LONGRUN_CHAT_TOOL_STEPS"] = "12"
os.environ["LONGRUN_CHAT_TOOL_ITERS"] = "12"
for d in ("cfg", "sessions", "edits", "runs", "ws"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.agent import agent as A     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SHELL_CALL = '{"action":"tool","tool":"shell","args":{"command":"echo hi"}}'
WRITE_CALL = '{"action":"tool","tool":"fs.write","args":{"path":"r.md","content":"x"}}'
FINISH = '{"action":"finish","summary":"I\'ve written the report and it is done."}'


def run_turn(sid, script):
    state = {"n": 0, "shell": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    def fake_gated(tool, args, **kw):
        if str(tool or "").startswith("shell"):
            state["shell"] += 1
            if script.fail_shell and state["shell"] == 1:
                return {"status": "executed",
                        "observation": "[shell] exit=1 backend=stub\nstderr: boom",
                        "result": {"ok": False, "exit_code": 1, "stdout": "",
                                   "stderr": "boom", "backend": "stub"}}
            return {"status": "executed",
                    "observation": "[shell] exit=0 backend=stub\nstdout: hi",
                    "result": {"ok": True, "exit_code": 0, "stdout": "hi",
                               "stderr": "", "backend": "stub"}}
        return {"status": "executed",
                "observation": "wrote r.md",
                "result": {"ok": True, "exit_code": 0, "stdout": "wrote r.md",
                           "stderr": "", "backend": "stub"}}

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "write the report",
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


def contracts(events):
    return [d for k, d in events
            if k == "harness.inject" and d.get("inject_kind") == "failure-contract"]


# ---- F1/F2/F3: shell fails, fs.write succeeds, the reply claims success ------
def s_hidden(n):
    return {0: SHELL_CALL, 1: WRITE_CALL, 2: FINISH}.get(
        n, "The shell check failed (exit 1); the report was written with fs.write, "
           "so the result stands.")


s_hidden.fail_shell = True
ev = run_turn("v1073-hidden", s_hidden)
_fta = contracts(ev)
check("F1 one failure-contract round", len(_fta) == 1, "n=%d" % len(_fta))
check("F2 it names the tool that failed",
      bool(_fta) and "shell" in (_fta[0].get("text") or ""),
      (_fta[0].get("text") or "")[:160] if _fta else "none")
check("F3 it does not name the tool that succeeded",
      bool(_fta) and "fs.write" not in (_fta[0].get("text") or ""),
      (_fta[0].get("text") or "")[:160] if _fta else "none")

# ---- F4: only successful calls -> no contract --------------------------------
def s_clean(n):
    return {0: WRITE_CALL, 1: FINISH}.get(n, "Done: r.md is written.")


s_clean.fail_shell = False
ev = run_turn("v1073-clean", s_clean)
check("F4 a clean turn gets no contract", not contracts(ev),
      "n=%d" % len(contracts(ev)))

# ---- F5: the SAME tool retried to success -> no contract --------------------
def s_retry(n):
    return {0: SHELL_CALL, 1: SHELL_CALL, 2: FINISH}.get(n, "Done: the check passed.")


s_retry.fail_shell = True
ev = run_turn("v1073-retry", s_retry)
check("F5 a failure retried to success gets no contract", not contracts(ev),
      "n=%d" % len(contracts(ev)))

# ---- F6: the text is a verdict demand, not prose ----------------------------
_t = A._failure_contract_text({"shell.exec": "exit 1: boom"})
check("F6 it asks for one line per entry",
      "FAILURE CONTRACT" in _t and "ONE line per entry" in _t
      and "Do not claim a success" in _t, _t[:200])
check("F6b the error text is carried", "exit 1: boom" in _t)

# ---- F7: both close paths, one flag ----------------------------------------
SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
check("F7a both close paths inject it",
      SRC.count('_inject(_failure_contract_text(_open_failures), "failure-contract")') == 2,
      SRC.count('_inject(_failure_contract_text(_open_failures), "failure-contract")'))
check("F7b the kind is used for nothing else",
      SRC.count('"failure-contract"') == 2, SRC.count('"failure-contract"'))
check("F7c the flag is spent once per turn",
      SRC.count("_fta_used = False") == 1 and SRC.count("_fta_used = True") == 2,
      (SRC.count("_fta_used = False"), SRC.count("_fta_used = True")))
check("F7d the failure map is cleared only by that tool's success",
      "_open_failures.pop(tool, None)" in SRC and "_open_failures.setdefault(tool" in SRC)

print("\n---\nv1073: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
