#!/usr/bin/env python3
"""v823 — a promotion may REPLACE an installed skill of the same name (v823).

The video's memory/skill lifecycle: refinement is "update or delete what is
stored". Longrun had it for memories and NOT for skills — `promote()` refused
outright when the target name existed, so an improvement to an already-installed
skill (or its second re-mine) could never land.

A collision now has a LIFECYCLE instead of a wall:

  A) the default is unchanged — a colliding promote is still REFUSED and the
     installed skill is untouched;
  B) with `supersede=True` the new skill is installed and the old one is RETIRED
     (moved to `<skills>/_retired/<category>/<name>-<stamp>/`, never deleted);
  C) the replacement is recorded twice — an append-only ledger line with the old
     content digest, and `supersedes` on the new proposal;
  D) the loader shows ONE active skill of that name (the retired copy is not an
     active skill), and a candidate that cannot be staged leaves the installed
     skill alone;
  E) the safety boundaries are unchanged: `skills/core` and an auto skill outside
     `skills/created` are still refused.

Deterministic: isolated dirs, held-out gate off, no model, no network.
Run: python3 tests/acceptance/v823_skill_supersede.py
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="lr-supersede-v823-")
SKILLS = os.path.join(_tmp, "skills")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = _tmp
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = SKILLS
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
for _d in ("cfg", "sessions"):
    os.makedirs(os.path.join(_tmp, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve          # noqa: E402
from longrun.memory import skills as skills_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


C = {"category": "created", "min_green_streak": 1, "max_cost_ratio": 99.0}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _prop(out, name):
    d = os.path.join(out, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "verified", "name": name, "origin": "auto",
                   "green_streak": 2}, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("# %s\n\ndraft body\n" % name)
    return d


# An already-installed skill (as a prior promotion would have left it).
INST = os.path.join(SKILLS, "created", "foo")
os.makedirs(INST, exist_ok=True)
OLD = b"# foo\n\nOLD BODY (the version being replaced)\n"
with open(os.path.join(INST, "SKILL.md"), "wb") as f:
    f.write(OLD)
with open(os.path.join(INST, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"status": "archived", "name": "foo"}, f)
OLD_SHA = _sha(os.path.join(INST, "SKILL.md"))

CAND = _prop(_tmp, "foo")   # the improved candidate, same name

# ---- A: the default is unchanged (refuse, do not clobber) ----------------
res = selfevolve.promote(CAND, skills_dir=SKILLS, c=dict(C))
check("A1 a colliding promote is refused without supersede",
      res.get("ok") is False and "already exists" in str(res.get("error")), res)
check("A2 the installed skill is untouched",
      _read(os.path.join(INST, "SKILL.md")) == OLD)

# ---- B: supersede installs the new one and RETIRES the old --------------
res = selfevolve.promote(CAND, skills_dir=SKILLS, c=dict(C), human=True,
                         supersede=True, purpose="a better foo")
check("B1 the colliding promote succeeds with supersede",
      res.get("ok") is True, {k: res.get(k) for k in ("ok", "error")})
_new_txt = _read(os.path.join(INST, "SKILL.md")).decode("utf-8", "replace")
check("B2 the new skill is installed (its archived text is in place)",
      "ARCHIVED" in _new_txt and "a better foo" in _new_txt, _new_txt[:160])

_rroot = os.path.join(SKILLS, "_retired")
_cat = os.path.join(_rroot, "created")
_rnames = sorted(os.listdir(_cat)) if os.path.isdir(_cat) else []
check("B3 the replaced version is retired, not deleted (bytes intact)",
      len(_rnames) == 1 and _read(os.path.join(_cat, _rnames[0], "SKILL.md")) == OLD,
      _rnames)
check("B4 the retired copy keeps its own proposal.json",
      os.path.isfile(os.path.join(_cat, _rnames[0], "proposal.json")) if _rnames else False)

_led = os.path.join(_rroot, "ledger.jsonl")
_lines = [json.loads(x) for x in _read(_led).decode("utf-8").splitlines()] if os.path.isfile(_led) else []
check("B5 the ledger records who replaced what, at which digest, and why",
      len(_lines) == 1 and _lines[0].get("name") == "foo"
      and _lines[0].get("by") == "operator"
      and _lines[0].get("prev_sha256") == OLD_SHA
      and _lines[0].get("reason") == "a better foo", _lines)

_prop_new = json.load(open(os.path.join(CAND, "proposal.json"), encoding="utf-8"))
check("B6 the NEW proposal names the version it replaced",
      (_prop_new.get("supersedes") or {}).get("prev_sha256") == OLD_SHA,
      _prop_new.get("supersedes"))

# ---- C/D: the loader shows ONE active skill; the retired copy is not one --
_rows = [s for s in skills_mod.list_skills(reload=True) if s["name"] == "foo"]
check("C1 the loader shows exactly one active `foo`", len(_rows) == 1,
      [r.get("path") for r in _rows])
check("C2 it is the NEW body", _rows and _rows[0]["digest"] == _sha(os.path.join(INST, "SKILL.md")),
      _rows and _rows[0]["digest"])
check("C3 no retired folder is listed as an active skill",
      all("_retired" not in (s.get("path") or "") for s in skills_mod.list_skills()))

_bad = os.path.join(_tmp, "not-a-folder")
with open(_bad, "w", encoding="utf-8") as f:
    f.write("x")
_keep = _read(os.path.join(INST, "SKILL.md"))
res = selfevolve.promote(_bad, skills_dir=SKILLS, c=dict(C), supersede=True)
check("D1 a candidate that cannot be staged leaves the installed skill alone",
      res.get("ok") is False and _read(os.path.join(INST, "SKILL.md")) == _keep, res)

# ---- E: the safety boundaries are unchanged ------------------------------
res = selfevolve.promote(_prop(_tmp, "coreskill"), skills_dir=SKILLS,
                         c={"category": "core", "min_green_streak": 1})
check("E1 skills/core is still refused",
      res.get("ok") is False and "core" in str(res.get("error")), res)
res = selfevolve.promote(_prop(_tmp, "elsewhere"), skills_dir=SKILLS,
                         c={"category": "custom", "min_green_streak": 1})
check("E2 an auto skill outside skills/created is still refused",
      res.get("ok") is False and "created" in str(res.get("error")), res)

# ---- F: the operator approve path actually asks for the supersede ---------
_src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"),
            encoding="utf-8").read()
check("F1 the WebUI approve path passes supersede=True",
      "supersede=True" in _src)

print("\n---")
print("v823: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
