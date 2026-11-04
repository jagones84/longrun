#!/usr/bin/env python3
"""v788 — evolution is accepted on a CASE TABLE, not on one lucky green.

`min_green_streak: 1` plus a single `check.py` cannot tell an improvement from
noise, and cannot see a case that USED to pass. This pins the gate:

  A  `evaluate_cases` returns {case_id: pass}; `verify` stores that map and the
     baseline it was compared against
  B  promotion refuses ANY case that regressed, even when the total went up
  C  promotion refuses a candidate that improved nothing over the baseline
  D  a candidate that keeps every case and gains one is accepted, and the
     evidence class is stamped on the proposal and on the installed SKILL.md
  E  with no baseline the promotion is allowed but LABELLED `single-case`
     (thinness made visible, never dressed up as statistics)
  F  `LONGRUN_EVOLVE_CASES=1` makes two cases mandatory

Deterministic: temp dirs, the runner is injected (no sandbox, no model).
Run: python3 tests/acceptance/v788_evolve_case_gate.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-788-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_tmp, "skills")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def runner_for(verdicts):
    """A pure check runner: command -> the verdict registered for that case."""
    def run(proposal_dir, command):
        return bool(verdicts.get(command, False)), "case %s" % command
    return run


def proposal(tag, cases, baseline=None, status="verified"):
    d = os.path.join(_tmp, "proposals", tag)
    os.makedirs(d, exist_ok=True)
    prop = {"name": tag, "status": status, "origin": "user",
            "green_streak": 1, "pattern": ["fs.read"]}
    if cases is not None:
        prop["verify"] = {"cases": cases, "baseline": baseline or {}}
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(prop, f)
    return d


CFG = {"min_green_streak": 1, "category": "created", "verify_timeout": 5}

# ------------------------------------------- A: verify stores the case table -
p1 = proposal("table", None, status="new")
rep = selfevolve.verify(p1, runner=runner_for({"python3 check.py": True,
                                               "pytest -q case_b": True,
                                               "pytest -q case_c": False}),
                        c=CFG,
                        cases=["default", "pytest -q case_b", "pytest -q case_c"],
                        baseline={"default": True, "pytest -q case_b": True})
stored = json.load(open(os.path.join(p1, "proposal.json"), encoding="utf-8"))
check("A1 every case is run and reported",
      rep.get("cases") == {"default": True, "pytest -q case_b": True,
                           "pytest -q case_c": False}, rep.get("cases"))
check("A2 one red case makes the whole verify red",
      rep.get("green") is False and stored.get("status") == "rejected", stored.get("status"))
check("A3 the baseline is stored WITH the result",
      (stored.get("verify") or {}).get("baseline") == {"default": True,
                                                       "pytest -q case_b": True},
      (stored.get("verify") or {}).get("baseline"))

_seen = []


def recording_runner(proposal_dir, command):
    _seen.append(command)
    return True, "ok"


selfevolve.verify(proposal("legacy", None, status="new"), runner=recording_runner,
                  c=CFG, cases=["default"])
check("A4 the default case runs the legacy check.py",
      _seen == ["python3 check.py"], _seen)

p1b = proposal("table-ok", None, status="new")
rep_ok = selfevolve.verify(p1b, runner=runner_for({"python3 check.py": True}),
                           c=CFG, cases=None)
check("A5 no case list = today's single check, still verified",
      rep_ok.get("green") is True
      and json.load(open(os.path.join(p1b, "proposal.json"), encoding="utf-8"))["status"] == "verified",
      rep_ok)

# ------------------------------------------ B: a regression is never averaged -
reg = proposal("regressed", {"default": True, "case_b": False, "case_c": True},
               {"default": True, "case_b": True, "case_c": True})
out = selfevolve.promote(reg, skills_dir=os.path.join(_tmp, "skills-b"), c=CFG)
check("B1 a dropped case refuses the promotion",
      out.get("ok") is False and out.get("regressions") == ["case_b"], out)
check("B2 nothing was installed",
      not os.path.exists(os.path.join(_tmp, "skills-b", "created", "regressed")))

# ---------------------------------------------- C: no improvement, no promote -
flat = proposal("flat", {"default": True, "case_b": True},
                {"default": True, "case_b": True})
out = selfevolve.promote(flat, skills_dir=os.path.join(_tmp, "skills-c"), c=CFG)
check("C1 a candidate that gains no case is refused",
      out.get("ok") is False and "no case improved" in str(out.get("error")), out)

# -------------------------------------------- D: keep every case, gain one ---
better = proposal("better", {"default": True, "case_b": True, "case_c": True},
                  {"default": True, "case_b": True})
skills_d = os.path.join(_tmp, "skills-d")
out = selfevolve.promote(better, skills_dir=skills_d, c=CFG)
target = os.path.join(skills_d, "created", "better")
check("D1 a strict improvement is promoted", out.get("ok") is True, out)
check("D2 the evidence class is reported", out.get("evidence") == "cases", out)
check("D3 the installed SKILL.md carries the evidence",
      os.path.isfile(os.path.join(target, "SKILL.md"))
      and "evidence: cases" in open(os.path.join(target, "SKILL.md"), encoding="utf-8").read())
archived = json.load(open(os.path.join(target, "proposal.json"), encoding="utf-8"))
check("D4 the archived proposal is stamped archived + cases",
      archived.get("status") == "archived" and archived.get("evidence") == "cases", archived)

# ------------------------------------- E: no baseline -> labelled, not hidden -
single = proposal("single", {"default": True}, {})
out = selfevolve.promote(single, skills_dir=os.path.join(_tmp, "skills-e"), c=CFG)
check("E1 a baseline-less single case still promotes (today's behaviour)",
      out.get("ok") is True, out)
check("E2 but it is LABELLED single-case", out.get("evidence") == "single-case", out)

# ------------------------------------ F: the strict env demands two cases ----
os.environ["LONGRUN_EVOLVE_CASES"] = "1"
try:
    strict = proposal("strict", {"default": True}, {})
    out = selfevolve.promote(strict, skills_dir=os.path.join(_tmp, "skills-f"), c=CFG)
    check("F1 LONGRUN_EVOLVE_CASES=1 refuses a single case",
          out.get("ok") is False and "at least 2" in str(out.get("error")), out)
finally:
    os.environ.pop("LONGRUN_EVOLVE_CASES", None)

print("\n---\nv788: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
