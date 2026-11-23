#!/usr/bin/env python3
"""v1291 — a promoted skill is measured on the runs that FOLLOW it (RSI round 3).

`forged_usage` answers "was the change USED after it landed?" for a forged tool.
A promoted SKILL had no such read: the loop could install a procedure and never
look at whether the habit behind it became more reliable. arXiv 2610.34938 names
exactly that gap ("harness self-evolution needs ways to establish whether a
change helps on later tasks").

Built: `impact(pattern, since)` compares the outcome rate of the SAME recorded
pattern before and after a cut (known outcomes only; `unknown` is not evidence);
`promote()` stamps the install time as `impact_baseline` on the artifact;
`skill_impact(dir)` and `installed_impact()` read it back. Read-only, no model.

Contract:
  A the six verdicts: improved / worse / flat / not-enough-data / no-runs-since /
    no-baseline, from a fixture history
  B unknown-outcome runs are never counted as success or failure
  C `promote` stamps the baseline (pattern + install time) on the installed copy
  D `skill_impact` measures the installed skill against the runs after that stamp
  E an artifact promoted before the stamp says so instead of inventing a baseline
  F `installed_impact` aggregates every created skill, naming the unmeasured ones

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1291_promotion_impact.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1291-")
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
SINCE = 2_000_000_000.0


def _call(name, *args, **kwargs):
    """Call an I-4 entry point, or report it missing (the test stays runnable
    against the parent tree, so its RED profile names every absent behaviour)."""
    fn = getattr(SE, name, None)
    if not callable(fn):
        return {"ok": False, "error": "missing-api: %s" % name, "verdict": ""}
    return fn(*args, **kwargs)


def write_history(rows):
    data = {}
    for i, row in enumerate(rows):
        data["run%d" % i] = {"tools": list(row[0]), "ts": float(row[1]),
                             "outcome": str(row[2])}
    with open(SE._history_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)


def verdict(before, after):
    """before/after are lists of (outcome) for the same pattern."""
    rows = []
    for i, oc in enumerate(before):
        rows.append((PAT, SINCE - 1000 + i, oc))
    for i, oc in enumerate(after):
        rows.append((PAT, SINCE + 10 + i, oc))
    write_history(rows)
    return _call("impact", PAT, since=SINCE)


# ---- A: the six verdicts ----------------------------------------------------
got = verdict(["ok", "ok", "error"], ["ok", "ok", "ok"])
check("A1 a habit that became reliable reads `improved`",
      got["verdict"] == "improved" and got["before"]["rate"] == 0.6667
      and got["after"]["rate"] == 1.0, got)
got = verdict(["ok", "ok", "ok"], ["error", "error", "error"])
check("A2 a habit that got worse reads `worse`", got["verdict"] == "worse", got)
got = verdict(["ok", "error", "ok"], ["ok", "error", "ok"])
check("A3 an unchanged rate reads `flat`",
      got["verdict"] == "flat" and got["before"]["rate"] == 0.6667
      and got["after"]["rate"] == 0.6667, got)
got = verdict(["ok", "ok", "ok"], ["ok", "ok"])
check("A4 too few runs after the change is `not-enough-data`",
      got["verdict"] == "not-enough-data" and got["after"]["runs"] == 2, got)
got = verdict(["ok", "error"], [])
check("A5 a change nobody exercised is `no-runs-since`",
      got["verdict"] == "no-runs-since", got)
got = verdict([], ["ok", "ok", "ok"])
check("A6 nothing to compare against is `no-baseline`",
      got["verdict"] == "no-baseline", got)
# `since=None` means "the install is happening now": every recorded run is before
# the cut, so there is nothing measurable after it (not "no baseline").
_past = time.time() - 1000
write_history([(PAT, _past, "ok"), (PAT, _past + 10, "ok")])
got = _call("impact", PAT, since=None)
check("A7 `since=None` means the cut is NOW (no after-runs yet)",
      got["verdict"] == "no-runs-since" and got["before"]["runs"] == 2, got)

# ---- B: unknown runs are not evidence --------------------------------------
write_history([(PAT, SINCE - 100, "ok"), (PAT, SINCE - 90, "ok"),
               (PAT, SINCE - 80, "ok"), (PAT, SINCE + 10, ""),
               (PAT, SINCE + 20, ""), (PAT, SINCE + 30, ""),
               (OTHER, SINCE + 40, "ok")])
got = SE.impact(PAT, since=SINCE)
check("B1 three unknown-outcome runs are not three successes",
      got["verdict"] == "no-runs-since" and got["after"]["runs"] == 0, got)
check("B2 a different pattern's runs are not counted",
      got["before"]["runs"] == 3, got)

# ---- C: promote stamps the baseline ----------------------------------------
GREEN = lambda folder, command: (True, "ok")      # noqa: E731
SK = os.environ["LONGRUN_SKILLS_DIR"]
out = os.path.join(TMP, "drafts")
d = SE.draft(PAT, 3, out)
SE.ensure_check(d)
rep = SE.verify(d, runner=GREEN)
check("C0 fixture: the draft verifies green", rep.get("green") is True, rep)
pr = SE.promote(d, skills_dir=SK, human=True, reason="I-4 acceptance fixture")
check("C1 the operator release installs the skill", pr.get("ok") is True, pr)
landed = os.path.join(SK, "created", SE.slug(PAT))
try:
    with open(os.path.join(landed, "proposal.json"), encoding="utf-8") as f:
        inst = json.load(f)
except (OSError, ValueError):
    inst = {}
base = inst.get("impact_baseline") if isinstance(inst.get("impact_baseline"), dict) else {}
check("C2 the installed copy carries the pattern and the install time",
      base.get("pattern") == PAT and float(base.get("ts") or 0) > 0, base)
check("C3 the draft record carries the same baseline",
      (json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8"))
       .get("impact_baseline") or {}).get("ts") == base.get("ts"),
      base)

# ---- D: the installed skill is measured against the runs after the stamp ---
ts = float(base.get("ts") or 0)
write_history([(PAT, ts - 200, "ok"), (PAT, ts - 100, "error"),
               (PAT, ts + 10, "ok"), (PAT, ts + 20, "ok"),
               (PAT, ts + 30, "ok")])
one = _call("skill_impact", landed)
check("D1 the installed skill reads `improved`", one.get("verdict") == "improved", one)
check("D2 the verdict names the artifact", one.get("name") == SE.slug(PAT), one)
check("D3 the baseline is the installed one, not the draft's",
      one.get("since") == round(ts, 3), one.get("since"))

# ---- E: an artifact promoted before the stamp says so ----------------------
old = os.path.join(TMP, "old_skill")
os.makedirs(old, exist_ok=True)
with open(os.path.join(old, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "old", "pattern": PAT, "status": "archived"}, f)
old_got = _call("skill_impact", old)
check("E1 a legacy artifact is honestly unmeasured",
      old_got.get("ok") is False and "baseline" in str(old_got.get("error")), old_got)

# ---- F: the aggregate names what is not measured --------------------------
os.makedirs(os.path.join(SK, "created", "legacy"), exist_ok=True)
with open(os.path.join(SK, "created", "legacy", "proposal.json"),
          "w", encoding="utf-8") as f:
    json.dump({"name": "legacy", "pattern": PAT, "status": "archived"}, f)
agg = _call("installed_impact", skills_dir=SK)
check("F1 every created skill is listed", agg.get("count") == 2, agg)
check("F2 the measured one keeps its verdict",
      [r for r in agg.get("skills") or []
       if r.get("name") == SE.slug(PAT) and r.get("verdict") == "improved"], agg)
check("F3 the unmeasured one is named, not dropped",
      agg.get("verdicts", {}).get("not-measured") == 1, agg.get("verdicts"))

print("---")
print("v1291: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
