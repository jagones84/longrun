#!/usr/bin/env python3
"""v1157 — a reply CUT by the repetition guard is not a finished one (round 101).

Measured 2026-11-18: 13 `model.runaway` events in 24 h; each returned the text
accumulated before the loop as a NORMAL reply, so the transcript showed a
truncated answer with nothing saying it had been cut (cluster 05:59–06:20,
deepseek-flash).

The transport now records `finish_reason: "repetition"` when the guard trips, and
the turn: persists the cut as a `model.attempt` card, gives the model ONE round
that continues instead of repeating, and never loops on it.

  A  the cut is announced once and the turn continues
  B  the continuation's answer closes the turn
  C  a second cut is NOT re-nudged (bounded)
  D  the transport records the reason (source pin) and the event is unchanged
  E  round 102: the GUARD itself is driven (A54 r101 item 1) — its false
     positives are measured, so the nudge must state what was measured
  F  round 102: a cut handed back as the reply SAYS it is incomplete in the
     message the operator reads (A54 r101 item 5), and `_rejected_reply_note`
     names a cut instead of asking for "one complete object" (item 2)

Deterministic: fake stream, no model, no network, no server.
Run: python3 tests/acceptance/v1157_repetition_cut.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ["LONGRUN_DATA"] = tempfile.mkdtemp(prefix="sf-1157-")
os.environ["LONGRUN_OPTIMIZER"] = "0"

from longrun.core import server  # noqa: E402  (imported FIRST: breaks the cycle)
from longrun.agent import agent as _agent  # noqa: E402,F401
from longrun.memory import stores as _stores  # noqa: E402
from longrun.model import rllm as _rllm  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


FINAL = "Done: the answer is complete and does not repeat."
CUT = "A" * 60 + " and then the same sentence over and over and over"
# A cut that the turn PERSISTS before the next reply: it is an announcement, so the
# promise branch appends it — this is the earlier-cut case `turn_reply(longest=True)`
# can pick over a shorter answer.
CUTP = "I will now check the file and then report. " * 3


def run_turn(sid, script):
    """`script(n, usage)` returns (text, finish_reason); it fills `usage`."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text, reason = script(state["n"])
        state["n"] += 1
        if usage is not None and reason:
            usage["finish_reason"] = reason
        if text:
            on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = lambda *a, **k: {"status": "executed",
                                                 "result": {"ok": True},
                                                 "observation": "ok"}
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "finish the work",
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


# A/B — one cut, then the model continues and finishes.
_SCRIPT = [(CUT, "repetition"), (FINAL, "stop")]
ev = run_turn("v1157-one", lambda n: _SCRIPT[min(n, len(_SCRIPT) - 1)])
nudges = [d for k, d in ev
          if k == "harness.inject" and d.get("inject_kind") == "retry"
          and "CUT your last message" in (d.get("text") or "")]
check("A1 the cut is announced exactly once", len(nudges) == 1, len(nudges))
check("A2 the nudge names the cut length", "CUT your last message at %d characters"
      % len(CUT.strip()) in (nudges[0].get("text") if nudges else ""), nudges[:1])
check("A3 the cut is persisted as a model.attempt card",
      any(k == "tool.result" and d.get("tool") == "model.attempt"
          and (d.get("args") or {}).get("mode") == "repetition" for k, d in ev))
_sess = server.load_session("v1157-one") or {}
_last = (_sess.get("messages") or [{}])[-1]
check("B1 the continuation's answer closes the turn",
      FINAL[:20] in (_last.get("content") or ""), (_last.get("content") or "")[:60])
check("B2 the turn reports no error", not [d for k, d in ev if k == "chat.error"])
check("B3 a normal answer is NOT marked incomplete",
      "this reply was cut" not in (_last.get("content") or ""))

# C — a second cut is recorded, not re-nudged.
_SCRIPT2 = [(CUT, "repetition"), (CUT, "repetition")]
ev2 = run_turn("v1157-two", lambda n: _SCRIPT2[min(n, len(_SCRIPT2) - 1)])
nudges2 = [d for k, d in ev2
           if k == "harness.inject" and d.get("inject_kind") == "retry"
           and "CUT your last message" in (d.get("text") or "")]
