#!/usr/bin/env python3
"""v598 (RED) — Maka thresholded release: eval promotion bar + patience.

Maka releases only when evals cross a bar, with patience (no release on a
single lucky green). Longrun's evolve pipeline promotes on the FIRST green
verify (`promote_if_green`) and `promote()` asks only "verified?" — a flaky
check.py passing once archives a skill. The slice (extends M9):

- `selfevolve.verify()` persists `green_streak` in proposal.json (+1 on
  green, reset to 0 on red).
- `STAGE2_DEFAULTS["min_green_streak"] = 1` (today's behavior) + `promote()`
  refuses below the bar with a patience error (invalid bar configs fail
  closed, rate_limit precedent). A legacy `verified` proposal without a
  streak key counts as 1 — the verify that set the status WAS a green.
- `pipeline()` unchanged: with the default bar a single green still
  archives (no regression); a raised bar holds the release.

Deterministic: isolated dirs, injected runner, held-out gate off,
no model, no network.
Run: python3 tests/acceptance/v598_thresholded_release.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="lr-streak-v598-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_DATA_DIR"] = _tmp
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(_tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _prop(out, name, status="proposed", streak=None):
    d = os.path.join(out, name)
    os.makedirs(d, exist_ok=True)
    p = {"status": status, "name": name}
    if streak is not None:
        p["green_streak"] = streak
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(p, f)
    return d


def _read(d):
    with open(os.path.join(d, "proposal.json"), encoding="utf-8") as f:
        return json.load(f)


GREEN = lambda s, c: (True, "ok")  # noqa: E731
RED = lambda s, c: (False, "boom")  # noqa: E731
SKILLS = os.path.join(_tmp, "skills")
BAR2 = {"min_green_streak": 2, "category": "created"}

# ---- A: the streak is tracked -------------------------------------------------
check("A1 default bar preserves today's single-green release",
      selfevolve.cfg().get("min_green_streak") == 1,
      repr(selfevolve.cfg().get("min_green_streak")))
d = _prop(_tmp, "streaky")
selfevolve.verify(d, runner=GREEN)
check("A2 green verify opens streak 1", _read(d).get("green_streak") == 1,
      repr(_read(d).get("green_streak")))
selfevolve.verify(d, runner=GREEN)
check("A3 consecutive green extends the streak", _read(d).get("green_streak") == 2,
      repr(_read(d).get("green_streak")))
selfevolve.verify(d, runner=RED)
r = _read(d)
check("A4 red resets the streak and rejects",
      r.get("green_streak") == 0 and r.get("status") == "rejected", repr(r))

# ---- B: the bar gates promotion -----------------------------------------------
p1 = _prop(_tmp, "impatient", status="verified", streak=1)
res = selfevolve.promote(p1, skills_dir=SKILLS, c=dict(BAR2))
check("B1 streak below the bar is refused with a patience error",
      res.get("ok") is False and "streak" in str(res.get("error") or "").lower(),
      repr(res.get("error"))[:120])
check("B2 nothing archived below the bar",
      not os.path.exists(os.path.join(SKILLS, "created", "impatient")))
p2 = _prop(_tmp, "patient", status="verified", streak=2)
res = selfevolve.promote(p2, skills_dir=SKILLS, c=dict(BAR2))
check("B3 streak at the bar archives",
      res.get("ok") is True
      and os.path.isdir(os.path.join(SKILLS, "created", "patient")),
      repr({k: res.get(k) for k in ("ok", "error")}))
p3 = _prop(_tmp, "legacy", status="verified")
res = selfevolve.promote(p3, skills_dir=SKILLS, c={"min_green_streak": 1})
check("B4 legacy verified proposal (no streak key) still releases at bar 1",
      res.get("ok") is True, repr({k: res.get(k) for k in ("ok", "error")}))
p4 = _prop(_tmp, "badbar", status="verified", streak=5)
res = selfevolve.promote(p4, skills_dir=SKILLS, c={"min_green_streak": "abc"})
check("B5 invalid bar config fails closed",
      res.get("ok") is False and "min_green_streak" in str(res.get("error") or ""),
      repr(res.get("error"))[:120])

# ---- C: the pipeline honors the bar --------------------------------------------
out1 = os.path.join(_tmp, "pipe1")
rep = selfevolve.pipeline(["fs.read", "fs.edit"], out1, 3, runner=GREEN,
                          skills_dir=SKILLS)
check("C1 default pipeline still archives on a single green",
      rep.get("ok") is True and (rep.get("archived") or {}).get("ok") is True,
      repr({k: rep.get(k) for k in ("ok",)}))
out2 = os.path.join(_tmp, "pipe2")
rep = selfevolve.pipeline(["fs.read", "fs.write"], out2, 3, runner=GREEN,
                          skills_dir=SKILLS, c=dict(BAR2))
check("C2 raised bar holds the release after one green",
      rep.get("ok") is True and (rep.get("archived") or {}).get("ok") is False,
      repr(rep.get("archived"))[:120])

# ---- D: the bar is operator-settable -----------------------------------------------
from longrun.core import api_v02  # noqa: E402


def _nocall(fn, *a, **k):
    try:
        return None, fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return repr(e), None


err, res = _nocall(api_v02.update_policy, {"selfevolve": {"min_green_streak": 3}})
check("D1 bar settable via API",
      err is None and (res or {}).get("ok") is True
      and (res or {}).get("selfevolve", {}).get("min_green_streak") == 3,
      err or repr(res)[:120])
err, res = _nocall(api_v02.update_policy, {"selfevolve": {"min_green_streak": "abc"}})
check("D2 invalid bar rejected cleanly (no raise, no drop)",
      err is None and (res or {}).get("ok") is False, err or repr(res)[:120])

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
