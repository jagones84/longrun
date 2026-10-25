#!/usr/bin/env python3
"""v602 (evolved v607) — the Plan header carries no session/job number.

A bare "J155"/"J182" prefix read as a team job that does not exist (registry
holds J12-J22; the number was the session's own JAG-169 sequence). The run id
identifies the run; the session lives in the sidebar (roster A id or honest
J sequence, v606). Kept: run-start goal label, word-boundary preview.

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


# the whole header-building block: everything before the dropdown body,
# wide enough to include the preview/stale consts above the innerHTML line.
_wide = HTML.split('<div class="goalfull-body">')[0][-1200:]
_segs = HTML.split('graphHead")')
_head = _segs[2].split("taskCount")[0] if len(_segs) > 2 else ""

check("T1 the header carries no session/job number prefix",
      "const _jid" not in HTML and '"J" + curJob + " · "' not in HTML
      and "session number" not in _head,
      "run id identifies the run, nothing else")
check("T2 a run-start goal is labelled as such once plans moved on",
      "run-start goal" in _wide and "plan_base" in _wide)
check("T3 the preview cuts at a word boundary, not mid-word",
      'lastIndexOf(" ")' in _wide)
check("T4 no regression (run id, counts, dropdown, history, rewind)",
      '"run " + (graph.run_id' in _head and "nodes \u00b7 " in _head
      and "goalfull" in _head
      and "OLD PLAN" in HTML and "rewind to just before this todo" in HTML)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
