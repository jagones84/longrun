#!/usr/bin/env python3
"""v439 — the RH Plan / chat-thread todo row: badge + ids on one line, the label on its
own full-width line under it.

Original scope (JAG-455): a todo row was one flat flex line
`[status] [id] [JN] [JN.x] [label …]`; when the label wrapped past two lines a JS
measurement moved it under the status/ID.

2026-11-22 ROUND 174 (operator: *"i todo in chat thread non possono contenere il testo
tutto a destra … deve stare in basso al done e Jx number così può occupare lo spazio
orizzontale invece di essere schiacciato"*). The wrapped-or-not split is gone: EVERY row
is the stacked shape, so the label always starts at the row's left edge at full width —
on a narrow Plan panel the flex row started it mid-row for any ordinary label. The JS
measuring pass (`_markWrappedTasks`, the `.stacked` class, the ResizeObserver) existed
only to decide WHEN to stack, so it is deleted with the fallback.

Deterministic, reads the sources as text (no browser).
Run: python3 tests/acceptance/v439_plan_row_wrap.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(REPO, "webui", "index.html")

with open(IDX, "r", encoding="utf-8") as f:
    idx = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- 1. the row is split into meta + main -----------------------------------
check("1a the row has a meta group", 'class="tmeta"' in idx)
check("1b the row has a main group", 'class="tmain"' in idx)
check("1c the label is its own span", 'class="tlabel"' in idx)
check("1d the per-todo rewind button is kept", 'class="task-rw"' in idx)
check("1e the label span wraps in main, not the flat row",
      '<span class="tmeta">${meta}</span><span class="tmain">${body}</span>' in idx)

# ---- 2. the CSS: one column, meta row, label full width ---------------------
check("2a .tmeta / .tmain are flex rows",
      ".task .tmeta { display: flex;" in idx and ".task .tmain { display: flex;" in idx)
check("2b the row is ONE column — meta above, label below (round 174)",
      ".task { display: grid; grid-template-columns: minmax(0, 1fr); gap: 3px; align-items: start; }" in idx)
check("2c the label takes the whole width and wraps in place",
      ".task .tmain { display: flex; flex-wrap: wrap; width: 100%; min-width: 0;" in idx
      and ".task .tlabel { flex: 0 0 100%; }" in idx)
check("2d status and id stay together in ONE meta row",
      ".task .tmeta { display: flex; flex-direction: row; align-items: center;" in idx)

# ---- 3. the two-lines measurement is gone (it only chose when to stack) -----
check("3a the measuring pass is deleted, not dormant", "function _markWrappedTasks" not in idx)
check("3b no caller survives it", "_markWrappedTasks(" not in idx)
check("3c the conditional `.stacked` variant is gone (the row IS the stacked shape)",
      ".task.stacked" not in idx and 'classList.add("stacked")' not in idx)
check("3d the chat-thread todo summary is the same anatomy",
      ".tctree > summary" in idx
      and "display: grid; grid-template-columns: minmax(0, 1fr); align-items: start;" in idx
      and ".tctree .tcmeta { display: flex; flex-direction: row; align-items: center; gap: 6px; }" in idx)

print("---")
okc = sum(results)
print("\nv439: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
