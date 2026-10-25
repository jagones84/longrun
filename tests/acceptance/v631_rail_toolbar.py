#!/usr/bin/env python3
"""v631 — the rail top is ONE tight toolbar; self-explanatory prose is gone.

Operator report (screenshot of the LH panel): the permanent "new session title"
input, the permanent search input, the activity bar and "hide empty" stacked to
~120px of dead vertical space; and several panels carried long explanatory
sentences that say what the UI already says.

Contract:
  A) the rail top is a single toolbar row: ＋ (opens the new-session DIALOG),
     🔍 (opens the search row on demand, Esc clears + closes), the
     running/finished chip, and hide-empty — nothing permanent above the list.
  B) the obvious prose is gone (short, factual lines only where semantics are
     NOT self-evident: exit-code hooks, backup path).

Run: python tests/acceptance/v631_rail_toolbar.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v631_")
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
ORBIT = src("src", "longrun", "orbit", "web", "orbit.html")


def block(selector, text=None):
    doc = text if text is not None else UI
    head = selector + " {"
    if head not in doc:
        return ""
    return doc.split(head)[1].split("}")[0]


# ---- A. one toolbar row --------------------------------------------------------
check("A1 the rail top is ONE toolbar row (no permanent input stack)",
      'class="rail-tools" role="toolbar"' in UI and "rail-workspace" not in UI)
check("A2 the toolbar holds ＋ · 🔍 · activity · hide-empty in that order",
      UI.index('id="railNew"') < UI.index('id="railSearch"')
      < UI.index('id="runsBar"') < UI.index('id="hide-empty"'))
check("A3 ＋ opens the new-session dialog (name asked there, not in the rail)",
      'id="railNew" data-call="newSession"' in UI
      and 'id="nsTitle"' in UI and 'id="sessInp"' not in UI)
check("A4 the magnifier opens the search row ON DEMAND (hidden by default)",
      'id="railSearch"' in UI and 'aria-controls="railSearchRow"' in UI
      and '<div id="railSearchRow" class="rail-search" hidden>' in UI
      and 'row.hidden = !open;' in UI)
check("A5 Esc closes the search row and clears the filter",
      'if (e.key !== "Escape") return;' in UI
      and "if (inp.value) { inp.value = \"\"; loadSessions(); }" in UI)
check("A6 the running/finished chip is still there (with its counts)",
      'id="runsBarRun"' in UI and 'id="runsBarDone"' in UI
      and 'id="runsPanel"' in UI and "position: fixed" in block(".runs-panel"))
check("A7 hide-empty is a compact inline toggle, not its own row",
      '<input type="checkbox" id="hide-empty"><span>hide empty</span>' in UI
      and "white-space: nowrap" in block("aside .rail-filter"))
check("A8 the revealed list re-closes the search row when it clears the filter",
      'const row = $("railSearchRow"); if (row) row.hidden = true;' in UI)

# ---- B. prose that only repeated the UI ---------------------------------------
GONE = [
    "Full prompt stack for this session",
    "read-only references — edit them in Settings",
    "The summarizer reads the full old transcript in bounded parts",
    "Use the structured forms above (and the dedicated panels",
    "They do not call an LLM or test remote credentials",
    "The team = the assignee plus its direct reports",
]
check("B1 every self-explanatory paragraph is gone", all(g not in UI and g not in ORBIT for g in GONE),
      [g for g in GONE if g in UI or g in ORBIT])
check("B2 the non-obvious facts survive in SHORT form",
      "Local checks only" in UI and "data/config-backups/" in UI
      and "team = assignee + org reports" in ORBIT)
check("B3 the hook exit-code rule is kept (it is NOT self-evident)",
      "exiting <b>2</b> blocks the call" in UI)

print("\nv631: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
