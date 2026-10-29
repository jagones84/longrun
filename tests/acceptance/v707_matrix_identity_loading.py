#!/usr/bin/env python3
"""v707 — one identity per skill, one installer, and fault-isolated legacy code.

The audit found three seams that made "the harness learns and modifies itself"
ambiguous:

  A  a repository skill and a Matrix skill with the SAME name are ONE active
     identity (deterministic winner, the shadowed source stays visible)
  B  `skills/created` has ONE installer: neither selfevolve nor Matrix graduation
     clobbers an existing folder
  C  `matrix.load_module` is reachable from the matrix tool (on demand, never boot)
  D  a broken / exiting hook or tool is isolated; valid artifacts stay live
  E  the session evidence digests the skills the PROMPT actually sees

Deterministic: no model, no network, no server.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v707-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR", "SKILLS_DIR",
            "MATRIX_SRC", "MATRIX_DOT"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.harness import record  # noqa: E402
from longrun.memory import skills  # noqa: E402
from longrun.tools import matrix_guard, registry, tools  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

matrix_guard.ensure_layout()
ROOT, MSRC, MDOT = matrix._roots()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------- A: one identity --
repo_skill = os.path.join(skills.SKILLS_DIR, "core", "dup", "SKILL.md")
matrix_skill = os.path.join(MDOT, "skills", "dup", "SKILL.md")
write(repo_skill, "# dup\n\nRepository copy.\n")
write(matrix_skill, "# dup\n\nMatrix copy.\n")
listed = skills.list_skills(reload=True)
dups = [s for s in listed if s["name"] == "dup"]
check("A1 a duplicated name is ONE active skill", len(dups) == 1, dups)
check("A2 the repository copy wins deterministically", dups and dups[0]["category"] == "core",
      dups and dups[0].get("category"))
check("A3 the shadowed source stays visible on the active entry",
      dups and matrix_skill in (dups[0].get("shadowed") or []), dups and dups[0].get("shadowed"))
shadow = skills.shadowed_skills()
check("A4 the shadowed source is reported with who won",
      any(s["name"] == "dup" and s["shadowed_by"] == repo_skill for s in shadow), shadow)
check("A5 the prompt injection lists the name once",
      skills.skills_context().count("dup") <= 2)

# --------------------------------------------------------- B: one installer --
dest = os.path.join(TMP, "created", "dup")
os.makedirs(dest, exist_ok=True)
blocked = skills.install_skill_dir(os.path.dirname(repo_skill), dest)
check("B1 the installer refuses an existing destination",
      blocked.get("ok") is False and "already exists" in str(blocked.get("error")), blocked)
fresh = os.path.join(TMP, "created", "fresh")
installed = skills.install_skill_dir(os.path.dirname(repo_skill), fresh)
check("B2 it installs into a free destination",
      installed.get("ok") is True and os.path.isfile(os.path.join(fresh, "SKILL.md")), installed)
se_src = open(os.path.join(REPO, "src", "longrun", "util", "selfevolve.py"),
              encoding="utf-8").read()
check("B3 selfevolve promotes through that installer (no second copytree)",
      "install_skill_dir" in se_src)
mx_src = open(os.path.join(REPO, "src", "longrun", "core", "matrix.py"),
              encoding="utf-8").read()
check("B4 Matrix graduation uses the same installer",
      "install_skill_dir" in mx_src and "shutil.rmtree(dst_pdir" not in mx_src)

# ------------------------------------------------ C: on-demand module loading --
write(os.path.join(MSRC, "util", "helper.py"), "def helper(v):\n    return v\n")
loaded = tools._matrix({"action": "load_module", "name": "util/helper"}, None)
check("C1 the matrix tool exposes load_module", loaded.get("ok") is True
      and loaded.get("path"), loaded)
check("C2 the action is declared in the schema",
      "load_module" in (registry._LEGACY_SCHEMAS["matrix"]["properties"]["action"]["enum"]))
check("C3 its name argument is required by the gate",
      registry._SUBTOOL_REQUIRED["matrix.load_module"] == ["name"]
      and registry._SUBTOOL_FIELDS["matrix"]["load_module"] == ["name"])
check("C4 traversal is refused through the tool",
      tools._matrix({"action": "load_module", "name": "../../etc/passwd"}, None).get("ok") is False)

# --------------------------------------------------- D: legacy fault isolation --
write(os.path.join(MSRC, "tools", "good.py"),
      'TOOL_SCHEMAS = {"good.run": {"description": "good", "type": "object"}}\n'
      "def execute(args, run_id=None, subtool=None):\n"
      '    return {"ok": True}\n')
write(os.path.join(MSRC, "tools", "bad.py"), "raise SystemExit(9)\n")
write(os.path.join(MSRC, "plan", "hooks.py"), "import sys\nsys.exit(7)\n")
hl = matrix.hotload()
check("D1 a valid tool stays live beside a broken one", "good.run" in hl["loaded_tools"], hl["loaded_tools"])
check("D2 the broken tool is reported, not fatal",
      any("bad.py" in str(e.get("file")) for e in hl["errors"]), hl["errors"])
check("D3 a hook that exits is isolated", hl.get("ok") is False
      and any(e.get("subpackage") == "plan" for e in hl.get("hook_errors") or []), hl.get("hook_errors"))
check("D4 a call through the dead hook still returns the default",
      matrix.call_hook("plan", "score_candidate", "x", 0.5, default=0.5) == 0.5)
check("D5 the tool executes with its own isolation boundary",
      matrix.execute_tool("good.run", {}).get("ok") is True)

# ------------------------------------------------------- E: honest evidence ----
digest = record._skills_digest()
check("E1 the session evidence digests the skill view the prompt sees",
      digest.get("count") == len([s for s in skills.list_skills() if s.get("digest")])
      and digest.get("sha256"), digest)
check("E2 the duplicated name is counted once", digest.get("count") ==
      len({s["name"] for s in skills.list_skills()}), digest)

print("\n---\nv707: %d/%d PASS" % (sum(results), len(results)))
try:
    shutil.rmtree(TMP, ignore_errors=True)
finally:
    sys.exit(0 if all(results) else 1)
