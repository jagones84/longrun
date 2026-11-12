#!/usr/bin/env python3
"""v966 — the learning loop can RETIRE a skill it installed and never reopened.

`skills.discovery()["never_opened"]` existed with no consumer: the RSI loop
installed skills but never removed one. This retires (moves aside, never
deletes) the machine-created skills that were never opened and are older than
`selfevolve.retire_days` (14, the bar used for forged tools), through the SAME
`_retire_skill` path a superseded promotion already uses.

  A) a dry run lists the eligible skill and touches nothing;
  B) a skill that was OPENED (helped > 0) is never a candidate;
  C) a skill in another category is never a candidate;
  D) a young skill is never a candidate;
  E) a real run moves the folder under skills/_retired/created/<name>-* with a
     ledger line carrying `prev_sha256`, and the loader no longer sees it;
  F) the tool `skills {"action":"retire"}` is a dry run unless `confirm` is set.

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v966_skill_retire.py
"""
import glob
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v966-")
SKILLS = os.path.join(TMP, "skills")
os.environ["LONGRUN_SKILLS_DIR"] = SKILLS
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_MEMORY_ATTRIBUTION"] = os.path.join(TMP, "attr.json")
sys.path.insert(0, os.path.join(REPO, "src"))

NOW = time.time()
OLD = NOW - 30 * 86400.0


def skill(cat, name, body, mtime=OLD):
    d = os.path.join(SKILLS, cat, name)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "SKILL.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.utime(p, (mtime, mtime))
    return d


def md(name, desc):
    return "---\nname: %s\ndescription: %s\n---\n\n# %s\n\nDo the thing.\n" % (
        name, desc, name)


old_dir = skill("created", "old-never-opened", md("old-never-opened", "Old and never opened."))
opened_dir = skill("created", "old-but-opened", md("old-but-opened", "Old but opened once."))
ops_dir = skill("ops", "old-ops", md("old-ops", "Old, in another category."))
young_dir = skill("created", "young-never-opened",
                  md("young-never-opened", "Never opened but just installed."), mtime=NOW)

from longrun.memory import attribution  # noqa: E402
from longrun.memory import skills as S  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

attribution.note(["skill:old-but-opened"], ["skill:old-but-opened"])

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------------------- A: dry run ----
out = selfevolve.retire_unused_skills(days=14, dry_run=True, now=NOW)
check("A1 the old, never-opened created skill is the only candidate",
      out.get("eligible") == 1 and out.get("candidates") == ["old-never-opened"], out)
check("A2 a dry run removes nothing and says so",
      out.get("removed") == [] and out.get("dry_run") is True, out)
check("A3 the folder is still on disk", os.path.isdir(old_dir), old_dir)
check("A4 the report names the default category and the bar",
      out.get("category") == "created" and out.get("days") == 14, out)

# ---------------------------------------------- B/C/D: exclusions, real run ----
out = selfevolve.retire_unused_skills(days=14, dry_run=False, now=NOW)
check("B1 an opened skill is never a candidate",
      "old-but-opened" not in (out.get("candidates") or []) and os.path.isdir(opened_dir),
      out.get("candidates"))
check("C1 a skill in another category is never a candidate",
      "old-ops" not in (out.get("candidates") or []) and os.path.isdir(ops_dir),
      out.get("candidates"))
check("D1 a young skill is never a candidate",
      "young-never-opened" not in (out.get("candidates") or [])
      and os.path.isdir(young_dir), out.get("candidates"))

# --------------------------------------------------------- E: real retirement --
removed = [r for r in (out.get("removed") or []) if r.get("name") == "old-never-opened"]
check("E1 the eligible skill was retired, not deleted",
      len(removed) == 1 and removed[0].get("ok") is True
      and bool(removed[0].get("retired_to")), out.get("removed"))
check("E2 the folder left its category box", not os.path.isdir(old_dir), old_dir)
moved = glob.glob(os.path.join(SKILLS, "_retired", "created", "old-never-opened-*"))
check("E3 the folder lives under skills/_retired/created/<name>-<stamp>",
      len(moved) == 1 and os.path.isfile(os.path.join(moved[0], "SKILL.md")), moved)
ledger = os.path.join(SKILLS, "_retired", "ledger.jsonl")
rows = []
if os.path.isfile(ledger):
    with open(ledger, encoding="utf-8") as fh:
        rows = [json.loads(ln) for ln in fh if ln.strip()]
check("E4 the ledger records who/why at the previous content digest",
      len(rows) == 1 and rows[0].get("name") == "old-never-opened"
      and rows[0].get("prev_sha256")
      and rows[0].get("by") == "selfevolve.retire_unused_skills", rows)
check("E5 the loader no longer sees the retired skill",
      "old-never-opened" not in {s["name"] for s in S.list_skills(reload=True)},
      [s["name"] for s in S.list_skills()])

# ------------------------------------------------------------ F: the tool ----
tool_out = T._skills({"action": "retire"}, None)
check("F1 action=retire is a dry run without confirm",
      tool_out.get("ok") is True and tool_out.get("dry_run") is True
      and tool_out.get("exit_code") == 0, tool_out)
check("F2 it lists what it would retire and removes nothing",
      tool_out.get("candidates") == [] and tool_out.get("removed") == []
      and "dry run" in str(tool_out.get("stdout") or "").lower(), tool_out)

_real = selfevolve.retire_unused_skills
selfevolve.retire_unused_skills = lambda **_kw: {"ok": False, "error": "boom"}
try:
    bad = T._skills({"action": "retire", "confirm": True}, None)
finally:
    selfevolve.retire_unused_skills = _real
check("F3 a failed report is an error, never an exception",
      bad.get("ok") is False and bad.get("exit_code") == 1
      and bad.get("error") == "boom", bad)

print("---")
passed = sum(results)
print("v966: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
