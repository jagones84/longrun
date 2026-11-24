#!/usr/bin/env python3
"""v1298 — the rail ring uses one per-session value, regardless of focus.

Reported (operator, 2026-11-24): the saturation ring changes when leaving a
session, then returns to its earlier value when that session is selected again.

Root cause: the selected row was first rendered from its `/api/sessions` row,
then `_repaintCtx()` overwrote that same row from the focused chat's separate
`/api/context` meter. Non-selected rows kept their own session snapshots. Thus
the selected row had two competing values, and focus changes switched which one
was visible.

Contract:
  A) every rail ring renders from its own session row, with no active-session
     special case or live-meter element IDs;
  B) repainting the current chat's live context must not mutate a rail row;
  C) a session switch clears the composer meter immediately, before the
     asynchronous context response for the new session arrives.

Run: python3 tests/acceptance/v1298_rail_ring_stable_across_focus.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:260]) if detail else ""))


def function_body(name):
    match = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", HTML)
    if not match:
        return ""
    start = match.end()
    depth = 1
    for pos in range(start, len(HTML)):
        if HTML[pos] == "{":
            depth += 1
        elif HTML[pos] == "}":
            depth -= 1
            if depth == 0:
                return HTML[start:pos]
    return ""


ring = function_body("_ctxRingHtml")
repaint = function_body("_repaintCtx")
switch = function_body("selectSession")

check("A1 rail ring renders directly from that row's ctx_pct",
      "s.ctx_pct" in ring and "sessionId" not in ring and "isActive" not in ring)
check("A2 rail ring has no active-only ids that live repaint can target",
      all(token not in ring for token in (
          'id=\"ctx-meter\"', 'id=\"ctxRing\"', 'id=\"ctxPctTop\"')))
check("B1 the live meter repaint does not write into any rail ring",
      all(token not in repaint for token in (
          '$(\"ctx-meter\")', '$(\"ctxRing\")', '$(\"ctxPctTop\")',
          "strokeDashoffset")))
check("C1 session switch clears the old live context before requesting the new one",
      bool(re.search(r"sessionId\s*=\s*s\.id;[\s\S]*?ctxNa\([^)]*\);[\s\S]*?loadCtx\(\)", switch)))

print("---")
ok = sum(results)
print("v1298: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
