#!/usr/bin/env python3
"""v439 — stack the RH Plan panel todo label after two wrapped lines (JAG-455).

A todo row was one flat flex line: `[status] [id] [JN] [JN.x] [label …]`. When the
label wrapped beyond 2 lines, move it onto its own full-width row below the status
and ID, giving it the available horizontal space without vertically stacking the
metadata.

Deterministic, reads the sources as text (no browser). Run: python3 tests/acceptance/v439_plan_row_wrap.py
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

# ---- 2. the CSS lays the two groups out + the stacked variant ---------------
check("2a .tmeta / .tmain are flex rows",
      ".task .tmeta { display: flex;" in idx and ".task .tmain { display: flex;" in idx)
check("2b .tmain can shrink (min-width: 0) so a wrapped label is measured right",
      ".task .tmain { display: flex; gap: 6px; align-items: baseline; flex: 1 1 auto; min-width: 0; }" in idx)
check("2c stacked rows put the label on its own full-width line",
      ".task.stacked .tmain {" in idx and ".task.stacked .tlabel { flex: 0 0 100%; }" in idx)
check("2d stacked rows keep status and id together (one meta COLUMN)",
      ".task.stacked .tmeta { flex-direction: column; align-items: flex-start;" in idx)

# ---- 3. the JS measurement pass ---------------------------------------------
check("3a _markWrappedTasks is defined", "function _markWrappedTasks(box)" in idx)
check("3b it counts text line boxes and stacks after two lines",
      "range.getClientRects()" in idx and "lines.size > 2" in idx
      and 'el.classList.add("stacked")' in idx)
check("3c it is called after the plan graph renders", "_markWrappedTasks(box);" in idx)
check("3d it re-marks when the panel width changes (splitter/drawer/zoom)",
      'new ResizeObserver(() => {' in idx and "_markWrappedTasks(_tb);" in idx)
check("3e it re-marks when the tasks tab is opened on mobile",
      'if (name === "tasks") requestAnimationFrame(() => _markWrappedTasks($("tasks")));' in idx)

print("---")
okc = sum(results)
print("\nv439: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
