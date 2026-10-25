#!/usr/bin/env python3
"""v635 — the same rule everywhere in the rail: one primary action, the rest inline.

v632-v634 established the pattern (data first, actions as inline links, prose only
where it is NOT self-evident). This locks it for the three sections that still
carried a paragraph and a row of full buttons: Terminal, Workspace ▸ pending
changes, Codebase.

Contract:
  A) Terminal: the 3-line "one shell per caller" paragraph left the body and
     lives in the section-header tooltip; clear / reset are inline links.
  B) Pending changes: refresh / approve all / reject all are inline links in the
     same `.acts` row (the data-call doors are untouched).
  C) Codebase: `⚡ build` stays the one button; files / status / clear are links.

Run: python tests/acceptance/v635_rail_actions.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v635_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

# ---- A. Terminal --------------------------------------------------------------
check("A1 the paragraph left the body", "One shell per caller —" not in UI)
check("A2 the rule stays reachable in the section tooltip",
      'title="one persistent shell per caller:' in UI)
check("A3 clear / reset are inline links, ids and handlers intact",
      '<button class="lnk" data-call="termClear"' in UI
      and '<button class="lnk" data-call="termReset"' in UI
      and "function termReset" in UI)

# ---- B. Pending changes -------------------------------------------------------
check("B1 the three review actions are inline links",
      '<button class="lnk" data-call="loadEdits"' in UI
      and '<button class="lnk" data-call="approveEdits"' in UI
      and '<button class="lnk" data-call="rejectEdits"' in UI)
check("B2 the verbs are still readable", ">approve all</button>" in UI
      and ">reject all</button>" in UI and ">refresh</button>" in UI)

# ---- C. Codebase --------------------------------------------------------------
check("C1 build stays the one primary button",
      '<button class="ghost" id="cbBuildBtn"' in UI)
check("C2 files / status / clear are inline links",
      '<button class="lnk" data-call="cbFiles"' in UI
      and '<button class="lnk" data-call="cbStatus"' in UI
      and '<button class="lnk" data-call="cbClear"' in UI)

print("\nv635: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
