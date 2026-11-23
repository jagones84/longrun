#!/usr/bin/env python3
"""v1286 — mining/scanning improvements: recency tiebreak (I-1) and near-dup merge (I-2).

Bug-hunt/RSI pass 2026-11-23.

I-1: `mine()` ranked a habit seen 3x last year exactly like one seen 3x this week.
With run timestamps it now counts the supporting runs inside `recency_days` and
uses that as a tiebreak, so the automatic pass (which installs the top
candidates) prefers what the operator is doing NOW. No timestamps -> `recent`
equals `support`, so ordering is byte-identical to before.

I-2: `scan()` deduped drafts by exact slug only, so a subsequence or a
near-identical tool set produced a SECOND draft for one habit. It now skips a
candidate that is contained in (or shares >= `dedupe_similarity` of its tool set
with) a pattern already in the store or already emitted this run.

Contract:
  A I-1 the recency tiebreak: a recent habit outranks a stale one at equal
    length*support; without timestamps nothing changes
  B I-2 `_near_dup` unit cases (subsequence yes; distinct sets no)
  C I-2 `scan()` skips a subsequence of a STORED draft
  D no over-block: two genuinely different habits both get a draft

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1286_mining_recency_and_near_dup.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1286-")
os.environ["LONGRUN_OFFLINE"] = "1"
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "MATRIX_DOT", "MATRIX_SRC",
           "SKILLS_DIR", "PROPOSALS_DIR", "IMPROVEMENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(tmp, _k)
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)

from longrun.tools import registry              # noqa: E402
from longrun.util import selfevolve as SE       # noqa: E402

registry._external_tools = lambda: {}

K = sorted(SE._known_tools())
A, B = K[0:3], K[3:6]                            # two genuinely different habits
P = K[0:4]                                        # a 4-step habit
S = P[1:4]                                        # its contiguous 3-step subsequence

# ---- A: the recency tiebreak (I-1) -----------------------------------------
now = time.time()
hist = {}
for i in (1, 2, 3):
    hist["a%d" % i] = {"tools": A, "ts": now - 3600, "outcome": "ok"}          # fresh
    hist["b%d" % i] = {"tools": B, "ts": now - 400 * 86400, "outcome": "ok"}   # a year old
with open(SE._history_path(), "w", encoding="utf-8") as f:
    json.dump(hist, f)

seqs, ocs, pps = SE.history_split()
_tss = SE.history_ts()
cands = SE.mine(seqs, outcomes=ocs, purposes=pps, times=_tss)
by_pat = {tuple(c["pattern"]): c for c in cands}
ca, cb = by_pat.get(tuple(A)), by_pat.get(tuple(B))
check("A1 both habits are mined at equal (length x support)",
      bool(ca) and bool(cb) and ca["support"] == cb["support"] == 3,
      (ca and ca["support"], cb and cb["support"]))
check("A2 the fresh habit counts as fully recent", ca and ca.get("recent") == 3,
      ca and ca.get("recent"))
check("A3 the year-old habit counts as not recent", cb and cb.get("recent") == 0,
      cb and cb.get("recent"))
check("A4 the fresh habit now ranks first",
      [c["pattern"] for c in cands].index(A) < [c["pattern"] for c in cands].index(B),
      [c["pattern"] for c in cands])
_no_ts = SE.mine(seqs, outcomes=ocs)
check("A5 without timestamps recent == support (order unchanged)",
      all(c["recent"] == c["support"] for c in _no_ts),
      [(c["recent"], c["support"]) for c in _no_ts])

# ---- B: _near_dup unit cases (I-2) -----------------------------------------
check("B1 a contiguous subsequence is the same habit",
      SE._near_dup(S, P, 0.8) is True, (S, P))
check("B2 disjoint tool sets are not",
      SE._near_dup(["a", "b", "c"], ["x", "y", "z"], 0.8) is False)
check("B3 a 2-of-4 overlap (Jaccard 0.33) is not",
      SE._near_dup(["a", "b", "c"], ["a", "b", "z"], 0.8) is False)

# ---- C: scan() skips a subsequence of a STORED draft -----------------------
out1 = os.path.join(tmp, "store_has_P")
SE.draft(P, 3, out1)                              # the store already holds habit P
got = SE.scan([S, S, S], out1, outcomes=["ok"] * 3)
check("C1 the subsequence candidate is NOT drafted again",
      got == [], got)
check("C2 the stored draft for P is untouched",
      os.path.isfile(os.path.join(out1, SE.slug(P), "proposal.json")), os.listdir(out1))

# ---- D: no over-block — two different habits both get a draft --------------
out2 = os.path.join(tmp, "two_habits")
got2 = SE.scan([A, A, A, B, B, B], out2, outcomes=["ok"] * 6)
check("D1 two genuinely different habits produce two drafts", len(got2) == 2, got2)

print("---")
ok_n = sum(RESULTS)
print("v1286: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
