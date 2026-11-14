#!/usr/bin/env python3
"""v997 — the memory store can be REMOVED for one arm of a run.

CO-2 (2026-11-14). CoReMem (arXiv 2611.17316) values a memory by what the next
task saves with it and without it; Longrun had no "without": `memory.py` built
its own folder while every other store subdirectory was overridable
(`util/paths.py`), so `benchmarks/ablation.py` could remove skills, rules and
hooks but not memory — and that module refuses a layer it cannot remove.

  A) `LONGRUN_MEMORY_DIR` is the ONE owner of the folder and the files land there;
  B) `ablation.materialize("memory")` yields an EMPTY folder and the env overlay,
     and the plan differs by exactly that key;
  C) with no override the default is still `<data>/memory` (nothing moved);
  D) a layer that cannot be removed is still refused.

Deterministic, no live model, no network, no server.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v997-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_MEMORY_DIR"] = os.path.join(TMP, "mem")
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from longrun.memory import memory               # noqa: E402
from benchmarks import ablation                 # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


MEM = os.path.join(TMP, "mem")

# ---- A. the switch is the one owner ---------------------------------------
check("A1 memory.DATA_DIR follows LONGRUN_MEMORY_DIR", memory.DATA_DIR == MEM,
      memory.DATA_DIR)
rec = memory.store("agent.note", "A_LESSON stored under the override", origin="reflect")
check("A2 the record lands in the override folder",
      os.path.isfile(os.path.join(MEM, "agent_notes.md")),
      os.listdir(MEM))
check("A3 the default data/memory folder was NOT created",
      not os.path.isdir(os.path.join(TMP, "data", "memory")))
check("A4 path_for() names the SAME file the store used",
      memory.path_for("agent.note") == os.path.join(MEM, "agent_notes.md"),
      memory.path_for("agent.note"))
check("A5 the record is recallable", any(r.get("mid") == rec.get("mid")
      for r in memory.query("A_LESSON", limit=5)))

# ---- B. the ablation arm ---------------------------------------------------
root = os.path.join(TMP, "arm")
env = ablation.materialize("memory", root)
arm_dir = env.get("LONGRUN_MEMORY_DIR", "")
check("B1 materialize() returns the overlay and creates the folder",
      arm_dir == os.path.join(root, "memory") and os.path.isdir(arm_dir), arm_dir)
check("B2 the arm folder is EMPTY (it removes, it does not copy)",
      os.listdir(arm_dir) == [], os.listdir(arm_dir))
plan = ablation.plan("memory", "python3 tests/x.py", root=os.path.join(TMP, "arm2"))
check("B3 the plan differs by exactly the memory folder",
      plan["differs_by"] == ["LONGRUN_MEMORY_DIR"], plan["differs_by"])
check("B4 the base arm carries no memory overlay", plan["arm_base"]["env"] == {})
check("B5 memory is a named layer next to the others",
      set(ablation.LAYERS) == {"skills", "rules", "hooks", "memory"},
      sorted(ablation.LAYERS))

# ---- C. no override, no move ----------------------------------------------
code = ("import sys; sys.path.insert(0, %r); from longrun.util import paths; "
        "print(paths.MEMORY_DIR)" % os.path.join(REPO, "src"))
clean = {k: v for k, v in os.environ.items() if k != "LONGRUN_MEMORY_DIR"}
got = subprocess.run([sys.executable, "-c", code], env=clean, capture_output=True,
                     text=True).stdout.strip().splitlines()[-1]
check("C1 with no override the default is <data>/memory",
      got == os.path.join(TMP, "data", "memory"), got)

# ---- D. a layer it cannot remove is refused --------------------------------
try:
    ablation.materialize("transcript", os.path.join(TMP, "arm3"))
    refused = False
except ValueError:
    refused = True
check("D1 an unknown layer is refused, never a silent no-op", refused)

print("checks: %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
