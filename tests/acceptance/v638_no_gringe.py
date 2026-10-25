#!/usr/bin/env python3
"""v638 — no gringe: one marker size, no boxes for numbers, no status paragraphs.

Operator (screenshot of Codebase): "ti sembrava elegante o è GRINGE?", "frecce di
menu delle sessioni troppo piccole, poi in Context i sub menu hanno frecce enormi",
"la frase save links this folder to THIS session — togli la, lo SPAZIO", "guarda
quello schifo di finestroni del codebase".

Contract:
  A) Codebase: no boxed stat cards — one line of counts, one line of provenance,
     the freshness sentence is plain text; the caps title + `#cbStat` are gone
     (the section header already carries both numbers).
  B) ONE disclosure marker in the rail: sessions groups, Context sub-menus and
     Rules all render the same 10px arrow (native <details> triangles removed).
  C) `.lnk` is underlined on hover only — a permanent dotted underline on a row of
     5 links reads as 5 broken words.
  D) The Workspace status sentence is gone (`#wsTarget`, `_wsTargetHint`).

Run: python tests/acceptance/v638_no_gringe.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v638_")
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

# ---- A. Codebase --------------------------------------------------------------
check("A1 the boxed stat cards are gone",
      "cb-metric" not in UI and "cb-location" not in UI and "cb-embedding" not in UI)
check("A2 counts are ONE line, provenance is ONE line",
      '<div class="cb-line"><b>\' + count(files) + "</b> files' in UI
      # 3 = counts line + provenance line + the empty-index branch (same class)
      and UI.count('class="cb-line"') == 3)
check("A3 the caps title and #cbStat are gone",
      "Codebase index" not in UI and 'id="cbStat"' not in UI)
check("A4 the freshness sentence is plain text (no box)",
      'class="cb-fresh"' in UI and "no re-index needed" in UI
      and ".cb-fresh { color: var(--ok); }" in UI)

# ---- B. one marker -----------------------------------------------------------
check("B1 the marker is declared once, for every inspector disclosure",
      'content: "\\25B8"; display: inline-block; width: 11px;' in UI
      and "#inspector details[open] > summary::before { content: \"\\25BE\"; }" in UI)
check("B2 the native triangle is suppressed in every engine",
      "#inspector details > summary::-webkit-details-marker { display: none; }" in UI
      and '#inspector details > summary::marker { content: ""; }' in UI)
check("B3 no second marker declaration in Rules",
      '.rulesrc > summary::before' not in UI)
check("B4 the session-group chevron matches (11px, was 9px)",
      ".sgroup-h .chev { font-size: 11px; width: 11px;" in UI)

# ---- C. links -----------------------------------------------------------------
check("C1 .lnk is plain, underlined on hover only",
      "cursor: pointer; text-decoration: none; }" in UI
      and ".lnk:hover { color: var(--txt); text-decoration: underline;" in UI
      and "text-decoration: underline dotted" not in UI)

# ---- D. Workspace -------------------------------------------------------------
check("D1 no status paragraph, no helper",
      'id="wsTarget"' not in UI and "_wsTargetHint" not in UI
      and "save links this folder to THIS session" not in UI)

print("\nv638: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
