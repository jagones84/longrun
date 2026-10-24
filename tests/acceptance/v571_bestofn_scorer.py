#!/usr/bin/env python3
"""v571 (STAGED — audit F4): a scorer failure must never win best-of-N.
Failed candidates are excluded; all-failed keeps the legacy first-pick.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import bestofn as B  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def boom(t):
    raise RuntimeError("scorer died")


best, items = B.choose(["good", "bad"], lambda t: {"good": 0.9, "bad": 0.1}[t], {})
check("0a sane scorer is untouched", best == "good", (best, items))

best, items = B.choose(["good", "bad"],
                       lambda t: (_ for _ in ()).throw(RuntimeError("x")) if t == "bad" else 0.9,
                       {})
check("1a a failed candidate cannot win",
      best == "good", (best, items))
check("1b the failed candidate is excluded from the scores",
      [x for x, _ in items] == ["good"], items)
check("1c reported scores stay floats",
      all(isinstance(s, float) for _, s in items), items)

best, items = B.choose(["a", "b"], boom, {"min_score": 0.0})
check("2a all-failed falls back to the legacy first pick",
      best == "a", (best, items))

best, items = B.choose(["a"], boom, {"min_score": 0.5})
check("2b the min_score floor still applies on fallback",
      best is None, (best, items))

best, items = B.choose([], boom, {})
check("2c empty list still returns (None, [])", (best, items) == (None, []), (best, items))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