cards2 = [d for k, d in ev2 if k == "tool.result"
          and d.get("tool") == "model.attempt"]
check("C1 a second cut is not re-nudged", len(nudges2) == 1, len(nudges2))
check("C2 both cuts are persisted", len(cards2) >= 2, len(cards2))

# F — the cut that IS handed back says so where the operator reads it.
_sess2 = server.load_session("v1157-two") or {}
_reply = _stores.turn_reply(_sess2.get("messages") or [])
check("F0 ONE owner marks cut text, and text that is not a cut is untouched",
      getattr(_agent, "_cut_mark", None) is not None
      and _agent._cut_mark("plain answer", ["a cut"]) == "plain answer"
      and "incomplete" in _agent._cut_mark("a cut", ["a cut"]))
check("F1 the turn's reply is the cut text", CUT[:20] in _reply, _reply[:60])
check("F2 that reply says it is incomplete",
      "the transport cut this text at %d characters" % len(CUT.strip()) in _reply,
      _reply[-140:])
check("F3 the note is in the PERSISTED message (turn_reply reads it)",
      "the transport cut this text" in ((_sess2.get("messages") or [{}])[-1].get("content") or ""))
_note = _agent._rejected_reply_note(CUT, "repetition")
check("F4 a cut reply is named as a cut, not as bad JSON",
      "CUT on the transport" in _note and "JSON is not valid" not in _note, _note[:160])

# F5/F6 — the two unmarked paths A54's r102 report measured (item 2).
# The model may ECHO the cut text back with a normal stop; and the UI's
# `turn_reply(longest=True)` may pick an EARLIER cut over a shorter answer.
ev3 = run_turn("v1157-echo", lambda n: [(CUT, "repetition"), (CUT, "stop")][min(n, 1)])
_sess3 = server.load_session("v1157-echo") or {}
_reply3 = _stores.turn_reply(_sess3.get("messages") or [])
check("F5 an echoed cut is marked", "the transport cut this text" in _reply3, _reply3[-120:])

ev4 = run_turn("v1157-longest",
               lambda n: [(CUTP, "repetition"), (CUTP, "repetition"),
                          ("ok", "stop")][min(n, 2)])
_sess4 = server.load_session("v1157-longest") or {}
_long = _stores.turn_reply(_sess4.get("messages") or [], longest=True)
check("F6 the EARLIER cut is marked too (longest=1)", "the transport cut this text" in _long,
      _long[-120:])
check("F7 the shorter normal answer is NOT marked",
      "the transport cut this text" not in _stores.turn_reply(_sess4.get("messages") or []))

# D — the transport records the reason (it is what makes A possible).
_src = open(os.path.join(REPO, "src", "longrun", "model", "rllm.py"),
            encoding="utf-8").read()
check("D1 the guard sets finish_reason=repetition",
      'usage["finish_reason"] = "repetition"' in _src)
check("D2 the event keeps its shape",
      'publish("model.runaway", model=model_id, chars=len(rg.text))' in _src)


def guard_trips(text):
    """Feed the REAL guard the way a stream does: one character at a time."""
    g = _rllm._RepetitionGuard()
    for i, ch in enumerate(text):
        if g.feed(ch):
            return i + 1
    return 0


# E — the guard is driven directly (round 102). A54 r101 item 1 measured that it is
# a PERIODICITY test: legitimate repeated structure trips it too. The contract the
# turn depends on is therefore "a trip is a cut", never "the model is defective".
check("E1 a degenerate prose loop trips the guard",
      guard_trips("I will now check the file and then report. " * 8) > 0)
check("E2 repeated table rows ALSO trip it (the false positive is real)",
      guard_trips("| value | alpha | beta | gamma |\n" * 4) > 0)
check("E3 a short code fence with no repetition does not trip",
      guard_trips("```python\nprint(1)\n```\n") == 0)

print()
print("%d/%d OK" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
