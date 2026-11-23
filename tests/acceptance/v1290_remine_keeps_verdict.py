#!/usr/bin/env python3
"""v1290 — a re-mine must not overwrite what the loop already learned (RSI round 2).

Measured on the parent tree, three ways the automatic self-evolution pass spent
work and destroyed its own evidence:

  1. `draft()` rewrote `proposal.json` unconditionally, so every pass over the
     same pattern threw away `verify`, the consecutive-green streak and the
     recorded abstraction. With a patience bar above 1 (`min_green_streak`) the
     bar was UNREACHABLE on the automatic path: the streak was reset before it
     could be read.
  2. `pipeline()` called `synth`, which rewrites `check.py` unconditionally — so
     re-mining a draft the operator had edited replaced their verification with
     the generated one, although `ensure_check` (the documented single owner of
     the synth-if-missing rule) leaves a hand-written check alone.
  3. `evolve_once()` re-drafted and re-verified a pattern it had ALREADY
     installed on an earlier turn; `promote` could only refuse it as a clobber.

Contract:
  A a verified draft survives a re-draft: status, verdict, streak, bytes
  B the patience bar is reachable across passes (streak 1 -> 2), still verifying
  C a hand-written `check.py` is not overwritten by the pipeline
  D `evolve_once` skips an installed pattern and names it in the report
  E a proposed/rejected draft is STILL refreshed (no over-block)

Deterministic: no model, no network; the check runner, `mine` and `promote` are
injected. Run: python3 tests/acceptance/v1290_remine_keeps_verdict.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1290-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
from longrun.util import improve as IMP           # noqa: E402
from longrun.util import selfevolve as SE         # noqa: E402

registry._external_tools = lambda: {}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def prop_of(folder):
    try:
        with open(os.path.join(folder, "proposal.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def body_of(folder):
    try:
        with open(os.path.join(folder, "SKILL.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


GREEN = lambda folder, command: (True, "ok")     # noqa: E731
RED = lambda folder, command: (False, "boom")    # noqa: E731

PAT = ["fs.read", "fs.edit", "shell.exec"]

# ---- A: a verified verdict survives a re-draft ------------------------------
out = os.path.join(TMP, "drafts_a")
d = SE.draft(PAT, 3, out)
before_md = body_of(d)
SE.verify(d, runner=GREEN)
p = prop_of(d)
check("A0 fixture: the draft is verified", p.get("status") == "verified"
      and int(p.get("green_streak") or 0) == 1, p.get("status"))
stamp = (p.get("verify") or {}).get("artifact_sha256")
again = SE.draft(PAT, 9, out)
p2 = prop_of(again)
check("A1 the same folder is returned", again == d, (again, d))
check("A2 the status and the streak survive",
      p2.get("status") == "verified" and int(p2.get("green_streak") or 0) == 1,
      (p2.get("status"), p2.get("green_streak")))
check("A3 the verdict (and its digest) survive",
      (p2.get("verify") or {}).get("artifact_sha256") == stamp and bool(stamp),
      ((p2.get("verify") or {}).get("artifact_sha256"), stamp))
check("A4 the artifact bytes were not rewritten", body_of(d) == before_md,
      body_of(d)[:120])

# ---- B: the patience bar is reachable across passes -------------------------
out_b = os.path.join(TMP, "drafts_b")
PAT_B = ["fs.read", "fs.write", "shell.exec"]
BAR2 = {"min_green_streak": 2}
seen = []
_orig_promote = SE.promote


def _fake_promote(folder, **kw):
    streak = int((prop_of(folder).get("green_streak") or 0))
    seen.append(streak)
    return {"ok": streak >= 2, "rel": "skills/created/" + SE.slug(PAT_B)}


SE.promote = _fake_promote
try:
    r1 = SE.pipeline(PAT_B, out_b, 3, runner=GREEN, c=dict(BAR2))
    r2 = SE.pipeline(PAT_B, out_b, 3, runner=GREEN, c=dict(BAR2))
finally:
    SE.promote = _orig_promote
check("B1 the first pass verifies once and is held by the bar",
      seen and seen[0] == 1 and (r1.get("archived") or {}).get("ok") is False,
      (seen, r1.get("archived")))
check("B2 the second pass reaches the bar instead of resetting to 1",
      seen == [1, 2], seen)
check("B3 the second pass archives",
      (r2.get("archived") or {}).get("ok") is True, r2.get("archived"))

# ---- C: a hand-written check is not overwritten ----------------------------
out_c = os.path.join(TMP, "drafts_c")
PAT_C = ["fs.read", "fs.edit", "fs.write"]
d_c = SE.draft(PAT_C, 2, out_c)
with open(os.path.join(d_c, "check.py"), "w", encoding="utf-8") as f:
    f.write("# hand written verification\nprint('ok')\n")
SE.pipeline(PAT_C, out_c, 2, runner=GREEN)
check("C1 the operator's check still owns the file",
      "hand written verification" in
      open(os.path.join(d_c, "check.py"), encoding="utf-8").read(),
      open(os.path.join(d_c, "check.py"), encoding="utf-8").read()[:160])

# ---- D: an installed pattern is skipped, not re-verified -------------------
root = os.environ["LONGRUN_SKILLS_DIR"]
PAT_INSTALLED = ["fs.read", "shell.exec", "fs.write"]
PAT_FRESH = ["shell.exec", "fs.read", "fs.write"]
os.makedirs(os.path.join(root, "created", SE.slug(PAT_INSTALLED)), exist_ok=True)
with open(os.path.join(root, "created", SE.slug(PAT_INSTALLED), "SKILL.md"),
          "w", encoding="utf-8") as f:
    f.write("# installed\n")
check("D0 fixture: the pattern reads as installed",
      callable(getattr(SE, "skill_installed", None))
      and SE.skill_installed(PAT_INSTALLED) is True
      and SE.skill_installed(PAT_FRESH) is False
      and SE.skill_installed(PAT_INSTALLED, category="core") is False)

calls = []


def _fake_pipe(pattern, out_dir, support=0, **kw):
    calls.append(list(pattern))
    return {"ok": True, "dir": SE.draft(pattern, support, out_dir) or "",
            "verify": {"green": True}, "archived": None}


_orig_mine, _orig_pipe, _orig_cfg = SE.mine, SE.pipeline, SE.cfg


def _cfg(override=None):
    base = dict(_orig_cfg(override))
    base.update({"forge_on_evolve": False, "abstract_on_evolve": False,
                 "promote_per_run": 1})
    return base


SE.mine = lambda *a, **kw: [{"pattern": list(PAT_INSTALLED), "support": 5},
                            {"pattern": list(PAT_FRESH), "support": 4}]
SE.pipeline = _fake_pipe
SE.cfg = _cfg
try:
    reps = IMP.evolve_once()
finally:
    SE.mine, SE.pipeline, SE.cfg = _orig_mine, _orig_pipe, _orig_cfg
check("D1 only the not-yet-installed pattern reaches the pipeline",
      calls == [PAT_FRESH], calls)
check("D2 the report names the installed pattern as skipped",
      [r for r in reps if r.get("skipped") == "already installed"
       and r.get("pattern") == PAT_INSTALLED], reps)
check("D3 the skipped row claims no new install",
      all(not r.get("rel") for r in reps if r.get("skipped")), reps)

# ---- E: no over-block — a rejected draft is refreshed ---------------------
out_e = os.path.join(TMP, "drafts_e")
PAT_E = ["fs.read", "web.fetch", "fs.write"]
d_e = SE.draft(PAT_E, 2, out_e)
SE.verify(d_e, runner=RED)
check("E0 fixture: the draft is rejected", prop_of(d_e).get("status") == "rejected",
      prop_of(d_e).get("status"))
SE.draft(PAT_E, 7, out_e)
p_e = prop_of(d_e)
check("E1 a draft with no green verdict is still refreshed",
      p_e.get("status") == "proposed" and int(p_e.get("support") or 0) == 7,
      (p_e.get("status"), p_e.get("support")))

print("---")
print("v1290: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
