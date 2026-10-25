#!/usr/bin/env python3
"""v606 (RED) — sidebar session rows must never fabricate an agent id.

The rail badge used `A${_anum}` for EVERY session: a roster agent shows its
real id (A49), but an agentless session (e.g. cmptest1, sequence 189) rendered
`A189` — an agent that does not exist (same phantom class as A155, v604).
Rule (UP-1): the A-namespace is roster-only; a session sequence renders J.

Deterministic: static HTML checks only. Run: python tests/acceptance/v606_sidebar_owner_truth.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("T1 no phantom-A badge in sidebar rows",
      '"session sequence"}">A${_anum}' not in HTML,
      "the old unconditional A<sequence> render must be gone")

check("T2 an agentless session renders its J sequence, honestly tooltiped",
      "J${_anum}" in HTML and "no designated agent" in HTML,
      "J-prefix + tooltip instead of a fake agent")

check("T3 a roster agent still renders its real A id",
      ">A${_anum}</span>" in HTML and "agent id ${esc(ag.id)}" in HTML,
      "A-namespace kept for real roster agents only")

check("T4 _agentNum still resolves roster-first, sequence-fallback",
      "function _agentNum(s)" in HTML
      and "a.n || String(a.id" in HTML
      and "(s && s.job)" in HTML,
      "resolver untouched, only the render changed")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
