#!/usr/bin/env python3
"""v717 — the installed skill says what it is FOR (and is not a draft any more).

Found by running the whole loop live: approving a mined draft installed
`skills/created/<name>/SKILL.md` copied from the DRAFT — the file inside the
installed skill still read "DRAFT — not verified, not archived" and told the
agent to verify/promote the very folder it was already living in, while the
purpose the operator wrote was dropped on the floor.

  A  a promoted skill states the purpose, the sequence and its REAL state
  B  without a purpose it does not invent one (it says so)
  C  the archived folder keeps the machine artifacts, replaces only SKILL.md
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v717-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(TMP, "skills")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.memory import skills as skills_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


PATTERN = ["fs.read", "fs.edit", "shell"]
OUT = os.path.join(TMP, "drafts")
d = SE.draft(PATTERN, 3, OUT)
SE.ensure_check(d)
SE.verify(d, runner=lambda _d, _c: (True, "ok"))
PURPOSE = "Read a file, edit it in place, then run the project's check."
# human=True is the operator path (approval in the WebUI): the sandbox check still
# has to be green, the sealed judge suite is not required — same as `decide`.
got = SE.promote(d, human=True, purpose=PURPOSE)
md = ""
if got.get("ok"):
    md = open(os.path.join(got["path"], "SKILL.md"), encoding="utf-8").read()

check("A1 promote succeeds", got.get("ok") is True, got)
check("A2 the skill states the purpose", PURPOSE in md, md[:200])
check("A3 it is no longer called a draft",
      "DRAFT" not in md and "not archived" not in md, md[:200])
check("A4 it says where it really lives",
      "ARCHIVED" in md and "skills/created/" in md, md[-200:])
check("A5 it keeps the sequence", "`fs.edit`" in md and "`shell`" in md, md[:300])
check("A6 it no longer tells the agent to promote itself",
      "Archive: `improve`" not in md, md)

# ---- B: no purpose is stated as such, never invented ----
d2 = SE.draft(["fs.read", "web.fetch", "fs.write"], 2, OUT)
SE.ensure_check(d2)
SE.verify(d2, runner=lambda _d, _c: (True, "ok"))
got2 = SE.promote(d2, human=True)
md2 = open(os.path.join(got2["path"], "SKILL.md"), encoding="utf-8").read() if got2.get("ok") else ""
check("B1 a purpose-less promotion says it has none",
      "no stated purpose" in md2, md2[:200])
check("B2 it still states its real state", "ARCHIVED" in md2, md2[-160:])

# ---- C: the rest of the draft folder is preserved ----
files = sorted(os.listdir(got["path"]))
check("C1 the machine artifacts travel with the skill",
      all(x in files for x in ("SKILL.md", "proposal.json", "check.py", "runner.py", "skill.json")), files)
check("C2 the installed skill is in the live skill list",
      any(s.get("name") == os.path.basename(got["path"]) for s in skills_mod.list_skills(reload=True)),
      [s.get("name") for s in skills_mod.list_skills()][:5])

print("\n---\nv717: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
