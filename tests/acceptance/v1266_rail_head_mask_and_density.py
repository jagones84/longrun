#!/usr/bin/env python3
"""v1266 — the inspector head masks its scroll, the fold control loses its frame, and
the sessions rail stops paying three layers of vertical air (round 183).

Operator, 2026-11-22, with two screenshots:
  *"see image inspector bar is overlapped in scroll of rh panel. fix."* — the head
  was a frameless label pinned with `position: sticky` and `background: transparent`,
  so the section scrolling under it printed THROUGH it ("clear decided" above the
  word INSPECTOR).
  *"i dont like the collasp expand button of framed. and thers to much space in
  session bar and below vert space wasted."*

Contract:
  A) the pinned inspector head paints the panel's own background under itself AND
     across the 12px gutter above it — no section can show in the scroll band;
  B) the fold control is still beside the section name with a 24px target, but it has
     NO frame: border 0, transparent surface, hover is the only surface;
  C) the sessions rail head is 28px, the block gap 6px and the tools strip carries a
     6px bottom padding only — the three layers that made the bar tall;
  D) both heads still start on the SAME line (12px from the topbar).

Deterministic: reads webui/index.html. No browser, no server, no model.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:200]) if detail and not ok else ""))


def block(start, stop):
    i = UI.find(start)
    return UI[i:UI.find(stop, i)] if i >= 0 else ""


# ---- A: the head masks the scroll ------------------------------------------
STICKY = "#inspector .insp-tools { position: sticky; top: 12px; z-index: 3; margin-top: 12px; }"
check("A1 the head is still pinned inside the panel scroller",
      STICKY in UI)
check("A2 the pinned head paints the panel background under itself",
      "#inspector .insp-tools { background: var(--bg); }" in UI)
_MASK = block("#inspector .insp-tools::before {", "}")
check("A3 a ::before covers the 12px gutter the scroll used to show in",
      "position: absolute" in _MASK and "top: -12px" in _MASK
      and "height: 12px" in _MASK and "background: var(--bg)" in _MASK, _MASK)
check("A4 the mask is the panel colour, not a new surface token",
      "--hd-surf" not in UI and "var(--panel)" not in _MASK)

# ---- B: the fold control has no frame -------------------------------------
_FOLD = block("aside .rail-head h2 .fold-tg, #inspector .insp-tools h2 .fold-tg {", "}")
check("B1 the fold control is still one 24px target",
      "width: 24px; height: 24px" in _FOLD, _FOLD)
check("B2 no frame: no border, transparent surface",
      "border: 0" in _FOLD and "background: transparent" in _FOLD
      and "1px solid" not in _FOLD, _FOLD)
check("B3 hover is the only surface and the open state keeps full contrast",
      "background: var(--hover); color: var(--txt); }" in UI
      and "background: transparent; color: var(--txt); }" in UI)
check("B4 the control still sits beside the label inside .hd-left",
      '<span class="hd-left"><span class="hd-name">Sessions</span>'
      '<button type="button" id="railToggleAll" class="fold-tg"' in UI
      and '<span class="hd-left"><span class="hd-name">Inspector</span>'
      '<button type="button" id="inspToggleAll" class="fold-tg"' in UI)

# ---- C: the sessions rail lost its three layers of air ---------------------
check("C1 the shared head metric is one 24px control row (28px)",
      ":root { --rail-hd: 28px; --rail-row: 29px;" in UI)
check("C2 the head carries no bottom margin",
      "height: var(--rail-hd); min-height: var(--rail-hd); margin: 0;" in UI)
check("C3 one 6px block gap in the rail",
      "aside .rail { display: flex; flex-direction: column; gap: 6px;" in UI)
check("C4 the tools strip is one 6px strip on the label's edge",
      "aside .rail-tools { gap: 4px; padding: 0 0 6px; border-bottom: 0; }" in UI)
check("C5 the search row keeps the same edge when it opens",
      "aside .rail-search { padding: 4px 0 6px;" in UI)
check("C6 2px head padding, so the 24px row alone sets the height",
      "aside .rail-head, #inspector .insp-tools { height: auto; min-height: var(--rail-hd);\n"
      "    padding-top: 2px; padding-bottom: 2px; }" in UI)

# ---- D: the two labels still start on the same line ------------------------
check("D1 both rails start 12px from the topbar",
      "#aside { padding-top: 12px; }" in UI and "top: 12px; z-index: 3; margin-top: 12px;" in UI)
check("D2 the head is still declared once for both rails",
      "aside .rail-head, #inspector .insp-tools {" in UI
      and "background: transparent; border: 0; border-radius: 0;" in UI)

print("---\nv1266: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
