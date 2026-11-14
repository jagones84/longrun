#!/usr/bin/env python3
"""v980 — reasoning deltas are COALESCED in the agent run loops too (H6).

The chat path has batched per-token chain-of-thought since JAG-265
(`core/sse.py:ThinkCoalescer`, `think_flush_secs`). The two agent RUN loops
forwarded every provider chunk as its own `agent.think` event: one live run
(`run_44ea468b`, 2026-11-14) produced 81,750 such events and an 8.3 MB log.

Contract:
  A) 1,000 per-token deltas inside one flush window become ONE event, and the
     concatenated text is byte-identical to the input (nothing lost);
  B) an answer channel flushes the pending thought FIRST (order preserved);
  C) both run loops call the shared coalescer — no per-token lambda remains.

Deterministic: fake clock, no model, no server, no network.

Run: python3 tests/acceptance/v980_run_think_coalesced.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core.sse import ThinkCoalescer  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- A: one window -> one event, text intact --------------------------------
clock = _Clock()
out = []
tc = ThinkCoalescer(lambda ch, text: out.append((ch, text)), flush_s=0.08,
                    cap=0, clock=clock)
CHUNKS = [("think", "t%d " % i) for i in range(1000)]
for ch, txt in CHUNKS:
    clock.t += 0.001      # ~1 s of streaming: a few flushes, never 1000
    tc.feed(ch, txt)
tc.flush()
check("A1 the 1000 deltas became a handful of events", 2 <= len(out) <= 15, len(out))
check("A2 the whole thought survived, in order",
      "".join(t for _, t in out) == "".join(t for _, t in CHUNKS),
      len("".join(t for _, t in out)))

# --- B: an answer flushes the pending thinking first -----------------------
clock = _Clock()
out = []
tc = ThinkCoalescer(lambda ch, text: out.append((ch, text)), flush_s=0.08,
                    cap=0, clock=clock)
tc.feed("think", "reasoning")
clock.t += 0.01          # inside the window: must NOT flush on its own
tc.feed("answer", "the reply")
check("B1 thinking is emitted before the answer",
      [ch for ch, _ in out] == ["think", "answer"], out)
check("B2 both payloads are intact",
      out[0][1] == "reasoning" and out[1][1] == "the reply", out)

# --- C: both loops use the shared owner -----------------------------------
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as fh:
    _api = fh.read()
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as fh:
    _agent = fh.read()
check("C1 the v2 run loop uses the coalescer",
      "srv.ThinkCoalescer" in _api and "_tc.feed" in _api)
check("C2 the legacy loop uses the coalescer",
      "server.ThinkCoalescer" in _agent and "_tc.feed" in _agent)
check("C3 no per-token agent.think lambda is left in a run loop",
      'lambda ch, t: on_event("agent.think"' not in _api
      and 'lambda ch, t: on_event("agent.think"' not in _agent)

ok = sum(RESULTS)
print("\nv980: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
