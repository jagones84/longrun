#!/usr/bin/env python3
"""v602 (RED) — the Plan header stops lying about what it shows.

- the run/job prefix uses the JOB namespace ("J180"), not the agent one
  ("A180" collides with agent ids like A54/A51);
- when plans moved on past the run start, the goal is labelled as the
  run-start goal (counts are live, the goal text is a fossil);
- the 80-char preview cuts at a word boundary, not mid-word.

Static, deterministic, no model/browser.
Run: python3 tests/acceptance/v602_plan_header_truth.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_jid = HTML.split("const _jid")[1].split(";")[0]
# the whole header-building block: everything before the dropdown body,
# wide enough to include the preview/stale consts above the innerHTML line.
_wide = HTML.split('<div class="goalfull-body">')[0][-1200:]
_segs = HTML.split('graphHead")')
_head = _segs[2].split("taskCount")[0] if len(_segs) > 2 else ""

check("T1 the header job prefix uses the job namespace",
      '"J" + curJob' in _jid and '("A" + curJob' not in _jid, _jid.strip()[:80])
check("T2 a run-start goal is labelled as such once plans moved on",
      "run-start goal" in _wide and "plan_base" in _wide)
check("T3 the preview cuts at a word boundary, not mid-word",
      'lastIndexOf(" ")' in _wide)
check("T4 no regression (counts, dropdown, history, rewind)",
      "nodes \u00b7 " in _head and "goalfull" in _head
      and "OLD PLAN" in HTML and "rewind to just before this todo" in HTML)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
