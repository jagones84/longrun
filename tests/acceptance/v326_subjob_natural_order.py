#!/usr/bin/env python3
"""v326 — subjob ids must order NUMERICALLY, not as strings (JAG-326).

Subjobs are JN.1, JN.2, … JN.10. Sorting the ids as STRINGS puts "JN.10" before
"JN.2", so a job with 10+ subjobs listed them out of order — in the coordinator's
delegation record (`jobs._announce_delegation`) and in the Orbit JobsView. Both
now sort by the numeric index.

Deterministic, no model. Run: python3 tests/acceptance/v326_subjob_natural_order.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-326-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate.jobs import plan_subjobs, subjob_num  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


check("A1 the numeric index of J6.1 is 1", subjob_num("J6.1") == 1)
check("A2 the numeric index of J6.2 is 2", subjob_num("J6.2") == 2)
check("A3 the numeric index of J6.10 is 10", subjob_num("J6.10") == 10)
check("A4 a non-numeric id falls back to 0", subjob_num("J6") == 0 and subjob_num("x") == 0)

# ---- a 12-subjob job sorts naturally -------------------------------------
subs = plan_subjobs("J7", ["A%d" % i for i in range(1, 13)], None, "", {})
expect = ["J7.%d" % i for i in range(1, 13)]
got = sorted(subs.keys(), key=subjob_num)
check("B1 12 subjobs sort 1..12 in natural order", got == expect, str(got))
check("B2 the bug is real: a string sort misorders them", sorted(subs.keys()) != expect,
      str(sorted(subs.keys())))
check("B3 numeric order is stable and total", sorted(got, key=subjob_num) == expect)

# ---- wiring ---------------------------------------------------------------
src = read("src", "longrun", "orchestrate/jobs.py")
check("C1 the coordinator's delegation record sorts naturally",
      'key=lambda x: subjob_num(x.get("id"))' in src)
orbit = read("src", "longrun", "orbit", "web", "orbit.html")
check("C2 the Orbit JobsView sorts subjobs by numeric PATH (v629: any depth)",
      "const _path = s => String(s).split(\".\").slice(1)" in orbit
      and "Object.keys(subs).sort(_cmp)" in orbit)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

