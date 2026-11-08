#!/usr/bin/env python3
"""v895 — panes are ONE continuous surface, the ROLE.md pencil lives in the row's ⋮
menu, the two prompt marks are glyphs on the row's second line, and the Model column
is as wide as the refs it shows.

Operator, 2026-11-08:
  *"too much space between panes shall be continuous attached"* ·
  *"the edit button shall be placed in the three dot menu inside edit prompt"* ·
  *"the AI made shall be put with a symbol, the prompt role.md void with asterisks but
  small and occupy low horiz space shall be put in vertical space to save it"* ·
  *"the llm model shall be all visible if there is space and squeeze only if stretched
  and no more space available"*.

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


# ---------------- A: the panes touch, the splitters cost nothing ---------------
check("A1 a view row has no gap (panels share one hairline)",
      "main.view-cols .vrow{display:flex;flex-direction:row;gap:0;width:100%;" in ORBIT)
check("A2 the column splitter is a zero-width overlay with its own hit-area",
      "main.view-cols .vrow > .rz-vcol{flex:0 0 0;width:0;min-width:0;position:relative;z-index:6}" in ORBIT
      and 'main.view-cols .vrow > .rz-vcol::before{content:"";position:absolute;top:0;bottom:0;left:-4px;right:-4px}' in ORBIT)
check("A3 a multi-pane deck is square and drops the doubled border",
      "main.view-cols section.panel[data-panel]{border-radius:0}" in ORBIT
      and "main.view-cols .vrow > section.panel[data-panel] + .rz-vcol + section.panel[data-panel]{border-left:0}" in ORBIT)
check("A4 the BOARD columns touch too (0 track + 0 gap + square panes)",
      "grid-template-columns:var(--cA,minmax(0,1.38fr)) 0 var(--cB,minmax(0,1fr));gap:0;align-items:stretch}" in ORBIT
      and ".rz-cols{align-self:stretch;justify-self:center;width:0;position:relative;z-index:6;" in ORBIT
      and ".col{display:flex;flex-direction:column;gap:0;min-width:0}" in ORBIT
      and ".col > .panel + .panel{border-top:0}" in ORBIT
      and ".grid2.ab section.panel,.grid2.oc section.panel{border-radius:0}" in ORBIT)
check("A5 stacked ROWS touch as well (zero-height splitter, overlay hit-area)",
      ".rz-vrow{width:100%;height:0;flex:0 0 0;position:relative;z-index:6;cursor:ns-resize;" in ORBIT
      and '.rz-vrow::before{content:"";position:absolute;left:0;right:0;top:-4px;bottom:-4px}' in ORBIT)
check("A6 a LONE panel keeps its rounded frame",
      "main.view-one section.panel[data-panel]{min-height:0;flex:1 1 auto;border-radius:var(--r)}" in ORBIT)

# ---------------- B: the ROLE.md pencil moved INTO the ⋮ menu -------------------
check("B1 four columns (ID | Agent | Model | menu), no Role.md header",
      '<col class="c-model"><col class="c-act">' in ORBIT
      and "<th>Role.md</th>" not in ORBIT and 'class="c-file"' not in ORBIT)
check("B2 the old prompt cell and its CSS are GONE (no dead object)",
      'data-brief' not in ORBIT and "pbtn" not in ORBIT
      and "col.c-file" not in ORBIT)
check("B3 the menu item is 'edit prompt (ROLE.md)' and it calls the one opener",
      'data-amenu="prompt">\\u270E edit prompt (ROLE.md)' in ORBIT
      and "m.querySelector('[data-amenu=\"prompt\"]').onclick = () => { closePopover(); this.openPrompt(a); };" in ORBIT)
check("B4 ONE implementation: AgentsView.openPrompt + togglePrompt (org menu delegates)",
      "openPrompt(a){" in ORBIT and "togglePrompt(sid){" in ORBIT
      and "this.togglePrompt(a.session);" in ORBIT
      and "if (this.onPrompt) this.onPrompt(a);" in ORBIT
      and "(a) => this.agents.openPrompt(a)" in ORBIT)
check("B5 the brief still opens through the SAME endpoint",
      '"/api/roles?session=" + encodeURIComponent(sid)' in ORBIT)

# ---------------- C: the two prompt marks are glyphs on the second line --------
check("C1 the AI provenance badge is a bare glyph (no box, no padding)",
      ".aibadge{display:inline-block;margin:0;padding:0;border-radius:0;font-size:10px;line-height:1;" in ORBIT
      and "background:none;color:var(--acc);vertical-align:middle;cursor:help}" in ORBIT)
check("C2 it renders the symbol, not the word",
      '\'">\\u2726</span>\'' in ORBIT and '\'">AI</span>\'' not in ORBIT)
check("C3 the empty-prompt star is a 10px glyph with no margin",
      ".req{color:var(--err);font-weight:700;margin-left:0;font-size:10px;line-height:1}" in ORBIT)
check("C4 both marks ride the row's SECOND line (vertical space, not a column)",
      "const voidMark = voidP ?" in ORBIT
      and '\'<span class="asub">\' + aiBadge + voidMark + \'<span class="arole">\'' in ORBIT)

# ---------------- D: the model column fits what it shows ----------------------
check("D1 the cell shows the WHOLE model ref (no last-segment truncation)",
      'const modelLabel = a.model ? String(a.model) : "default";' in ORBIT
      and 'String(a.model).split("/").slice(-1)[0]' not in ORBIT)
check("D2 the cell is a .mcell so the fitter can find it",
      '\'<td class="mcell">' in ORBIT)
check("D3 the width is measured from the rendered text, never past the table",
      'document.createElement("canvas").getContext("2d")' in ORBIT
      and 'col.style.width = Math.min(w, room) + "px";' in ORBIT)
check("D4 it re-fits after every render AND on every panel width change",
      "this._applyFocus();\n    this._fitModelCol();" in ORBIT
      and "this._mcolRO = new ResizeObserver(() => this._fitModelCol()); this._mcolRO.observe(wrap);" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
