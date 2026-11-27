#!/usr/bin/env python3
"""v1319 — a `<json>`-wrapped call RUNS, and the verifier grades THIS turn.

Two harness defects met in session `architect` (2026-11-27) and produced a reply
that made no sense to the operator:

  * the model emitted its action as
    `<json>\n{"action":"tool","tool":"shell.exec",…}\n</json>`.
    `tail_json_spans` only accepted whitespace / ``` fence / punctuation after a
    JSON value, so the `</json>` footer hid the call: `extract_action_json`
    returned None, three `todo.update` calls were swallowed (the harness kept
    rejecting the final answer because the steps were still open), and the raw
    envelope was streamed/persisted as the turn's final chat message (`chat.final`
    text `<json>{"action":"tool",…}</json>`).

  * `_request_thread` scanned the WHOLE session, so the turn that asked about
    reasoning effort was graded against the FIRST request of the session
    ("Shutoff windows pc and put dgx monitor stby"). The independent verifier
    bounced the correct answer with "never addresses the user's original
    request…", and the agent went back to redo the old task.

  A  a JSON value followed by `</json>` is still the message's action;
  B  a call inside inline backticks stays prose (the v1247 guard is intact);
  C  the request thread starts after the last COMPLETED turn, while consecutive
     user messages with no answer between them stay one refinement thread;
  D  end-to-end: the `<json>`-wrapped call executes and the stored reply is the
     model's prose, never the raw envelope.

Deterministic: no model, no network. Run:
    python3 tests/acceptance/v1319_json_tagged_action_and_turn_thread.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1319-")
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

from longrun.core import server          # noqa: E402
from longrun.agent import agent as A     # noqa: E402
from longrun.util import textkit as TK   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The exact shape stored as the last assistant message of session `architect`.
WRAPPED = (
    '<json>\n'
    '{"action":"tool","tool":"shell.exec","args":{"command":"echo hi"}}\n'
    '</json>'
)

# ── A · the `<json>` footer is part of the message's conclusion ─────────────
check("A1 extract_action_json reads the call behind </json>",
      (TK.extract_action_json(WRAPPED) or {}).get("tool") == "shell.exec",
      TK.extract_action_json(WRAPPED))
check("A2 the agent extracts it as an ACTION (so the call RUNS)",
      (A._extract_action(WRAPPED) or {}).get("tool") == "shell.exec",
      A._extract_action(WRAPPED))
check("A3 _looks_like_json_action treats the wrapper as machine text",
      A._looks_like_json_action(WRAPPED) is True)
check("A4 a call with prose before the wrapper is still an action",
      (TK.extract_action_json("Vado avanti.\n" + WRAPPED) or {}).get("tool")
      == "shell.exec",
      TK.extract_action_json("Vado avanti.\n" + WRAPPED))

# ── B · prose that merely MENTIONS the envelope is not a call ───────────────
check("B1 a call inside inline backticks stays prose",
      A._looks_like_json_action(
          'The model writes `<json>{"tool":"fs.read"}</json>` as its envelope.')
      is False)
check("B2 a normal prose answer stays prose",
      A._looks_like_json_action("Done. The command ran and the test passes.")
      is False)

# ── C · the request thread is THIS turn's task ─────────────────────────────
SESS = {"id": "v1319", "messages": [
    {"role": "user", "content": "Shutoff windows pc and put dgx monitor stby"},
    {"role": "assistant", "content": "Done — both done.", "ts": 1.0},
    {"role": "user", "content": "Shutdown again windows pc only"},
    {"role": "assistant", "content": "Windows PC shut down again.", "ts": 2.0},
    {"role": "user", "content": "Whats your think effort?"},
    {"role": "assistant", "content": "medium", "ts": 3.0},
    {"role": "user", "content": "Is that value actually applied?"},
]}
CUR = "Is that value actually applied?"
thread = A._request_thread(SESS, CUR)
check("C1 an earlier, answered task is NOT this turn's request",
      "Shutoff" not in thread and "Shutdown again" not in thread, thread)
check("C2 the current message is the thread", thread == CUR, thread)

REFINE = {"id": "v1319b", "messages": [
    {"role": "user", "content": "build the report from the two sheets"},
    {"role": "assistant", "content": "working"},          # no `ts`: still in-turn
    {"role": "user", "content": "[harness] closure check (harness — do not skip)"},
    {"role": "user", "content": "and make it one page"},
]}
rthread = A._request_thread(REFINE, "and make it one page")
check("C3 consecutive user messages remain ONE refinement thread",
      "build the report" in rthread and "one page" in rthread, rthread)
check("C4 a harness injection is never quoted as a request",
      "[harness]" not in rthread, rthread)

# ── D · end-to-end: the wrapped call executes; prose is what is stored ─────
SID = "v1319turn"


def run_turn(script):
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = lambda tool, args, **kw: {
        "status": "executed", "observation": "", "result": {}}
    A._turn_verify_bounce = lambda *a, **k: None   # no second model in a unit test
    server.chat_once({"id": SID, "messages": [], "workspace": ""}, "go",
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


SCRIPT = [WRAPPED, "Done — the command ran."]
ev = run_turn(lambda n: SCRIPT[n] if n < len(SCRIPT) else SCRIPT[-1])
calls = [d for k, d in ev if k == "tool.call" and d.get("tool") == "shell.exec"]
check("D1 the wrapped call is EXECUTED (not dropped as prose)", len(calls) == 1,
      calls)
sess = server.load_session(SID) or {}
finals = [m for m in (sess.get("messages") or [])
          if m.get("role") == "assistant" and not m.get("internal")]
last = (finals[-1].get("content") or "") if finals else ""
check("D2 the stored reply is the model's prose",
      "Done — the command ran." in last, last[:200])
check("D3 the raw envelope never reaches the user",
      "<json>" not in last and '"action"' not in last, last[:200])

print("\n---")
print("v1319: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
