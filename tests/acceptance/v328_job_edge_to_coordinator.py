#!/usr/bin/env python3
"""v328 — a job's assign edge goes to its COORDINATOR only (JAG-328).

In the constellation, J7 was drawn with an assign arrow to EVERY member (J7 -> A8
AND J7 -> A9). But the job is given to the MASTER (A8) alone; the piece handed to A9
is the SUBJOB J7.1, already drawn as J7.1 -> A9. The job->member arrow was a FALSE
edge duplicating the subjob edge — misleading and structurally wrong.

Deterministic, source-locked. Run: python3 tests/acceptance/v328_job_edge_to_coordinator.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    o = f.read()

check("A1 the job->agent edge is drawn from the job's COORDINATOR",
      "jobs.forEach(j => { const aid = j.coordinator;" in o)
check("A2 the old per-member job->agent edge is gone",
      "(j.agents || []).forEach(aid => { const a = agents.find" not in o)
check("A3 a member is still reached through its SUBJOB edge",
      "const a = agents.find(z => z.id === s.agent);" in o)
check("A4 a fan-out job (no coordinator) draws no false job->agent edge",
      "const aid = j.coordinator; if (!aid) return;" in o)
check("A5 the coordinator edge still uses the job->agent style",
      # JAG-424d: the assign edge is now a curved <path> (this._curve) instead of a
      # straight <line> (this._seg), but it keeps the same "clink assign" style.
      "const b = box[a.session], d = this._curve(jpos[j.id]" in o
      and 'class="clink assign"' in o)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

