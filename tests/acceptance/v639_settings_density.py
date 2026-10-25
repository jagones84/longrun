#!/usr/bin/env python3
"""v639 — Settings and its dialogs use the rail's size.

The window was the last surface still authored at the 14px/8-14px-padding scale:
full-size buttons, a prose line above every panel, and a dialog with the browse
affordance spelled out twice.

Contract:
  A) Compaction panel: the "Global policy — not session-specific" sentence left
     the body (the rule survives in the title tooltip).
  B) ONE rule sizes every Settings button like the rail's (11px / 4-9px).
  C) The main column uses the rail's padding rhythm.
  D) New session dialog: `folder` label, short placeholder, icon-only browse with
     an accessible name.

Run: python tests/acceptance/v639_settings_density.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v639_")
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

# ---- A. Compaction panel ------------------------------------------------------
check("A1 the panel intro sentence is gone",
      "Global policy — not session-specific. Click a config filename to open it." not in UI)
check("A2 the rule survives in the title tooltip",
      'title="global policy — not session-specific; click a config filename to open it"' in UI)

# ---- B/C. shell ---------------------------------------------------------------
check("B1 one rule sizes every Settings button like the rail",
      "#settingsWin button.ghost { font-size: 11px; padding: 4px 9px; border-radius: 8px; }" in UI)
check("C1 the main column uses the rail's padding",
      "#settingsWin .sw-main { flex: 1; min-width: 0; overflow-y: auto; padding: 10px 12px; }" in UI)

# ---- D. new session dialog ----------------------------------------------------
check("D1 the folder field lost the duplicated affordance",
      '<label class="remaining u-db u-mt10" for="nsWs">folder</label>' in UI
      and 'placeholder="empty = default folder"' in UI
      and "📁 browse…</button>" not in UI)
check("D2 browse is an icon button with an accessible name",
      'data-call="openDirPicker" aria-label="browse folders"' in UI)
check("D3 the dialog still creates through the same door",
      'id="nsTitle"' in UI and 'data-call="createNewSession"' in UI)

print("\nv639: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
