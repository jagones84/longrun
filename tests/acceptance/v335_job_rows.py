#!/usr/bin/env python3
"""v335 — Orbit job rows: subjobs are INDENTED by depth and open their agent (JAG-335/JAG-484).

The job panel listed the subjobs AND a flat per-agent `runs` list ("A8 done, A9 done,
A11 running") — the run rows are redundant: only the `JN.j` indexes carry the structure.
Each subjob row is now indented by its org depth and carries an explicit "↗ session"
button that opens the receiving agent's chat (JAG-484: the row itself is NOT a second
click-to-open — that would duplicate the ORG chart).

Deterministic, source-locked. Run: python3 tests/acceptance/v335_job_rows.py
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

check("A1 subjob rows carry data-sub; a dedicated button carries data-go",
      'class="runrow subjob" data-sub="' in o and 'data-go="' in o)
check("A2 the row is NOT a click-to-open; the \u2197 session button reuses onOpenAgent",
      'querySelectorAll("[data-sub]")' in o and "el.onclick = (e) => e.stopPropagation()" in o
      and "this.onOpenAgent(el.dataset.agent)" not in o
      and 'querySelectorAll("[data-go]")' in o and "this.onOpenAgent(b.dataset.go)" in o)
check("A3 rows are INDENTED by the org depth", "depth * 16" in o and "padding-left:'" in o)
check("A4 depth comes from the id dots (J8.1 -> 0, J8.1.2 -> 1)",
      'String(sid).split(".").length - 2' in o)
check("A5 the redundant flat `runs` list is GONE",
      "Object.keys(runs)" not in o and "const runs = j.runs" not in o)
check("A6 the collapsed body is just the subjob rows",
      'const runHtml = (this.open === j.id) ? subHtml : "";' in o)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

