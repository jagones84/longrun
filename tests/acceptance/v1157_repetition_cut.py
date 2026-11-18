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

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


FINAL = "Done: the answer is complete and does not repeat."
CUT = "A" * 60 + " and then the same sentence over and over and over"


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
          and "REPEATING" in (d.get("text") or "")]
check("A1 the cut is announced exactly once", len(nudges) == 1, len(nudges))
check("A2 the nudge names the cut length", "CUT at %d characters" % len(CUT)
      in (nudges[0].get("text") if nudges else ""), nudges[:1])
check("A3 the cut is persisted as a model.attempt card",
      any(k == "tool.result" and d.get("tool") == "model.attempt"
          and (d.get("args") or {}).get("mode") == "repetition" for k, d in ev))
_sess = server.load_session("v1157-one") or {}
_last = (_sess.get("messages") or [{}])[-1]
check("B1 the continuation's answer closes the turn",
      FINAL[:20] in (_last.get("content") or ""), (_last.get("content") or "")[:60])
check("B2 the turn reports no error", not [d for k, d in ev if k == "chat.error"])

# C — a second cut is recorded, not re-nudged.
_SCRIPT2 = [(CUT, "repetition"), (CUT, "repetition")]
ev2 = run_turn("v1157-two", lambda n: _SCRIPT2[min(n, len(_SCRIPT2) - 1)])
nudges2 = [d for k, d in ev2
           if k == "harness.inject" and d.get("inject_kind") == "retry"
           and "REPEATING" in (d.get("text") or "")]
cards2 = [d for k, d in ev2 if k == "tool.result"
          and d.get("tool") == "model.attempt"]
check("C1 a second cut is not re-nudged", len(nudges2) == 1, len(nudges2))
check("C2 both cuts are persisted", len(cards2) >= 2, len(cards2))

# D — the transport records the reason (it is what makes A possible).
_src = open(os.path.join(REPO, "src", "longrun", "model", "rllm.py"),
            encoding="utf-8").read()
check("D1 the guard sets finish_reason=repetition",
      'usage["finish_reason"] = "repetition"' in _src)
check("D2 the event keeps its shape",
      'publish("model.runaway", model=model_id, chars=len(rg.text))' in _src)

print()
print("%d/%d OK" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
