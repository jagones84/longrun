#!/usr/bin/env python3
"""v714 — a harness-proposed skill can be admitted and installed.

The Harness tab DOES have a self-evolve half: a scoped editor may propose a
`skill`, the matched whole run really tests it at
`skills/<category>/<name>/SKILL.md`, and the snapshot/library see it. But
`cycle._admit` answered "no approvable component" for anything that was not a
project rule or a Matrix artifact, so a tested skill could never be installed —
the mining lane could install and the evidence lane could not.

  A  admission still needs a verified matched experiment
  B  a skill-only bundle becomes ONE scope=skill proposal whose artifacts are
     the exact bytes, hashed, at the path the run tested
  C  a mixed bundle still refuses (one experiment, one destination)
  D  approval installs those bytes through `skills.install_skill_file`:
     atomic, hash-checked, never clobbering
  E  the approval queue says a content-bound skill IS approvable
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v714-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(TMP, "skills")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402
from longrun.harness import cycle  # noqa: E402
from longrun.tools import approvals  # noqa: E402
from longrun.memory import skills as skills_mod  # noqa: E402

results = []
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


BASE = "a" * 64
VAR = "b" * 64
EVIDENCE = {"scope": "matched_container_run", "snapshot_digest": VAR}
GROUP = {"digest": BASE,
         "reference_run": {"cleanup_verified": True, "digest": BASE, "run_id": "ref-1"},
         "reference": {"evidence": {"scope": "matched_container_run",
                                    "snapshot_digest": BASE}}}
REPORT = {"decision": "selected", "contrast": {"verdict": "improved"},
          "successor": {"digest": VAR, "repeats": 2,
                        "run": {"cleanup_verified": True, "digest": VAR, "run_id": "var-1"},
                        "record": {"evidence": EVIDENCE}}}
SKILL = "# use the narrow loop\n\nRun the narrow loop when the task is a single file.\n"

# ------------------------------------- A: evidence is still required --------
empty = dict(REPORT, successor={"digest": VAR, "run": {"digest": VAR}})
r = cycle._admit(GROUP, empty, [{"kind": "skill", "name": "narrow-loop", "content": SKILL}])
check("A1 a skill candidate without a verified experiment is refused",
      r.get("ok") is False and "verified" in str(r.get("reason")), r)

# ------------------------------------- B: a skill-only bundle is admitted ---
r = cycle._admit(GROUP, REPORT, [{"kind": "skill", "name": "narrow-loop", "content": SKILL}])
art = (r.get("artifacts") or [])
check("B1 the skill-only bundle is admitted", r.get("ok") is True and r.get("id"), r)
check("B2 it names the path the run tested", art == ["skills/harness/narrow-loop/SKILL.md"], art)
rec = improve.get_proposal(str(r.get("id") or "")) or {}
arts = rec.get("artifacts") or []
check("B3 the proposal is scope=skill with the exact bytes",
      rec.get("scope") == "skill" and len(arts) == 1
      and arts[0].get("content") == SKILL, rec)
check("B4 the artifact is hash-bound to what was tested",
      arts and arts[0].get("sha256") == hashlib.sha256(SKILL.encode("utf-8")).hexdigest(), arts)
check("B5 it carries the matched-run evidence, not a summary",
      (rec.get("experiment") or {}).get("verified") is True
      and len((rec.get("experiment") or {}).get("runs") or []) == 2, rec.get("experiment"))

# ------------------------------------- C: one destination per experiment ----
r2 = cycle._admit(GROUP, REPORT, [{"kind": "skill", "name": "narrow-loop", "content": SKILL},
                                 {"kind": "guardrail", "content": "always cite the file"}])
check("C1 a skill+rule bundle refuses instead of attributing both",
      r2.get("ok") is False and "destinations" in str(r2.get("reason")), r2)
r3 = cycle._admit(GROUP, REPORT, [{"kind": "skill", "name": "narrow-loop", "content": "   "}])
check("C2 an empty skill candidate is refused", r3.get("ok") is False, r3)

# ------------------------------------- D: approval installs those bytes ----
got = improve.decide(str(r.get("id") or ""), "approve")
installed = os.path.join(TMP, "skills", "harness", "narrow-loop", "SKILL.md")
check("D1 approving installs the tested skill", got.get("ok") is True
      and got.get("installed_to"), got)
check("D2 the installed file is byte-identical",
      os.path.isfile(installed)
      and open(installed, encoding="utf-8").read() == SKILL, installed)
check("D3 the proposal is marked approved", (got.get("status") == "approved"), got.get("status"))

# a second install of the same name must not clobber
again = skills_mod.install_skill_file("harness", "narrow-loop", "other")
check("D4 an existing skill is never overwritten", again.get("ok") is False
      and "exists" in str(again.get("error")), again)

# a tampered artifact is refused before anything is written
bad = improve.propose("skill", "tampered", origin="agent", artifacts=[
    {"kind": "skill_file", "name": "evil", "content": "x",
     "target": "skills/harness/evil/SKILL.md",
     "sha256": "0" * 64}])
got = improve.decide(str(bad.get("id") or ""), "approve")
check("D5 a changed artifact is refused", got.get("ok") is False
      and "changed" in str(got.get("error")), got)
check("D6 nothing was written for the tampered artifact",
      not os.path.exists(os.path.join(TMP, "skills", "harness", "evil")), "")
esc = improve.propose("skill", "escape", origin="agent", artifacts=[
    {"kind": "skill_file", "name": "x", "content": "x", "target": "skills/../etc/SKILL.md",
     "sha256": hashlib.sha256(b"x").hexdigest()}])
got = improve.decide(str(esc.get("id") or ""), "approve")
check("D7 an escaping target is refused", got.get("ok") is False
      and "target" in str(got.get("error")), got)

# ------------------------------------- E: the queue and the card agree ------
view = approvals._improvement_view(rec)
check("E1 the approval queue lets a content-bound skill be approved",
      view.get("can_approve") is True and not view.get("blocked_reason"), view)
bare = improve.propose("skill", "no bundle")
view = approvals._improvement_view(bare)
check("E2 a skill proposal with no draft and no bundle is still blocked",
      view.get("can_approve") is False and "no draft" in str(view.get("blocked_reason")), view)
check("E3 the card states what approving installs",
      "verified SKILL.md the matched run tested" in UI, "")

print("\n---\nv714: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
