#!/usr/bin/env python3
"""v919 — the promotion gate cannot be priced around (DR-M).

Numbered `v919`, not `v910`: another stream created `v910_no_team_bulk.py` in the
same working tree while this item was being built (see the plan's DR-M row).

`_installed_cost_median` answered **0** with fewer than three installed artifacts,
and `promote` read 0 as falsy — so a category holding one or two skills had NO
cost gate at all: a 20x oversized markdown was promoted automatically.

The gate is now priced from whatever is installed, and the basis is written on
the artifact instead of being hidden:
  * 0 samples  -> cannot judge; the install proceeds and the record says
                  `cost_basis: "no-baseline"` (the first install IS the baseline)
  * 1-2        -> applied against the median of what exists ("weak-median(n=k)")
  * >=3        -> applied ("median(n=k)")
  * operator release over the ratio, or over a required held-out suite, is
    allowed but named in `release_skipped`.

Deterministic: temp dirs, injected case runner, no sandbox, no model, no network.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-v910-")
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


def proposal(tag, md=100, cases=None):
    d = os.path.join(_tmp, "proposals", tag)
    os.makedirs(d, exist_ok=True)
    prop = {"name": tag, "status": "verified", "origin": "user",
            "green_streak": 1, "pattern": ["fs.read"],
            "verify": {"cases": cases or {"default": True}, "baseline": {},
                       "cost_tokens": {"tokens": max(1, md // 4), "bytes": md}}}
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(prop, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("x" * md)
    return d


def installed(root, tag, md=100):
    d = os.path.join(root, "created", tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"name": tag, "status": "archived", "origin": "auto",
                   "verify": {"cases": {"default": True}, "baseline": {}}}, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("x" * md)
    return d


CFG = {"min_green_streak": 1, "category": "created", "verify_timeout": 5,
       "max_cost_ratio": 2.0}

# ---- A: ONE installed sample is a baseline, not "no baseline" ----------------
root_a = os.path.join(_tmp, "skills-a")
installed(root_a, "seed", md=100)
out = selfevolve.promote(proposal("fat1", md=4000), skills_dir=root_a, c=CFG)
check("A1 with ONE sample an oversized candidate is refused",
      out.get("ok") is False and "cost gate" in str(out.get("error")), out)
check("A2 nothing was installed",
      not os.path.exists(os.path.join(root_a, "created", "fat1")))
check("A3 the refusal names the weak basis",
      out.get("median_tokens") == 25 and int(out.get("cost_tokens") or 0) == 1000, out)

# ---- B: two samples, same rule ------------------------------------------------
root_b = os.path.join(_tmp, "skills-b")
installed(root_b, "s0", md=100)
installed(root_b, "s1", md=120)
out = selfevolve.promote(proposal("fat2", md=4000), skills_dir=root_b, c=CFG)
check("B1 with TWO samples an oversized candidate is refused",
      out.get("ok") is False and "cost gate" in str(out.get("error")), out)

# ---- C: an empty category cannot be judged and says so ------------------------
root_c = os.path.join(_tmp, "skills-c")
out = selfevolve.promote(proposal("first", md=4000), skills_dir=root_c, c=CFG)
arch = os.path.join(root_c, "created", "first", "proposal.json")
_saved = json.load(open(arch, encoding="utf-8")) if os.path.exists(arch) else {}
check("C1 the FIRST install in a category is allowed",
      out.get("ok") is True, out)
check("C2 the record says the gate could not be priced",
      _saved.get("cost_basis") == "no-baseline", _saved.get("cost_basis"))
check("C3 the basis is on the return value too",
      out.get("cost_basis") == "no-baseline", out.get("cost_basis"))

# ---- D: three samples keep the old behaviour and name the basis --------------
root_d = os.path.join(_tmp, "skills-d")
for i, md in enumerate((100, 110, 120)):
    installed(root_d, "d%d" % i, md=md)
out = selfevolve.promote(proposal("lean", md=100), skills_dir=root_d, c=CFG)
check("D1 a normal-sized candidate passes against three samples",
      out.get("ok") is True, out)
check("D2 the basis names the sample count",
      out.get("cost_basis") == "median(n=3)", out.get("cost_basis"))
out = selfevolve.promote(proposal("fat3", md=4000), skills_dir=root_d, c=CFG)
check("D3 an outlier is still refused with three samples",
      out.get("ok") is False and "cost gate" in str(out.get("error")), out)

# ---- E: the operator may override, but the record names the bar it skipped ---
out = selfevolve.promote(proposal("fat4", md=4000), skills_dir=root_d, c=CFG,
                         human=True, reason="editorial choice")
_saved = json.load(open(os.path.join(root_d, "created", "fat4", "proposal.json"),
                        encoding="utf-8")) if out.get("ok") else {}
check("E1 the operator can still release an oversized candidate",
      out.get("ok") is True, out)
check("E2 the release names the cost bar it skipped",
      "cost" in (_saved.get("release_skipped") or []), _saved.get("release_skipped"))
check("E3 a hard gate is never claimed as skipped",
      "heldout" not in (_saved.get("release_skipped") or []),
      _saved.get("release_skipped"))

# ---- F: the old helper is gone (one owner, not two) --------------------------
check("F1 the zero-with-few-samples helper no longer exists",
      not hasattr(selfevolve, "_installed_cost_median"),
      [n for n in dir(selfevolve) if "cost" in n.lower()])

print("\n---\nv919: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
