#!/usr/bin/env python3
"""v725 — did the forged tool actually help AFTER it landed? (EV-20)

arXiv 2610.34938 ("How Do Coding-Agent Harnesses Self-Evolve?"): of 12 implemented
harness changes, only 2 eliminated the targeted behaviour, 1 reduced it and 4
changed nothing — the missing capability is telling whether a change helps on LATER
tasks (arXiv 2610.30042 calls the same thing edit-outcome attribution).

Longrun forged tools and never looked back. Now each forged module reports, from
the recorded runs: how many runs called it, when it was last used, and how many
runs happened after it landed.

  A  a forged tool that later runs called is "used"
  B  a forged tool with later runs and no call is "unused"
  C  a forged tool newer than every run is "new" (no verdict yet — not a lie)
  D  a Matrix module that was NOT forged is not claimed
  E  the panel and the API wire the same object
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v725-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.core import matrix as MTX  # noqa: E402
from longrun.util import paths  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


USE, DEAD = "learned_v725_used", "learned_v725_dead"
r1 = SE.forge_matrix(["fs.read", "fs.edit", "shell.exec"], support=3, name=USE)
r2 = SE.forge_matrix(["fs.read", "fs.write", "memory.recall"], support=3, name=DEAD)
check("P0 both tools were forged", r1.get("ok") and r2.get("ok"), (r1, r2))
# a Matrix module the miner never wrote
os.makedirs(os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools"), exist_ok=True)
hand = os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools", "handwritten_v725.py")
with open(hand, "w", encoding="utf-8", newline="\n") as f:
    f.write("STEPS = ['fs.read', 'fs.read']\nTOOL_SCHEMAS = {}\nTOOL_SCHEMA = {}\n"
            "def execute(args, run_id=None, subtool=None):\n    return {'ok': True}\n")

# both tools existed BEFORE the recorded runs: backdate them, then record runs
_now = time.time()
_late_t = _now - 100
for _r in (r1, r2):
    os.utime(_r["path"], (_late_t, _late_t))
hist = os.path.join(paths.DATA_DIR, "sequences.json")
with open(hist, "w", encoding="utf-8") as f:
    json.dump({"run-1": {"tools": ["fs.read", USE + ".run"], "ts": _now - 60},
               "run-2": {"tools": ["fs.read", "shell.exec"], "ts": _now - 50},
               "run-3": {"tools": ["shell.exec", "memory.recall"], "ts": _now - 40}}, f)

rep = SE.forged_usage()
rows = {r["namespace"]: r for r in (rep.get("tools") or [])}
check("A1 a called tool is 'used'", (rows.get(USE) or {}).get("verdict") == "used"
      and rows[USE]["uses"] == 1, rep)
check("A2 it says how many runs happened after it landed",
      rows[USE]["runs_after"] == 3, rows.get(USE))
check("A3 the call time is recorded", rows[USE]["last_used"] > 0, rows.get(USE))
check("B1 a never-called tool with later runs is 'unused'",
      (rows.get(DEAD) or {}).get("verdict") == "unused"
      and rows[DEAD]["uses"] == 0, rows.get(DEAD))
check("B2 the summary counts the unused one", rep.get("unused") == 1, rep)
check("D1 a hand-written module is not claimed", "handwritten_v725" not in rows,
      sorted(rows))

# a tool that lands after every run has no verdict yet
late = SE.forge_matrix(["fs.read", "fs.edit"], support=2, name="learned_v725_late")
rows2 = {r["namespace"]: r for r in (SE.forged_usage().get("tools") or [])}
check("C1 a brand-new tool is 'new', not 'unused'",
      late.get("ok") and (rows2.get("learned_v725_late") or {}).get("verdict") == "new",
      rows2.get("learned_v725_late"))

api_rows = improve.list_forged()
check("E1 the panel reads the same object through improve.list_forged",
      {"tools", "count", "unused"} <= set(api_rows)
      and any(r["namespace"] == USE for r in api_rows["tools"]), api_rows)
check("E2 the API payload carries it", '"forged": _forged.get("tools")' in API
      and '"forged_unused"' in API)
check("E3 the panel renders it with the real remove door",
      'id="impForged"' in UI
      and '"/api/matrix/remove"' in UI.split('const forgedBox = $("impForged")')[1][:1600])

for ns in (USE, DEAD, "learned_v725_late"):
    MTX.remove("tool", ns)
print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
