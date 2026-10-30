#!/usr/bin/env python3
"""v736 — a malformed tool call must TEACH, and a turn may not close on a failure.

EV-41. Live (2026-10-30, session transcript): the model called
`pmcp__gateway.describe` with `{"tool_ids": ["a", "b"]}` — the schema requires
`tool_id` (a string; verified against the live `/api/tools`: NO tool in the
harness has `tool_ids`). The harness answered "missing REQUIRED argument(s)
'tool_id'", which is true and useless: the model HAD passed a similar-looking
key, so it repeated the call and then closed the turn in prose as if the work
were done.

Three mechanisms, none of them task-specific:

  A  an unknown key is NAMED, with the accepted arguments and a did-you-mean
  B  ONE value wrapped in a one-element list is unwrapped (a list of two is not:
     the tool takes one value per call, and the error says so)
  C  a failed call is never offered the "or report the result" ending, and a turn
     that ends right after a failed call faces ONE closure check (plan/plan-less
     alike, bounded like the existing done-gate)

Deterministic and offline: the LLM and the tool gate are mocked (v183 pattern).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v736-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# ---- A: an unknown key is named, with the accepted arguments ----------------
_unknown = T.execute("fs.read", {"paths": ["/tmp/x.txt"]})
_err = str(_unknown.get("error") or "")
check("A1 the usage error names the key the model actually sent",
      _unknown.get("exit_code") == 64 and "unknown argument 'paths'" in _err, _err)
check("A2 it suggests the declared key", "did you mean 'path'" in _err, _err)
check("A3 it lists the ACCEPTED arguments",
      "Accepted arguments:" in _err and "path" in _err and "start_line" in _err, _err)
check("A4 the missing-required fact is still reported",
      "missing REQUIRED argument(s) 'path'" in _err, _err)
check("A5 the shape problems are machine-readable",
      any("paths" in str(x) for x in (_unknown.get("shape_problems") or [])),
      _unknown.get("shape_problems"))

_two = T.execute("fs.read", {"path": ["/tmp/a", "/tmp/b"]})
_err2 = str(_two.get("error") or "")
check("A6 a list of TWO for a scalar says it takes one value per call",
      "'path' must be a string, you sent a list of 2" in _err2
      and "ONE value per call" in _err2, _err2)

_ws = T.execute("fs.read", {"paths": ["/tmp/x.txt"], "workspace": "/tmp"})
_notes = [str(x) for x in (_ws.get("shape_problems") or [])]
check("A7 a key the HARNESS injected is never blamed on the model",
      len(_notes) == 1 and "workspace" not in _notes[0], _notes)

# ---- B: one value in a one-element list is unwrapped ------------------------
check("B1 normalize_args unwraps a single-element list for a scalar",
      T.normalize_args("fs.read", {"path": ["/tmp/x"]}) == {"path": "/tmp/x"})
check("B2 a multi-element list is NOT coerced (schema is the contract)",
      T.normalize_args("fs.read", {"path": ["/tmp/a", "/tmp/b"]})
      == {"path": ["/tmp/a", "/tmp/b"]})
_one = T.execute("fs.read", {"path": ["/tmp/v736-does-not-exist.txt"]})
check("B3 the unwrapped call reaches the tool (no usage error)",
      not _one.get("missing_args") and _one.get("exit_code") != 64,
      (_one.get("error") or "")[:200])

# ---- C: a turn cannot close on a failed call -------------------------------
CALL_BAD = '{"action":"tool","tool":"shell","args":{"command":"false"}}'


def gated_bad():
    err = "tool error: unsupported argument 'tool_ids' (did you mean 'tool_id'?)"
    return {"status": "executed",
            "observation": "[shell] exit=64 ok=False backend=stub sandboxed=False\n"
                           "stderr: " + err,
            "result": {"ok": False, "exit_code": 64, "stdout": "", "stderr": err,
                       "backend": "stub", "missing_args": ["tool_id"]}}


def run_turn(sid, script):
    """Drive chat_once with a scripted model and a failing tool gate."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = lambda tool, args, **kw: gated_bad()
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events, state["n"]


def injects(events):
    return [d.get("text") or "" for k, d in events if k == "harness.inject"]


# C1: a prose answer right after the failure faces the check once
ev, calls = run_turn("v736a", lambda n: CALL_BAD if n == 0 else "ho finito")
_texts = injects(ev)
_failed_checks = [t for t in _texts if "LAST tool call FAILED" in t]
check("C1 the turn asks the failure verdict before accepting prose",
      len(_failed_checks) == 1, _texts[-3:])
check("C2 the verdict carries the harness error, not a generic sentence",
      _failed_checks and "tool_ids" in _failed_checks[0], _failed_checks[:1])
check("C3 it fires ONCE (bounded — no loop)", calls <= 4, calls)
check("C4 the observation of a failed call no longer says 'or report the result'",
      any("FAILED — this is NOT a result" in t for t in _texts),
      [t[:80] for t in _texts if "Observation for tool" in t])
sess = server.load_session("v736a") or {}
_last = (sess.get("messages") or [{}])[-1]
check("C5 the turn still ends with an answer for the user",
      _last.get("role") == "assistant" and _last.get("content"), _last.get("role"))

# C6: an explicit `finish` right after the failure faces the same check once
ev2, calls2 = run_turn(
    "v736b",
    lambda n: CALL_BAD if n == 0 else '{"action":"finish","summary":"done"}')
_texts2 = injects(ev2)
check("C6 an explicit finish after a failed call is challenged once",
      len([t for t in _texts2 if "LAST tool call FAILED" in t]) == 1, _texts2[-2:])
check("C7 the second finish is accepted (the check never regresses into a loop)",
      calls2 <= 4, calls2)

# ---- D: static wiring (the prompt names the contract the model violated) ----
check("D1 the gateway prompt says one tool_id per call",
      "no batch form" in A.PMCP_PROMPT, A.PMCP_PROMPT[:200])
check("D2 the failure note is the only path that says NOT a result",
      "FAILED — this is NOT a result" in open(
          os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
          encoding="utf-8").read())

# ---- E: the XML tag + JSON envelope is the same request, not a lost batch ----
# (the model's own post-mortem named this: "action>batch</action> + JSON … il
# batch non è mai stato eseguito")
_e1 = A._extract_action('<action>tool</action>\n{"tool":"shell.exec","args":{"command":"echo hi"}}')
check("E1 <action>tool</action> + JSON is ONE action", _e1 == {
    "action": "tool", "tool": "shell.exec", "args": {"command": "echo hi"}}, _e1)

_e2 = A._extract_action('<action>batch</action>\n{"calls":[{"tool":"self.info","args":{}}]}')
check("E2 <action>batch</action> + JSON keeps every call",
      _e2 and _e2.get("action") == "batch" and len(_e2.get("calls") or []) == 1, _e2)

_e3 = A._extract_action('<action>finish</action> {"summary":"all done"}')
check("E3 <action>finish</action> + JSON carries the summary",
      _e3 == {"summary": "all done", "action": "finish"}, _e3)

_e4 = A._extract_action('<action>finish</action> {"action":"tool","tool":"shell.exec","args":{}}')
check("E4 a full action object is never re-labelled by a conflicting tag",
      _e4 and _e4.get("action") == "tool", _e4)

print("\n---")
print("v736: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
