#!/usr/bin/env python3
"""v627 — N9: the compaction overflow is a DURABLE note, not a silent clip.

Two paths shrink the context:
  1. turn-start auto-compaction (`httpapi.prepare_session_for_turn`);
  2. mid-turn trim (`agent._trim_midturn`, JAG-465).
When compaction/trimming CANNOT bring the prompt inside the model window
(a keep_recent window full of huge turns cannot shrink further, or the trim
is capped by the recent-working-set floor), the harness used to answer from a
clipped context with no durable reason. Now both paths leave a
`context_overflow_after_compaction` note in the transcript (P1/N9) — a later
stop cannot hide the overflow, and a resumed run can cite it.

Deterministic: no live server, no network, no model. The httpapi path is
driven with a stubbed context_usage/compact_session; the agent path is a
source-contract check (the trim runs inside the real turn loop).

Run: python3 tests/acceptance/v627_replay_note.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v627-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores            # noqa: E402
from longrun.core import server as _srv      # noqa: E402,F401  (import order)
from longrun.core import httpapi             # noqa: E402
from longrun.model import rllm               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
             encoding="utf-8").read()
HTTPAPI = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
               encoding="utf-8").read()
CCFG = open(os.path.join(REPO, "config", "compaction.yaml"),
            encoding="utf-8").read()

# ---- A. policy + config -------------------------------------------------------
check("A1 compaction.yaml declares overflow_note: true",
      "overflow_note: true" in CCFG)
check("A2 rllm exposes COMPACT_OVERFLOW_NOTE (PEP-562, default True)",
      rllm.COMPACT_OVERFLOW_NOTE is True)

# ---- B. source contracts ------------------------------------------------------
check("B1 turn-start path: prepare_session_for_turn re-checks usage after compaction",
      "_post = context_usage(sess[\"id\"], model=model)" in HTTPAPI)
check("B2 turn-start path: the durable note names context_overflow_after_compaction",
      "context_overflow_after_compaction" in HTTPAPI
      and "context.overflow_after_compact" in HTTPAPI)
check("B3 mid-turn path: _trim_midturn emits the durable note when still over",
      "context_overflow_after_compaction"
      in AGENT.split("def _trim_midturn", 1)[1][:2500])
check("B4 both notes are pure observability (never abort)",
      "must never break a turn" in HTTPAPI.split("context_overflow_after_compaction")[0]
      or "never break a turn" in AGENT)

# ---- C. functional: turn-start overflow note ----------------------------------
sid = "v627-sess"
stores.save_session({"id": sid, "title": "c", "created": time.time(),
                     "messages": [{"role": "user", "content": "hi"},
                                  {"role": "assistant", "content": "ok"}]})
sess = stores.load_session(sid)
caught = []
httpapi.publish = lambda kind, **kw: caught.append(kind)   # capture events
_over = {"available": True, "over_threshold": True, "budget_tokens": 1500,
         "pct": 78, "used": 1170}
httpapi.context_usage = lambda sid_, model=None: dict(_over)   # ALWAYS over
httpapi.compact_session = lambda session, budget_tokens=None, keep_recent=None, \
    origin=None: {"compacted": 2, "input_tokens": 1170, "output_tokens": 400}
out = httpapi.prepare_session_for_turn(sess, model=None)
inj = out.get("injects") or []
check("C1 the overflow note was persisted into the transcript injects",
      any("context_overflow_after_compaction" in str(r.get("text")) for r in inj),
      [str(r.get("text"))[:80] for r in inj])
check("C2 the overflow event was published",
      "context.overflow_after_compact" in caught, caught)

# ---- D. the note is gated by config (off => silent, unchanged behavior) -------
rllm.set_policy_override(overflow_note=False)
caught.clear()
sid2 = "v627-sess-fresh"
stores.save_session({"id": sid2, "title": "c", "created": time.time(),
                     "messages": [{"role": "user", "content": "hi"},
                                  {"role": "assistant", "content": "ok"}]})
sess2 = stores.load_session(sid2)
out2 = httpapi.prepare_session_for_turn(sess2, model=None)
check("D1 with overflow_note: false no note is written (config gate works)",
      not any("context_overflow_after_compaction" in str(r.get("text"))
              for r in (out2.get("injects") or [])))
rllm.clear_policy_override()

# ---- E. the note does not change turn control flow ----------------------------
check("E1 prepare_session_for_turn still returns the session",
      isinstance(out, dict) and out.get("id") == sid, out.get("id"))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
