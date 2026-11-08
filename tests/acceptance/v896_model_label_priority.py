#!/usr/bin/env python3
"""v896 — the Agent NAME never pays for the Model column, and the model label degrades
in steps (provider prefix → path → model name → ellipsis) as the panel narrows.

Operator, 2026-11-08:
  *"the LLM model shall not overlap the agent name … the prefix openrouter can
  disappear in case of needs squeeze just the initial model name can remain on that
  case dynamically"*.

Deterministic: reads the Control deck, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: the name is never the one that pays ----------------------
check("A1 the model column is bounded by a reserved, readable name width",
      "const MIN_NAME = 110;" in ORBIT
      and "const room = Math.max(56, avail - ID_W - ACT_W - MIN_NAME);" in ORBIT)
check("A2 the old percentage cap (the cause of the squeeze) is gone",
      "avail * 0.55" not in ORBIT)
check("A3 the column is written from the measured need, clamped by that room",
      'col.style.width = Math.min(w, room) + "px";' in ORBIT)

# ---------------- B: the label degrades in steps ------------------------------
check("B1 one label function: whole ref → no provider → model name",
      "_modelLabel(ref, level){" in ORBIT
      and 'r.replace(/^[a-z0-9_-]+:/i, "")' in ORBIT
      and 'noProv.split("/").slice(-1)[0] || noProv' in ORBIT)
check("B2 the ladder keeps the LONGEST level that fits, then falls back to the model name",
      "for (let l = 0; l <= 2; l++){" in ORBIT
      and "if (need <= room){ level = l; w = Math.ceil(need); break; }" in ORBIT
      and 'this._modelLabel(el.getAttribute("data-m"), Math.min(level, 2))' in ORBIT)
check("B3 the visible text is rewritten per level (not only the column width)",
      'const t = this._modelLabel(el.getAttribute("data-m"), Math.min(level, 2));' in ORBIT
      and "if (el.textContent !== t) el.textContent = t;" in ORBIT)

# ---------------- C: nothing is lost when the label degrades ------------------
check("C1 the FULL ref is kept on the cell (data-m) so a wider panel restores it",
      '<span class="cv" data-m="\' + esc(a.model || "default") + \'">' in ORBIT)
check("C2 the tooltip still carries the full model",
      'title="model: \' + esc(a.model || "router default") + \'"' in ORBIT)
check("C3 the cell still opens the model editor (same endpoint as before)",
      'data-aedit="model"' in ORBIT and 'kind === "model"' in ORBIT)

# ---------------- D: it re-fits when the room changes -------------------------
check("D1 fitted after every render and on every panel width change",
      "this._applyFocus();\n    this._fitModelCol();" in ORBIT
      and "new ResizeObserver(() => this._fitModelCol())" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
