#!/usr/bin/env python3
"""v790 — evolution acts on what it learned: retire dead tools, read failures.

The gate (v788/v789) decides what may land. These two close the loop the corpus
keeps pointing at:

  A  RETIREMENT (arXiv 2610.34938): a forged tool nobody called after N days is
     removable through Matrix's own remover; a tool that was called never is   [C3]
  B  FAILURE CLASSES (AHE 2604.25850): the durable run records already carry the
     failed step's tool + error; this ranks them so a draft can target a real
     failure instead of a repeated habit                                   [C6]

Deterministic: temp dirs, injected usage/remover, no Matrix layout, no model.
Run: python3 tests/acceptance/v790_evolve_retire_and_failures.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-790-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


NOW = time.time()
DAY = 86400.0
USAGE = {"ok": True, "tools": [
    {"namespace": "old_unused", "created": NOW - 30 * DAY, "last_used": 0.0,
     "uses": 0, "verdict": "unused"},
    {"namespace": "new_unused", "created": NOW - 1 * DAY, "last_used": 0.0,
     "uses": 0, "verdict": "unused"},
    {"namespace": "old_used", "created": NOW - 30 * DAY, "last_used": NOW - 2 * DAY,
     "uses": 4, "verdict": "used"},
], "count": 3, "unused": 2}

# ------------------------------------------------------- A: retirement -------
removed = []


def fake_remove(ns):
    removed.append(ns)
    return {"ok": True}


out = selfevolve.retire_unused(days=14, usage=lambda **_kw: USAGE, remove=fake_remove,
                               now=NOW)
check("A1 only the old, never-used tool is eligible", out.get("eligible") == 1, out)
check("A2 exactly that namespace is removed", removed == ["old_unused"], removed)
check("A3 a used tool is never touched", "old_used" not in removed, removed)
check("A4 a young tool is left alone", "new_unused" not in removed, removed)

removed.clear()
out = selfevolve.retire_unused(days=14, usage=lambda **_kw: USAGE, remove=fake_remove,
                               now=NOW, dry_run=True)
check("A5 a dry run names the victim and removes nothing",
      out.get("eligible") == 1 and removed == []
      and (out.get("removed") or [{}])[0].get("dry_run") is True, out)

out = selfevolve.retire_unused(days=0, usage=lambda **_kw: USAGE, remove=fake_remove, now=NOW)
check("A6 days=0 still refuses a used tool", out.get("eligible") == 2, out)

# ------------------------------------------------- B: failure classes --------
harness = os.path.join(_tmp, "harness")
os.environ["LONGRUN_HARNESS_DIR"] = harness
runs = os.path.join(harness, "runs")
os.makedirs(runs, exist_ok=True)


def record(name, steps):
    with open(os.path.join(runs, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)


record("r1", [
    {"tool": "fs.read", "ok": False, "error": "no such file: /a"},
    {"tool": "fs.read", "ok": False, "error": "no such file: /b"},
    {"tool": "fs.write", "ok": True, "error": ""},
])
record("r2", [
    {"tool": "fs.read", "ok": False, "error": "no such file: /c"},
    {"tool": "shell", "ok": False, "error": "exit 127: command not found"},
])

rep = selfevolve.failure_candidates(limit=10)
classes = rep.get("classes") or []
top = classes[0] if classes else {}
check("B1 both run records are read", rep.get("runs") == 2, rep)
check("B2 the dominant class is the normalized fs.read error",
      top.get("tool") == "fs.read" and top.get("count") == 3 and top.get("runs") == 2, top)
check("B3 a different error is its own class",
      any(c.get("tool") == "shell" and c.get("count") == 1 for c in classes), classes)
check("B4 a successful step is not a failure class",
      not any(c.get("tool") == "fs.write" for c in classes), classes)

rep = selfevolve.failure_candidates(limit=1)
check("B5 the limit is honoured", len(rep.get("classes") or []) == 1, rep)

rep = selfevolve.failure_candidates(limit=10, min_count=3)
check("B6 min_count filters rare classes",
      all(c.get("count") >= 3 for c in rep.get("classes") or []), rep)

print("\n---\nv790: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
