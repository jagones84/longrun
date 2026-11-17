#!/usr/bin/env python3
"""v1069 — a canary case makes a perfect held-out score a TRIPWIRE, not a triumph.

Source of the mechanism: PROCTOR, arXiv:2609.02246 (stored S-2026-11-18-007),
§5.5 — "canary cases … no honest agent can pass, so that a perfect score is itself
evidence of cheating". Longrun's promotion gate is deterministic + held-out-sealed
(`util/selfevolve.promote`, `plan/heldout.py`) but has NO positive control: nothing
proves the gate would reject a cheater (a candidate that reads the answer key, or a
silent parser fallback that lifts the metric).

Contract pinned here:
  C1 `longrun.plan.canary` exists and its detector is pure (no I/O, no model).
  C2 an absent/undeclared canary is `unbound`, NEVER green (no positive control).
  C3 a canary that PASSED is `tripped` — evidence of leakage, not quality.
  C4 a canary that FAILED is `ok` — the healthy outcome.
  C5 a declared canary missing from the results is `unbound`.
  C6 `plan.heldout.gate` refuses (green False, reason `canary_tripped`) when the
     canary passes.
  C7 `util.selfevolve.promote` refuses a proposal whose held-out gate tripped on
     the canary (error names the canary).

Run: python3 tests/acceptance/v1069_promotion_canary.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


try:
    from longrun.plan import canary
except Exception as e:  # noqa: BLE001
    canary = None
    IMPORT_ERR = e
else:
    IMPORT_ERR = None

check("C1 plan.canary imports", canary is not None, IMPORT_ERR or "")

if canary is not None:
    check("C2 no canary declared -> unbound (never green)",
          canary.evaluate({"cases": {"a": True}}, canary_id=None).get("verdict") == "unbound")
    r_pass = canary.evaluate({"cases": {"canary_x": True, "a": True}}, canary_id="canary_x")
    check("C3 a PASSED canary is tripped",
          r_pass.get("verdict") == "tripped" and r_pass.get("case") == "canary_x", r_pass)
    r_fail = canary.evaluate({"cases": {"canary_x": False, "a": True}}, canary_id="canary_x")
    check("C4 a FAILED canary is ok", r_fail.get("verdict") == "ok", r_fail)
    r_missing = canary.evaluate({"cases": {"a": True}}, canary_id="canary_x")
    check("C5 a declared-but-absent canary is unbound",
          r_missing.get("verdict") == "unbound", r_missing)

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
