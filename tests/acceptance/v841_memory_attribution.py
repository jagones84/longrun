#!/usr/bin/env python3
"""v841 — a memory that keeps helping must outrank one that only shares words.

Source: MEMOIR, arXiv:2611.07631 (2026-11-05): attribute usefulness AFTER use,
and never let retrieval keep favouring a memory that merely resembles the query.
Longrun already measured the first half — `context_engine.usage_signal` (B-6,
v818) says which injected memories the reply repeated, published as `memory.use`
— and nothing consumed it: the retrieval order stayed frozen at write-time
scores.

This pins the closed loop: a bounded weight from the evidence ledger, applied to
the score that actually orders the list, fail-open, and unable to invert a clear
relevance gap.

Deterministic, offline, no model. Run: python3 tests/acceptance/v841_memory_attribution.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
# The ledger path is resolved from DATA_DIR at call time; keep it out of the live
# data dir whatever this test does.
os.environ["LONGRUN_DATA_DIR"] = tempfile.mkdtemp(prefix="v841-data-")

from longrun.memory import attribution as A  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the evidence is recorded, per memory ---------------------------------
A.note(["m-helped", "m-ignored"], ["m-helped"], ts=1000.0)
A.note(["m-helped", "m-ignored"], ["m-helped"], ts=1001.0)
st_h, st_i = A.stats("m-helped"), A.stats("m-ignored")
check("A1 a used memory counts uses and helps",
      st_h.get("uses") == 2 and st_h.get("helped") == 2, st_h)
check("A2 a retrieved-but-unused memory counts the use only",
      st_i.get("uses") == 2 and int(st_i.get("helped") or 0) == 0, st_i)
check("A3 note() with nothing injected records nothing", A.note([], []) is None)
check("A4 an unknown memory has no evidence", A.stats("nope") == {})

# --- B: the weight -----------------------------------------------------------
check("B1 no evidence means no change (exactly 1.0)",
      A.boost("nope") == 1.0, A.boost("nope"))
A.note(["m-once"], ["m-once"])
check("B2 one observation is noise, so no change yet (MIN_USES=2)",
      A.boost("m-once") == 1.0, A.boost("m-once"))
check("B3 a memory that keeps helping is boosted",
      A.boost("m-helped") == A.CEIL, A.boost("m-helped"))
check("B4 a memory that is never used is damped",
      A.boost("m-ignored") == A.FLOOR, A.boost("m-ignored"))

A.note(["m-floor"], ["m-floor"] * 0)
for _ in range(12):
    A.note(["m-floor"], [])
check("B5 the damping is bounded (never below the floor)",
      A.boost("m-floor") == A.FLOOR, A.boost("m-floor"))
for _ in range(12):
    A.note(["m-ceil"], ["m-ceil"])
check("B6 the boost is bounded (never above the ceiling)",
      A.boost("m-ceil") == A.CEIL, A.boost("m-ceil"))

# --- C: the order -----------------------------------------------------------
same = [{"mid": "m-ignored", "score": 0.50}, {"mid": "m-helped", "score": 0.50}]
order = [h["mid"] for h in A.rerank(same)]
check("C1 at equal relevance the memory that helped wins", order[0] == "m-helped", order)
check("C2 the displayed score is the one that ordered the list",
      A.rerank(same)[0]["score"] == 0.575 and A.rerank(same)[0].get("attribution") == 1.15,
      A.rerank(same)[0])

far = [{"mid": "m-helped", "score": 0.30}, {"mid": "m-ignored", "score": 0.90}]
order = [h["mid"] for h in A.rerank(far)]
check("C3 a clearly more relevant memory still wins (bounded weight)", order[0] == "m-ignored",
      order)

rel = [{"mid": "m-ignored", "score": 0.10, "relevance": 0.80},
       {"mid": "m-helped", "score": 0.90, "relevance": 0.60}]
got = A.rerank(rel)
check("C4 the cross-encoder's relevance is what gets weighted",
      got[0]["mid"] == "m-ignored" and got[0]["relevance"] == 0.72,
      [(h["mid"], h.get("relevance")) for h in got])

check("C5 an empty list stays empty", A.rerank([]) == [])

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
