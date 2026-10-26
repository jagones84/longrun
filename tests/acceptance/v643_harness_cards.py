#!/usr/bin/env python3
"""v643 — Settings ▸ Harness: ONE card format (title · subtitle · save on one row).

Operator, verbatim: "guarda 3 immagini cristo bold eccetera no è rispettato allo
stesso modo, il format cambia da setting a setting fa schifo tutto, refactor.
Minimalista senza perdere funzioni" and "frasi ridondanti".

Contract:
  A) Every Harness card is `.card.hcard` with exactly ONE header row
     (`.hcard-hd`) carrying the title, the subtitle AND the save button.
  B) The explanation that used to be a visible paragraph is a tooltip on the
     header — no card keeps a `remaining u-m006` paragraph.
  C) Each card still owns exactly ONE `.config-save` button (no duplicate save
     stacked under the fields), and the buttons keep their `data-call` target.
  D) The save button is pushed to the end of the header row by CSS, so every
     card reads the same way.

Run: python tests/acceptance/v643_harness_cards.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v643_")
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

# ---- the harness panel only --------------------------------------------------
start = UI.index('<div class="sw-cat" data-cat="harness"')
end = UI.index('<div class="sw-cat"', start + 10)
PANEL = UI[start:end]

cards = re.findall(r'<div class="card hcard"[^>]*>(.*?)\n        </div>', PANEL, re.S)
check("A1 six harness cards", len(cards) == 6, len(cards))

# ---- A. one header row per card ---------------------------------------------
hdrs = re.findall(r'<div class="hcard-hd"[^>]*>(.*?)</div>', PANEL, re.S)
check("A2 every card has exactly one header row", len(hdrs) == len(cards), (len(hdrs), len(cards)))
check("A3 every header carries the save button",
      all("config-save" in h for h in hdrs),
      [("config-save" in h) for h in hdrs])
check("A4 every header carries the title and the subtitle",
      all("<b>" in h and 'class="hc-sub"' in h for h in hdrs))

# ---- B. prose is a tooltip, never a paragraph --------------------------------
check("B1 no card keeps a visible explanation paragraph",
      "remaining u-m006" not in PANEL)
titles = re.findall(r'<div class="hcard-hd" title="([^"]{25,})"', PANEL)
check("B2 all six explanations survive as header tooltips", len(titles) == 6, len(titles))
for phrase in ("continue on its own", "verification command", "independent answers",
               "how hard the task is", "recurring patterns",
               "cumulative prompt+completion tokens"):
    check("B3 tooltip keeps the words: " + phrase, any(phrase in t for t in titles))

# ---- C. one save per card, same targets -------------------------------------
check("C1 exactly one save button per card", len(re.findall(r'class="ghost config-save"', PANEL)) == 6)
for target in ("saveRuntime", "saveVerifier", "saveBudget", "saveBestofn",
               "saveDifficulty", "saveSelfevolve"):
    check("C2 the target survives: " + target, ('data-call="%s"' % target) in PANEL)
check("C3 the save is not stacked under the fields any more",
      not re.search(r'</div>\s*<button class="ghost config-save"', PANEL))

# ---- D. same visual placement ------------------------------------------------
check("D1 the save is pushed to the end of the header row",
      ".hcard-hd .config-save { margin-left: auto; }" in UI)

# ---- F. constructed cards follow the same shape ------------------------------
# The panels below the hand-written cards (Decision layer, Team jobs, Trace
# policy, …) are rendered from settings.py sections. They used to put the save on
# a SECOND row, which is exactly the "format changes from setting to setting"
# defect. Same shape now: title left, actions at the end of the same row.
check("F1 the renderer emits a header row", 'card.innerHTML = \'<div class="set-hd">\' +' in UI)
_fn = UI[UI.index("function _setSectionEl"):UI.index("function _setFieldEl")]
check("F2 the actions live inside the header, before the fields",
      _fn.index('class="set-hd"') < _fn.index('class="set-acts"') < _fn.index("data-fields"))
check("F3 the header pushes its actions to the right",
      "#swMain .set-hd .set-acts { margin: 0 0 0 auto; }" in UI)

# ---- E. every field still there (no function lost) ----------------------------
for fid in ("rtKgMax", "rtNoProg", "rtWall", "rtDepth", "rtParallel", "rtAuto",
            "vfOn", "vfCmd", "vfTimeout", "vfPaths",
            "bdMax",
            "bnOn", "bnN", "bnMin",
            "dfOn", "dfEasy", "dfMed", "dfHard", "dfMedAt", "dfHardAt",
            "seMinLen", "seMinCount", "seMaxLen", "seCat"):
    check("E1 field still present: " + fid, ('id="%s"' % fid) in PANEL)

print("\nv643: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
