#!/usr/bin/env python3
"""RSI-V — a promotion carries a bound on accepting an inferior candidate.

The gate was a set of deterministic booleans, so a case that passed 2 of 3
repeats promoted exactly like one that passed 3 of 3. TRUST (arXiv:2611.10787)
measures the greedy gate accepting an inferior update in 45.59% of rounds; here
each repeated case must beat a fair coin at `promotion_alpha`, the accepted-set
error is bounded by cases x alpha, and a case verified ONCE is named
`single-run` instead of being given a bound it does not have.

Deterministic: temp dirs, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="longrun-v965-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"   # the sealed suite is not V's subject
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def proposal(tag, cases, counts=None, baseline=None):
    d = os.path.join(_tmp, "proposals", tag)
    os.makedirs(d, exist_ok=True)
    prop = {"name": tag, "status": "verified", "origin": "user",
            "green_streak": 1, "pattern": ["fs.read"],
            "verify": {"cases": cases, "baseline": baseline or {}}}
    if counts is not None:
        prop["verify"]["case_runs"] = counts
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(prop, f)
    return d


def promoted(tag, skills):
    return os.path.isdir(os.path.join(_tmp, skills, "created", tag))


CFG = {"min_green_streak": 1, "category": "created", "verify_timeout": 5,
       "promotion_alpha": 0.05}

# ---- A: two of three is a coin, not evidence ------------------------------
weak = proposal("weak", {"default": True},
                {"default": {"passes": 2, "runs": 3}})
out = selfevolve.promote(weak, skills_dir=os.path.join(_tmp, "s-a"), c=CFG)
check("A1 2/3 is refused at alpha 0.05",
      out.get("ok") is False and "evidence gate" in str(out.get("error")), out)
check("A2 the refusal names the case and its p-value",
      (out.get("bound") or {}).get("failed") == ["default"]
      and abs(((out.get("bound") or {}).get("cases") or {}).get("default", {}).get("p", -1) - 0.5) < 1e-9,
      out.get("bound"))
check("A3 nothing was installed", not promoted("weak", "s-a"))

# ---- B: the price of alpha 0.05 is five consecutive passes --------------
three = proposal("three", {"default": True},
                 {"default": {"passes": 3, "runs": 3}})
out = selfevolve.promote(three, skills_dir=os.path.join(_tmp, "s-b0"), c=CFG)
check("B0 3/3 does NOT clear alpha 0.05 (p=0.125) — the bar is stated, not hidden",
      out.get("ok") is False, out)

solid = proposal("solid", {"default": True},
                 {"default": {"passes": 5, "runs": 5}})
out = selfevolve.promote(solid, skills_dir=os.path.join(_tmp, "s-b"), c=CFG)
check("B1 5/5 is promoted", out.get("ok") is True, out)
archived = json.load(open(os.path.join(_tmp, "s-b", "created", "solid",
                                       "proposal.json"), encoding="utf-8"))
bound = archived.get("promotion_bound") or {}
check("B2 the archived proposal carries the bound",
      bound.get("verdict") == "bounded" and bound.get("basis"), bound)
check("B3 the family-wise bound is cases x alpha",
      bound.get("family_alpha") == 0.05, bound)
check("B4 the p-value is the exact tail",
      abs((bound.get("cases") or {}).get("default", {}).get("p", -1) - 0.03125) < 1e-9, bound)

# ---- C: the bar is configurable, never hardcoded -------------------------
border = proposal("border", {"default": True},
                  {"default": {"passes": 3, "runs": 4}})
out = selfevolve.promote(border, skills_dir=os.path.join(_tmp, "s-c"), c=CFG)
check("C1 3/4 fails the default bar (p=0.3125)",
      out.get("ok") is False and "evidence gate" in str(out.get("error")), out)
loose = dict(CFG, promotion_alpha=0.4)
out = selfevolve.promote(border, skills_dir=os.path.join(_tmp, "s-c2"), c=loose)
check("C2 the same artifact passes at alpha 0.4",
      out.get("ok") is True, out)

# ---- D: one run per case has no bound, and says so -----------------------
once = proposal("once", {"default": True},
                {"default": {"passes": 1, "runs": 1}})
out = selfevolve.promote(once, skills_dir=os.path.join(_tmp, "s-d"), c=CFG)
check("D1 a single run still promotes (today's behaviour)", out.get("ok") is True, out)
archived = json.load(open(os.path.join(_tmp, "s-d", "created", "once",
                                       "proposal.json"), encoding="utf-8"))
bound = archived.get("promotion_bound") or {}
check("D2 it is labelled single-run, not given a bound",
      bound.get("verdict") == "single-run" and bound.get("single_run") == ["default"], bound)

# ---- E: a legacy proposal without counts is not refused ------------------
legacy = proposal("legacy", {"default": True, "other": True})
out = selfevolve.promote(legacy, skills_dir=os.path.join(_tmp, "s-e"), c=CFG)
check("E1 no case_runs means no bound and no refusal", out.get("ok") is True, out)

# ---- F: one weak case is enough to refuse the whole set ------------------
mixed = proposal("mixed", {"default": True, "other": True},
                 {"default": {"passes": 5, "runs": 5},
                  "other": {"passes": 2, "runs": 3}})
out = selfevolve.promote(mixed, skills_dir=os.path.join(_tmp, "s-f"), c=CFG)
check("F1 the weak case refuses the set and is named",
      out.get("ok") is False and (out.get("bound") or {}).get("failed") == ["other"], out)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
