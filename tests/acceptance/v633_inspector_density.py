#!/usr/bin/env python3
"""v633 — the inspector reads as data, not as chrome (Approvals / Cost / Workspace).

Operator report: the RH rail spent a card, a sentence and a row of zeroes on
panels that had nothing to report, and the two Cost maintenance actions were
stacked as full buttons under a three-clause explanation that the header tooltip
already carries.

Contract:
  A) Approvals: an empty queue renders NOTHING in the body (the section header
     already says `none`) and keeps the one maintenance action as an inline link.
  B) Cost: the counter row only exists when the ledger has calls; zero reads on
     one line ("$0  no calls yet"); the actions are inline links in ONE row; the
     three-clause prose is gone from the panel.
  C) Workspace: the body does not repeat the section title, and the default
     checkbox label lost the filler.
  D) Chat header: the copy action is an icon button with an accessible name.
  E) One shared rule for the inline-action rows (no duplicate declarations).

Run: python tests/acceptance/v633_inspector_density.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v633_")
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

# ---- A. Approvals --------------------------------------------------------------
check("A1 the empty queue no longer repeats what the header says",
      "no pending approvals" not in UI)
check("A2 the clear-decided action survives as an inline link",
      'class="lnk" data-call="approvalsClear"' in UI
      and 'data-call="approvalsClear"' in UI)
check("A3 an empty queue renders an EMPTY body, not a text node",
      'if (!pend.length) { box.innerHTML = ""; return; }' in UI)
check("A4 the pending summary still drives the section header",
      '_isum("apprCount", pend.length ? (pend.length + " pending") : "none"' in UI)

# ---- B. Cost -------------------------------------------------------------------
check("B1 the counter row is hidden until the ledger has calls",
      '<div class="ctxrow" id="costMetrics" hidden>' in UI
      and 'if (metrics) metrics.hidden = !(c && Number(c.calls || 0) > 0);' in UI)
check("B2 the two maintenance actions are inline links in ONE row",
      '<div class="acts">' in UI and 'class="lnk" id="costRefresh"' in UI
      and 'class="lnk" data-call="resetCosts"' in UI
      and '>refresh prices</button>' in UI)
check("B3 the three-clause prose left the panel (the tooltip keeps the rule)",
      "Harness calls only · DeepSeek peak/off-peak by UTC" not in UI
      and "HARNESS ONLY: this counts the calls Longrun itself made" in UI)
check("B4 a zero ledger reads on one line, not three",
      ': "no calls yet";' in UI
      and '<div class="remaining">no calls yet</div>' not in UI)
check("B5 `hidden` actually hides the counter row (author display beats UA rule)",
      ".ctxrow[hidden], .acts[hidden] { display: none; }" in UI)

# ---- C. Workspace --------------------------------------------------------------
check("C1 the body does not repeat the section title",
      "Workspace · folder (this session)" not in UI
      and 'id="wsCard"' in UI)
check("C2 the default checkbox label lost the filler",
      '> default for new sessions</label>' in UI
      and "set as default for new sessions" not in UI)

# ---- D. Chat header ------------------------------------------------------------
check("D1 copy is an icon button with an accessible name",
      'aria-label="copy name">⧉</button>' in UI and "⧉ copy name" not in UI)

# ---- E. one shared action-row rule --------------------------------------------
check("E1 the inline-action row rule is declared ONCE",
      ".acts, .ctxacts {" in UI and "\n  .ctxacts {" not in UI)

print("\nv633: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
