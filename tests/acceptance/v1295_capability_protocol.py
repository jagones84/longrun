#!/usr/bin/env python3
"""v1295 — a capability protocol: evolve/held-out split, A/A band, like-for-like verdict (RSI R1).

Source: RRSI arXiv:2609.24972 §4.1 and Tables 2–3; HSI arXiv:2608.08466 §4.1
(Setup B). Both separate the tasks a harness is evolved on from the tasks it is
scored on, and both establish a noise band before trusting a delta. Longrun had
benchmark runners and no protocol tying them together — its newest capability run
predates every RSI round. This module is the protocol, not a benchmark runner.

Contract:
  A `split()` is deterministic, disjoint, exhaustive, non-empty, and refuses bad input
  B `split_digest()` names the held-out side (the seal is a contract; the digest is the audit)
  C `noise_band()` is the worst A/A gap; one run is refused, not guessed
  D `record()` carries arm/model/suite/split/scores/n/tokens/date and refuses mismatch or non-binary scores
  E `compare()` is improved/worse/flat only against a band, and refuses a changed n or suite
  F an end-to-end fixture produces the first verdict the repository could defend

Deterministic: no model, no network, no benchmark executed.
Run: python3 tests/acceptance/v1295_capability_protocol.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import capability_protocol as CP   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


TASKS = ["t%02d" % i for i in range(10)]

# ---- A: the split ----------------------------------------------------------
one = CP.split(TASKS, heldout_fraction=0.3, seed=7)
two = CP.split(TASKS, heldout_fraction=0.3, seed=7)
other = CP.split(TASKS, heldout_fraction=0.3, seed=8)
check("A1 a split is accepted", one.get("ok") is True, one)
check("A2 the same seed gives the same two sides", one == two, (one, two))
check("A3 the sides are disjoint and exhaustive",
      set(one["evolve"]).isdisjoint(one["heldout"])
      and set(one["evolve"]) | set(one["heldout"]) == set(TASKS), one)
check("A4 both sides are non-empty at the requested ratio",
      len(one["heldout"]) == 3 and len(one["evolve"]) == 7, one)
check("A5 a different seed moves tasks", other["heldout"] != one["heldout"],
      (one["heldout"], other["heldout"]))
check("A6 two tasks still split (1 held out, 1 to evolve)",
      CP.split(["a", "b"], heldout_fraction=0.5).get("ok") is True
      and len(CP.split(["a", "b"], heldout_fraction=0.5)["heldout"]) == 1)
check("A7 one task is refused", CP.split(["a"]).get("ok") is False)
check("A8 duplicate ids are refused", CP.split(["a", "a"]).get("ok") is False)
check("A9 an out-of-range fraction is refused",
      CP.split(TASKS, heldout_fraction=0).get("ok") is False
      and CP.split(TASKS, heldout_fraction=1).get("ok") is False)
check("A10 ids are normalised to stripped strings",
      CP.split([1, " 2 "], heldout_fraction=0.5)["evolve"] in (["1"], ["2"]),
      CP.split([1, " 2 "], heldout_fraction=0.5))

# ---- B: the digest ---------------------------------------------------------
check("B1 the digest is stable for the same split",
      CP.split_digest(one) == CP.split_digest(two)
      and len(CP.split_digest(one)) == 64)
check("B2 the digest changes with the held-out set",
      CP.split_digest(one) != CP.split_digest(other))

# ---- C: the A/A band -------------------------------------------------------
band = CP.noise_band([0.70, 0.74, 0.72])
check("C1 the band is the worst pair gap", band.get("band") == 0.04, band)
check("C2 one run cannot establish a band",
      CP.noise_band([0.7]).get("ok") is False)
check("C3 a non-number is refused", CP.noise_band([0.7, "x"]).get("ok") is False)
check("C4 a negative score is refused", CP.noise_band([-0.1, 0.2]).get("ok") is False)

# ---- D: the record ---------------------------------------------------------
split = CP.split(TASKS, 0.3, seed=3)
ev = [1] * 7                                # 7/7 evolve
ho = [1, 0, 1]                              # 2/3 held out
rec = CP.record("baseline", "dgx:qwen-3.8-27b", "Terminal-Bench slice", split,
                ev, ho, tokens=123456, date="2026-11-24")
check("D1 a complete record is accepted", rec.get("ok") is True, rec)
check("D2 the rates and n are computed from the task outcomes",
      rec["evolve"] == {"passed": 7, "n": 7, "rate": 1.0}
      and rec["heldout"] == {"passed": 2, "n": 3, "rate": 0.6667}, rec)
check("D3 the split is named by digest, not by its held-out ids",
      rec.get("split_sha256") == CP.split_digest(split)
      and "heldout" not in (rec.get("split") or {}), rec)
check("D4 missing arm/model/suite are refused",
      CP.record("", "m", "s", split, ev, ho).get("ok") is False
      and CP.record("a", "", "s", split, ev, ho).get("ok") is False
      and CP.record("a", "m", "", split, ev, ho).get("ok") is False)
check("D5 a score list that does not match the split is refused",
      CP.record("a", "m", "s", split, ev, [1]).get("ok") is False)
check("D6 a non-binary outcome is refused",
      CP.record("a", "m", "s", split, ev, [1, 0.5, 1]).get("ok") is False)
check("D7 an empty side is refused",
      CP.record("a", "m", "s", split, [], ho).get("ok") is False)
check("D8 a non-integer token count is refused",
      CP.record("a", "m", "s", split, ev, ho, tokens="many").get("ok") is False)

# ---- E: the verdict --------------------------------------------------------
after = CP.record("rsr", "dgx:qwen-3.8-27b", "Terminal-Bench slice", split,
                  [1] * 7, [1, 1, 1], tokens=100000, date="2026-11-24")
up = CP.compare(rec, after, noise=band)
check("E1 a gain above the band is `improved`",
      up.get("verdict") == "improved" and up["delta"] == 0.3333, up)
same = CP.compare(rec, rec, noise=band)
check("E2 the same record against itself is `flat`",
      same.get("verdict") == "flat" and same["delta"] == 0.0, same)
down = CP.record("regressed", "dgx:qwen-3.8-27b", "Terminal-Bench slice", split,
                 [1] * 7, [0, 0, 0])
check("E3 a drop beyond the band is `worse`",
      CP.compare(rec, down, noise=band).get("verdict") == "worse")
big = CP.noise_band([0.4, 0.8])
check("E4 a delta inside a wide band is `flat`",
      CP.compare(rec, after, noise=big).get("verdict") == "flat", big)
check("E5 no band means no verdict",
      CP.compare(rec, after).get("error", "").startswith("no-noise-band"))
other_n = CP.record("other-n", "dgx:qwen-3.8-27b", "Terminal-Bench slice",
                    CP.split(TASKS, 0.5, seed=3), [1] * 5, [1] * 5)
check("E6 a changed n is not comparable",
      "not-comparable" in str(CP.compare(rec, other_n, noise=band).get("error")),
      CP.compare(rec, other_n, noise=band))
other_suite = CP.record("other-suite", "dgx:qwen-3.8-27b", "JobBench", split,
                        [1] * 7, [1, 1, 1])
check("E7 a different suite is refused",
      CP.compare(rec, other_suite, noise=band).get("ok") is False)
check("E8 the compared side must be evolve|heldout",
      CP.compare(rec, after, noise=band, side="train").get("ok") is False)

# ---- F: end to end --------------------------------------------------------
# Three unchanged runs establish the band; the change then moves the held-out
# side from 2/3 to 3/3, which is above it, and the evolve side is unchanged.
aa = CP.noise_band([CP.record("baseline", "m", "JobBench", split, ev, ho)["heldout"]["rate"],
                    CP.record("baseline", "m", "JobBench", split, ev, [1, 1, 0])["heldout"]["rate"],
                    CP.record("baseline", "m", "JobBench", split, ev, [1, 0, 1])["heldout"]["rate"]])
base = CP.record("baseline", "m", "JobBench", split, ev, ho)
cand = CP.record("candidate", "m", "JobBench", split, ev, [1, 1, 1])
verdict = CP.compare(base, cand, noise=aa)
check("F1 the first defensible verdict is produced from records alone",
      verdict.get("ok") is True and verdict["verdict"] == "improved"
      and verdict["n"] == 3, (verdict, aa))

print("---")
print("v1295: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
