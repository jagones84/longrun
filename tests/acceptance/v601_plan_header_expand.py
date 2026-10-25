#!/usr/bin/env python3
"""v601 (RED) — the Plan panel header no longer silently truncates the run goal.

- the 40-char hard cut (`goal.slice(0, 40)` with no ellipsis) is gone;
- the header shows a short preview ending in an ellipsis + the FULL goal in
  the usual expandable dropdown (`details.goalfull`), escaped;
- the evidence badge (`N` count) explains itself (title: click the row).

Static, deterministic, no model/browser.
Run: python3 tests/acceptance/v601_plan_header_expand.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_segs = HTML.split('graphHead")')
_head = _segs[2].split("taskCount")[0] if len(_segs) > 2 else ""

check("T1 no silent 40-char goal cut in the header",
      "goal.slice(0, 40)" not in _head)
check("T2 the full goal is rendered escaped in an expandable dropdown",
      "goalfull" in _head and "esc(_goalFull)" in _head
      and "<details" in _head)
check("T3 the preview ends with an ellipsis when the goal is long",
      "\u2026" in HTML.split('<details class="goalfull">')[0][-900:])
check("T4 the evidence badge explains itself (click the row to view)",
      'class="ev"' in HTML and "click the row" in HTML.split('class="ev"')[1][:400])
check("T5 counts + history + rewind survive (no regression)",
      '" nodes \u00b7 "' in HTML and "OLD PLAN" in HTML
      and "rewind to just before this todo" in HTML)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
