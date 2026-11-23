#!/usr/bin/env python3
"""v1294 — the retention constraint with recorded evidence (RSI I-7).

I-4 measured a promoted skill's own habit before/after. arXiv:2611.25380 Eq. 4
asks the other half: a specialisation may improve its target and must not destroy
prior capability (the paper's Table 4 checks the off-target columns). I-5 built
the predicate (`domain_adapter.retention`) but nothing fed it; this round wires
it to the runs the harness already records — the target habit versus the REST of
the known-outcome runs, over the same cut `promote()` stamped.

Contract:
  A a target gain with the rest unchanged is retained
  B a target gain does not hide a drop in the rest (the regression is named)
  C with no target runs after the cut, the rest is still checked
  D a stated tolerance can absorb a small drop
  E `installed_impact()` carries the retention verdict per skill and in totals
  F a legacy artifact says it has no baseline instead of inventing one
  G unknown-outcome runs are not evidence, and a target run is not "the rest"

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1294_skill_retention.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1294-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
from longrun.util import selfevolve as SE         # noqa: E402

registry._external_tools = lambda: {}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


PAT = ["fs.read", "fs.edit", "shell.exec"]
OTHER = ["web.search", "fs.write", "memory.recall"]
GREEN = lambda folder, command: (True, "ok")      # noqa: E731

def retention_of(folder, **kw):
    """Call the I-7 entry point, or report it missing (the test stays runnable
    against the parent tree, so its RED profile names every absent behaviour)."""
    fn = getattr(SE, "skill_retention", None)
    if not callable(fn):
        return {"ok": False, "error": "missing-api: skill_retention",
                "retention": {}, "target": {}, "rest": {}}
    return fn(folder, **kw)


# ---- fixture: one promoted skill, whose install time is the cut --------------
SK = os.environ["LONGRUN_SKILLS_DIR"]
out = os.path.join(TMP, "drafts")
d = SE.draft(PAT, 3, out)
SE.ensure_check(d)
SE.verify(d, runner=GREEN)
pr = SE.promote(d, skills_dir=SK, human=True, reason="I-7 acceptance fixture")
check("A0 fixture: the skill is installed", pr.get("ok") is True, pr)
landed = os.path.join(SK, "created", SE.slug(PAT))
with open(os.path.join(landed, "proposal.json"), encoding="utf-8") as f:
    TS = float((json.load(f).get("impact_baseline") or {}).get("ts") or 0)
check("A1 fixture: the install time is stamped", TS > 0, TS)


def write_history(rows):
    data = {}
    for i, (tools, ts, outcome) in enumerate(rows):
        data["run%d" % i] = {"tools": list(tools), "ts": float(ts),
                             "outcome": outcome}
    with open(SE._history_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)


def rows(target_before, target_after, rest_before, rest_after):
    got = []
    for i, oc in enumerate(target_before):
        got.append((PAT, TS - 1000 + i, oc))
    for i, oc in enumerate(target_after):
        got.append((PAT, TS + 10 + i, oc))
    for i, oc in enumerate(rest_before):
        got.append((OTHER, TS - 900 + i, oc))
    for i, oc in enumerate(rest_after):
        got.append((OTHER, TS + 20 + i, oc))
    return got


# ---- A: target improves, the rest is unchanged ------------------------------
write_history(rows(["ok", "error", "error"], ["ok", "ok", "ok"],
                   ["ok", "ok", "ok", "error"], ["ok", "ok", "ok", "ok"]))
got = retention_of(landed)
check("A2 the target's own rate improved",
      got["target"]["before"]["rate"] == 0.3333
      and got["target"]["after"]["rate"] == 1.0, got.get("target"))
check("A3 the rest did not regress, so the change is retained",
      got.get("ok") is True and got["retention"]["regressions"] == [], got.get("retention"))
check("A4 both domains were compared",
      sorted(r["domain"] for r in got["retention"]["compared"]) == ["rest", "target"],
      got["retention"].get("compared"))

# ---- B: a target gain does not hide a drop in the rest ---------------------
write_history(rows(["ok", "error", "error"], ["ok", "ok", "ok"],
                   ["ok", "ok", "ok", "ok"], ["error", "error", "error", "error"]))
got_b = retention_of(landed)
check("B1 the target still improved",
      got_b["target"]["after"]["rate"] == 1.0, got_b.get("target"))
check("B2 the change is NOT retained",
      got_b.get("ok") is False, got_b.get("retention"))
check("B3 the regression names the rest, with both rates",
      [(r["domain"], r["before"], r["after"])
       for r in got_b["retention"]["regressions"]] == [("rest", 1.0, 0.0)],
      got_b["retention"].get("regressions"))
check("B4 the rest's own rows are reported",
      got_b["rest"]["before"]["runs"] == 4 and got_b["rest"]["after"]["runs"] == 4,
      got_b.get("rest"))

# ---- C: no target runs after the cut, the rest is still checked ------------
write_history(rows(["ok", "ok"], [], ["ok", "ok", "ok", "ok"],
                   ["ok", "error", "error", "error"]))
got_c = retention_of(landed)
check("C1 an unexercised target is skipped, not called retained",
      got_c["target"]["after"]["runs"] == 0
      and "target" in got_c["retention"]["skipped"], got_c.get("retention"))
check("C2 the rest's regression still refuses the change",
      got_c.get("ok") is False
      and got_c["retention"]["regressions"][0]["domain"] == "rest",
      got_c.get("retention"))

# ---- D: a stated tolerance absorbs a small drop ---------------------------
write_history(rows(["ok", "ok", "ok"], ["ok", "ok", "ok"],
                   ["ok", "ok", "ok", "ok"], ["ok", "ok", "ok", "error"]))
check("D1 the default tolerance refuses a 25-point drop",
      retention_of(landed).get("ok") is False)
check("D2 a 0.5 tolerance absorbs it",
      retention_of(landed, tolerance=0.5).get("ok") is True)

# ---- E: the aggregate carries the verdict ---------------------------------
write_history(rows(["ok", "ok", "ok"], ["ok", "ok", "ok"],
                   ["ok", "ok", "ok", "ok"], ["ok", "ok", "ok", "ok"]))
agg = SE.installed_impact(skills_dir=SK)
row = [r for r in agg.get("skills") or [] if r.get("name") == SE.slug(PAT)]
check("E1 the row carries the retention verdict",
      row and row[0].get("retained") is True
      and (row[0].get("retention") or {}).get("regressions") == [], row)
check("E2 the totals count it",
      agg.get("retention") == {"retained": 1, "regressed": 0, "not-measured": 0},
      agg.get("retention"))
write_history(rows(["ok", "ok", "ok"], ["ok", "ok", "ok"],
                   ["ok", "ok", "ok", "ok"], ["error", "error", "error", "error"]))
agg_b = SE.installed_impact(skills_dir=SK)
check("E3 a regressed skill is counted as regressed",
      agg_b.get("retention", {}).get("regressed") == 1, agg_b.get("retention"))

# ---- F: a legacy artifact is honestly unmeasured --------------------------
legacy = os.path.join(SK, "created", "legacy")
os.makedirs(legacy, exist_ok=True)
with open(os.path.join(legacy, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "legacy", "pattern": PAT, "status": "archived"}, f)
old = retention_of(legacy)
check("F1 no baseline is named as such",
      old.get("ok") is False and "baseline" in str(old.get("error")), old)

# ---- G: unknown outcomes are not evidence; a target run is not "the rest" --
write_history([(PAT, TS - 100, "ok"), (PAT, TS - 90, "ok"),
               (PAT, TS + 10, "ok"), (PAT, TS + 20, ""),
               (OTHER, TS + 30, ""), (OTHER, TS + 40, ""),
               (OTHER, TS + 50, ""),
               # the rest, before the cut: one success and one run that CONTAINS
               # the pattern and failed — that failed run belongs to the target
               (OTHER, TS - 80, "ok"), (PAT + OTHER, TS - 70, "error")])
got_g = retention_of(landed)
check("G1 three unknown-outcome rest runs are not a 0% regression",
      got_g["rest"]["after"]["runs"] == 0, got_g.get("rest"))
check("G2 a run containing the pattern is not counted in the rest",
      got_g["rest"]["before"]["runs"] == 1, got_g.get("rest"))
check("G3 with nothing comparable in the rest, only the target is compared",
      got_g.get("ok") is True and got_g["retention"]["compared"] == [
          {"domain": "target", "before": 0.6667, "after": 1.0, "delta": 0.3333}],
      got_g.get("retention"))

print("---")
print("v1294: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
