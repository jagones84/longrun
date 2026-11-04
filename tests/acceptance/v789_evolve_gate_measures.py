#!/usr/bin/env python3
"""v789 — the evolution gate measures: repeats, cost, attribution, release, set.

The case table (v788) made a promotion per-item. This adds the four things the
corpus says a per-item gate still lacks:

  A  REPEATS (ParetoSaddler 2611.02079): each case runs N times, a case passes on
     a strict majority, the counts are stored                     [C1]
  B  COST (HarnessPro 2610.26770): an automatic promotion whose markdown is an
     outlier against the installed median is refused                [C2]
  C  RELEASE provenance (Post-Audit Mirage 2610.31103): the operator path needs a
     reason and stamps who/when/why                                [C8]
  D  ATTRIBUTION (Harness-Delta 2610.22466): which case was fixed/broken, and a
     confirmation that the INSTALLED copy behaves like the draft   [C4]
  E  COMPOSED-SET smoke (Compositional Safety 2609.33123): a promotion is
     refused when an already installed artifact goes red            [C5]

Deterministic: temp dirs, the case runner is injected (no sandbox, no model).
Run: python3 tests/acceptance/v789_evolve_gate_measures.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-789-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_tmp, "skills-default")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def proposal(tag, cases=None, baseline=None, status="verified", md=100, name=None):
    d = os.path.join(_tmp, "proposals", tag)
    os.makedirs(d, exist_ok=True)
    prop = {"name": name or tag, "status": status, "origin": "user",
            "green_streak": 1, "pattern": ["fs.read"]}
    if cases is not None:
        prop["verify"] = {"cases": cases, "baseline": baseline or {},
                          "cost_tokens": {"tokens": max(1, md // 4), "bytes": md}}
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(prop, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("x" * md)
    return d


def installed(root, tag, cases, md=100):
    """An artifact already on disk, with its own case table."""
    d = os.path.join(root, "created", tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"name": tag, "status": "archived", "origin": "auto",
                   "verify": {"cases": cases, "baseline": {}}}, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("x" * md)
    return d


CFG = {"min_green_streak": 1, "category": "created", "verify_timeout": 5,
       "max_cost_ratio": 2.0}

# ------------------------------------------------ A: repeats per case --------
seq = iter([True, False, True])


def flaky(proposal_dir, command):
    return next(seq), "scripted"


rep = selfevolve.verify(proposal("flaky", status="new"), runner=flaky, c=CFG,
                        cases=["case_a"], repeats=3)
check("A1 a 2/3 majority passes the case",
      rep["cases"] == {"case_a": True} and rep["case_runs"]["case_a"] == {"passes": 2, "runs": 3},
      rep)
check("A2 the counts are stored with the result", "2/3" in rep.get("output", ""), rep.get("output"))

rep = selfevolve.verify(proposal("flaky2", status="new"),
                        runner=lambda d, c: (False, "no"), c=CFG,
                        cases=["case_a"], repeats=3)
check("A3 0/3 is a red case", rep["cases"] == {"case_a": False}, rep["cases"])

rep = selfevolve.verify(proposal("cfg-repeats", status="new"),
                        runner=lambda d, c: (True, "ok"),
                        c={"verify_repeats": 3, "verify_timeout": 5}, cases=["a"])
check("A4 the config default drives the repeat count",
      rep["case_runs"]["a"] == {"passes": 3, "runs": 3}, rep.get("case_runs"))

# ------------------------------------------- C: the release is attributable --
root_c = os.path.join(_tmp, "skills-c")
p = proposal("release", cases={"default": True}, md=100, name="release")
out = selfevolve.promote(p, skills_dir=root_c, c=CFG, human=True)
check("C1 an operator release with no reason is refused",
      out.get("ok") is False and "reason" in str(out.get("error")), out)
check("C2 nothing was installed", not os.path.exists(os.path.join(root_c, "created", "release")))
out = selfevolve.promote(p, skills_dir=root_c, c=CFG, human=True, reason="operator says yes")
check("C3 a reasoned release is accepted", out.get("ok") is True, out)
arch = json.load(open(os.path.join(root_c, "created", "release", "proposal.json"), encoding="utf-8"))
check("C4 the release stamps who/when/why",
      arch.get("released_by") == "operator" and arch.get("released_ts")
      and arch.get("released_reason") == "operator says yes", arch)

# ------------------------------------------------- D: attribution ------------
root_d = os.path.join(_tmp, "skills-d")
p = proposal("attrib", cases={"default": True, "case_b": True},
             baseline={"default": True, "case_b": False}, name="attrib")
out = selfevolve.promote(p, skills_dir=root_d, c=CFG,
                         runner=lambda d, c: (c != "case_b_that_fails", "ok"))
check("D1 the promotion records the case flips",
      (out.get("attribution") or {}).get("case_flips") == {"case_b": "fail->pass"},
      out.get("attribution"))
check("D2 gained/lost are counted", (out.get("attribution") or {}).get("gained") == 1
      and (out.get("attribution") or {}).get("lost") == 0, out.get("attribution"))
check("D3 the installed copy is confirmed",
      (out.get("attribution") or {}).get("installed_confirmed") is True, out.get("attribution"))
saved = json.load(open(os.path.join(root_d, "created", "attrib", "proposal.json"), encoding="utf-8"))
check("D4 the attribution is persisted on the artifact", "attribution" in saved, list(saved))

# ------------------------------------------------------- B: cost gate --------
root_b = os.path.join(_tmp, "skills-b")
for i in range(3):
    installed(root_b, "s%d" % i, {"default": True}, md=100)
p = proposal("fat", cases={"default": True}, md=2000, name="fat")
out = selfevolve.promote(p, skills_dir=root_b, c=CFG)
check("B1 an outlier prompt cost is refused",
      out.get("ok") is False and "cost gate" in str(out.get("error")), out)
check("B2 nothing was installed",
      not os.path.exists(os.path.join(root_b, "created", "fat")))
out = selfevolve.promote(p, skills_dir=root_b, c=CFG, human=True, reason="editorial choice")
check("B3 the operator can still release it", out.get("ok") is True, out)
p2 = proposal("lean", cases={"default": True}, md=100, name="lean")
out2 = selfevolve.promote(p2, skills_dir=root_b, c=CFG)
check("B4 a normal-sized artifact passes and reports its cost",
      out2.get("ok") is True and isinstance(out2.get("cost_tokens"), int), out2)

# ---------------------------------------------- E: composed-set smoke --------
root_e = os.path.join(_tmp, "skills-e")
installed(root_e, "old", {"case_old": True})


def smoke_runner(proposal_dir, command):
    return (command != "case_old"), "old artifact is red"


p = proposal("new", cases={"default": True}, name="new")
out = selfevolve.promote(p, skills_dir=root_e, c=CFG, runner=smoke_runner)
check("E1 a red installed artifact blocks the promotion",
      out.get("ok") is False and "composed-set smoke red" in str(out.get("error")), out)
check("E2 the red artifact is named", "old" in (out.get("smoke") or {}), out.get("smoke"))
check("E3 nothing was installed",
      not os.path.exists(os.path.join(root_e, "created", "new")))

print("\n---\nv789: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
