#!/usr/bin/env python3
"""v330 — the coordinator DECLARES subjob dependencies; the order is ENFORCED (JAG-330).

SEVERE finding: in a coordinator job, coder 2's work must happen AFTER coder 1's, but
EVERY subjob ran in parallel — the master never structured the order and the runner had
no dependency to honour, so coder 2 started immediately instead of waiting for coder 1.

Fix (Paperclip-style): the coordinator's decomposition asks it to END a bullet with
"(after AX)" when that teammate must wait; the runner reads those declarations into the
subjob DAG and schedules in WAVES, so a dependent subjob cannot start before the ones
it waits on are done.

Deterministic, no model. Run: python3 tests/acceptance/v330_declared_subjob_deps.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-330-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate.jobs import JobRegistry, merge_deps, parse_plan_deps, plan_subjobs, waves  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def wave_of(w, aid):
    return next(i for i, wave in enumerate(w) if aid in wave)


PLAN = ("- A9 (coding agent 1): scaffold the project (after A8)\n"
        "- A11 (coding agent 2): deploy to the phone (after A9)")

# ---- A: reading the coordinator's declarations ----------------------------
d = parse_plan_deps(PLAN)
check("A1 '(after A9)' becomes a dependency", d == {"A9": ["A8"], "A11": ["A9"]}, str(d))
check("A2 several deps on one bullet are read",
      parse_plan_deps("- A11: x (after A9, A10)") == {"A11": ["A9", "A10"]})
check("A3 a bullet with no '(after …)' declares nothing", parse_plan_deps("- A9: x") == {})
check("A4 'after' is case-insensitive",
      parse_plan_deps("- A11: x (After A9)") == {"A11": ["A9"]})

# ---- B: the effective DAG and the ENFORCED order --------------------------
m = merge_deps({}, d)
check("B1 the merge unions the user's deps with the declared ones",
      sorted(merge_deps({"A11": ["A8"]}, d)["A11"]) == ["A8", "A9"])
w = waves(["A8", "A9", "A11"], m)
check("B2 coder 2 is scheduled STRICTLY AFTER coder 1", wave_of(w, "A11") > wave_of(w, "A9"), str(w))
check("B3 the full chain waits: A8 -> A9 -> A11", w == [["A8"], ["A9"], ["A11"]], str(w))

# ---- C: the subjobs carry the declared deps -------------------------------
subs = plan_subjobs("J8", ["A8", "A9", "A11"], "A8", PLAN, m)
check("C1 coder 2's subjob depends on coder 1's subjob",
      subs["J8.2"]["deps"] == ["J8.1"], str({k: v["deps"] for k, v in subs.items()}))
check("C2 coder 1's subjob has no subjob dep (its coord dep is filtered out)",
      subs["J8.1"]["deps"] == [])

# ---- D: the workers are told the order ------------------------------------
msg = JobRegistry._delegation_msg("J8", "A8 (Master)", {"id": "J8.2", "deps": ["J8.1"]}, "g", "- A11: x")
check("D1 the dependent worker is told what it waits for",
      "Waits for (already completed): J8.1." in msg)

# ---- E: wiring ------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orchestrate/jobs.py"), encoding="utf-8") as f:
    src = f.read()
check("E1 the coordinator is ASKED to declare dependencies",
      "DEPENDENCIES (enforced)" in src and "(after AX)" in src)
check("E2 the runner orders subjobs by the EFFECTIVE deps",
      "plan_subjobs(jid, list(sessions.keys())," in src
      and "(coord if _coord_mode else None), plan, deps," in src
      and "tree=_tree)" in src          # v629: the org tree drives nesting
      and "for wave in waves(list(sessions.keys()), deps):" in src)
check("E3 the declared deps are stored on the job",
      "j[\"declared_deps\"] = _decl" in src)   # v629: inside the merge updater
check("E4 the master's chat shows the declared order", "[after %s]" in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

