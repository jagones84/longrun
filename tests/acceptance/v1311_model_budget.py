#!/usr/bin/env python3
"""v1311 — model budget: delegation and budgeted routing, priced honestly (round 173).

Three papers, one subject (cost-efficient model choice inside a harness), read in
full 2026-11-26:

  * Delegent, arXiv:2611.33098 — the lead delegates legwork (code investigation,
    tests, corpus search) to a small model and keeps the main coding task.
  * ARoute, arXiv:2611.13209 — a task-aligned router under a cost budget, with a
    finite-sample guarantee on expected normalized spending.
  * Route Anything, arXiv:2611.05275 — a routing claim is bounded by the per-input
    oracle gap it captures.

What this pins:

  A  the contract — `FORMAT`, pure imports (v1275's rule), no app layer;
  B  delegation — legwork goes to the SLM, main work stays on the lead, and a task
     under ~25 calls is not worth delegating;
  C  routing — only-strong-correct counting, benefit-first batch planning, and a
     spend that a point estimate cannot certify;
  D  honesty — the oracle gap, the captured share, the efficiency multiple at a
     quality floor, and every misreading `audit` must name;
  E  the wire — `forge.py modelbudget audit FILE` exits 0 on a clean record and 1
     on findings (the CLI route the operator uses).

Deterministic: numbers and recorded claims only. No model, no network, no server.
Run:  python3 tests/acceptance/v1311_model_budget.py
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.harness.checks import model_budget as mb  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the contract (v1275's rule, asserted for this module) ───────────────
check("A1 FORMAT is declared and stamped on every result",
      isinstance(mb.FORMAT, str) and mb.FORMAT and mb.audit({})["format"] == mb.FORMAT)
_tree = ast.parse(open(mb.__file__, encoding="utf-8").read())
_imports = {n.names[0].name.split(".")[0]
            for n in ast.walk(_tree) if isinstance(n, ast.Import)}
_imports |= {(n.module or "").split(".")[0]
             for n in ast.walk(_tree) if isinstance(n, ast.ImportFrom)}
check("A2 no app layer is imported (stdlib only)",
      not ({"longrun", "os", "sys", "json"} & _imports) or _imports <= {"__future__", "math"},
      ",".join(sorted(x for x in _imports if x)))

# ── B · delegation (Delegent) ───────────────────────────────────────────────
check("B1 legwork is delegated to the SLM",
      mb.classify("corpus_search")["model"] == "slm")
check("B2 the main coding task stays on the lead",
      mb.classify("main_code")["model"] == "lead")
check("B3 an unknown task class fails closed to the lead",
      mb.classify("mystery") == {"task": "mystery", "model": "lead",
                                 "reason": "unknown-task-class",
                                 "format": mb.FORMAT})
check("B4 the instruction can be turned off (everything on the lead)",
      all(mb.classify(t, lead_owns_main=False)["model"] == "lead" for t in mb.TASK_CLASSES))
check("B5 the gain is share x (1 - slm ratio)",
      abs(mb.delegation_gain(0.6, 0.1)["gain"] - 0.54) < 1e-9)
check("B6 an invalid ratio is refused, not silently accepted",
      mb.delegation_gain(0.6, 1.4)["reason"] == "invalid-input")
check("B7 a task under ~25 calls is not worth delegating",
      mb.worthwhile(10, 0.9, 0.01)["reason"] == "short-task")
check("B8 a long legwork-heavy task is worth it",
      mb.worthwhile(120, 0.9, 0.01)["worthwhile"] is True)

# ── C · routing (ARoute) ────────────────────────────────────────────────────
_o = mb.osc([(False, True), (True, True), (True, False), (False, True)])
check("C1 only-strong-correct and strong-replaces-correct are both counted",
      abs(_o["osc"] - 0.5) < 1e-9 and abs(_o["replace"] - 0.25) < 1e-9, _o)
_plan = mb.plan([{"id": "a", "benefit": 1, "cost": 0.2},
                 {"id": "b", "benefit": 3, "cost": 0.3},
                 {"id": "c", "benefit": -1, "cost": 0.1}], budget=0.6)
check("C2 the budget buys the greatest benefit first and never a negative one",
      _plan["chosen"] == ["b", "a"] and _plan["adheres"] is True, _plan)
check("C3 a zero budget buys nothing",
      mb.plan([{"id": "a", "benefit": 1, "cost": 0.2}], budget=0.0)["chosen"] == [])
check("C4 a point estimate cannot certify a spend",
      mb.certified(0.4, 0.5, 0.0)["certified"] is False
      and mb.certified(0.4, 0.5, 0.0)["reason"] == "no-margin")
check("C5 a margin that fits the quota certifies it",
      mb.certified(0.4, 0.5, 0.05)["certified"] is True)
check("C6 a margin that does not fit refuses certification",
      mb.certified(0.48, 0.5, 0.05)["certified"] is False)
check("C7 an overspend is reported even when certified is asked",
      mb.certified(0.6, 0.5, 0.01)["adheres"] is False)

# ── D · honesty (Route Anything) ────────────────────────────────────────────
check("D1 the oracle gap is the mean per-input headroom",
      abs(mb.oracle_gap([80.0, 80.0], [84.0, 87.0])["gap"] - 5.5) < 1e-9)
_cap = mb.capture([81.0, 80.5], [80.0, 80.0], [84.0, 87.0])
check("D2 the captured share is gain over the oracle gap",
      abs(_cap["capture"] - 0.136363636) < 1e-6, _cap)
check("D3 no headroom means no capture claim",
      mb.capture([80.0], [80.0], [80.0])["reason"] == "no-headroom")
_eff = mb.efficiency(0.8865, -0.4)
check("D4 the efficiency multiple is 1/(1-saving) and admissible at the floor",
      abs(_eff["efficiency"] - 8.81) < 0.02 and _eff["admissible"] is True, _eff)
check("D5 a quality loss past the floor is not admissible",
      mb.efficiency(0.5, -2.0)["admissible"] is False)
_clean = mb.audit({"claimed_gain": 0.3, "oracle_gap": 5.4, "capture": 0.06,
                   "seeds": 3, "units": "fraction", "delegation_calls": 200,
                   "delegated_tasks": ["run_tests"], "spend": 0.3, "quota": 0.5,
                   "margin": 0.05, "certified": True})
check("D6 a consistent record is clean", _clean["verdict"] == "clean", _clean)
for kind, rec in (
        ("routing-beyond-oracle", {"claimed_gain": 9.0, "oracle_gap": 5.4, "capture": 0.5, "seeds": 2}),
        ("capture-not-reported", {"claimed_gain": 1.0}),
        ("single-seed", {"claimed_gain": 1.0, "oracle_gap": 5.4, "capture": 0.1, "seeds": 1}),
        ("delegation-on-short-task", {"delegation_calls": 5}),
        ("main-delegated", {"delegated_tasks": ["main_code"]}),
        ("budget-overspend", {"spend": 0.9, "quota": 0.5}),
        ("uncertified-spend", {"certified": True, "margin": 0.0}),
        ("unit-mismatch", {"units": "tokens"})):
    got = {f["kind"] for f in mb.audit(rec)["findings"]}
    check("D7 audit names %s" % kind, kind in got, sorted(got))
_advice = mb.advise({"routing_claim": True, "delegation": True,
                     "delegated_tasks": ["main_code"], "delegation_calls": 5,
                     "budget": 0.5, "margin": 0.0})
check("D8 advise returns every applicable rule",
      len(_advice["advice"]) >= 4, _advice["advice"])

# ── E · the wire (the CLI route the operator uses) ──────────────────────────
_tmp = tempfile.mkdtemp(prefix="sf-v1311-")
_clean_file = os.path.join(_tmp, "clean.json")
_bad_file = os.path.join(_tmp, "bad.json")
json.dump({"claimed_gain": 0.3, "oracle_gap": 5.4, "capture": 0.06, "seeds": 3,
           "units": "fraction", "delegation_calls": 200,
           "delegated_tasks": ["run_tests"], "spend": 0.3, "quota": 0.5,
           "margin": 0.05, "certified": True},
          open(_clean_file, "w", encoding="utf-8"))
json.dump({"claimed_gain": 9.0, "oracle_gap": 5.4, "capture": 0.5, "seeds": 2},
          open(_bad_file, "w", encoding="utf-8"))
_run = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"),
                       "modelbudget", "audit", _clean_file],
                      capture_output=True, text=True, timeout=60)
check("E1 the clean record exits 0", _run.returncode == 0,
      (_run.stdout + _run.stderr)[-200:])
_run2 = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"),
                        "modelbudget", "audit", _bad_file],
                       capture_output=True, text=True, timeout=60)
check("E2 a finding exits 1", _run2.returncode == 1,
      (_run2.stdout + _run2.stderr)[-200:])
_run3 = subprocess.run([sys.executable, os.path.join(REPO, "forge.py"), "modelbudget"],
                       capture_output=True, text=True, timeout=60)
check("E3 the built-in report prints advice and exits 0",
      _run3.returncode == 0 and "advice" in _run3.stdout, _run3.stdout[:160])

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
