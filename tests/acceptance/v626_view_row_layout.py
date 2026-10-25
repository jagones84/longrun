#!/usr/bin/env python3
"""v626 — view layout: rows × columns grid with reversible resize.

  A  panels chunk into rows of N columns (N = columns the deck fits ≥280px):
     a wrapped panel FILLS its row (rows are full-width flex lines).
  B  column widths persist as per-row RATIOS (not px) → drags are reversible
     and scale with the window; structure can flow back to the first row.
  C  row heights resize per ROW via a horizontal splitter between rows.
  D  mobile (≤1100px) keeps the plain vertical stack; resize re-flow triggers
     only when the column count changes.
  E  reset layout clears the ratio + row-height keys.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v626_view_row_layout.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("A1 panels chunk into full-width rows of N fitting columns",
      'for (let i = 0; i < vis.length; i += ncols) rows.push(vis.slice(i, i + ncols))' in ORBIT
      and 'row.className = "vrow"' in ORBIT
      and "deck.clientWidth - 12) / minCol" in ORBIT)
check("A2 a wrapped row fills the row width (rows are full-width lines)",
      "main.view-cols .deckBody.vrows{flex-direction:column;flex-wrap:nowrap;gap:0}" in ORBIT
      and "main.view-cols .vrow{display:flex;flex-direction:row;gap:8px;width:100%;" in ORBIT)
check("B1 column widths persist as per-row RATIOS, not px",
      '"vrat:" + this.view + ":" + r + ":" + c' in ORBIT
      and "p.getBoundingClientRect().width / rowW" in ORBIT)
check("B2 ratios are stored as flex-basis percentages (reversible, window-scaling)",
      'p.style.flex = "0 0 " + (this._vcolRatio(saved, r, c, rowPanels.length) * 100).toFixed(4) + "%"' in ORBIT)
check("B3 panels restore home via slot markers BEFORE rows are dropped (re-entrant safe)",
      'p._vmark.parentElement.insertBefore(p, p._vmark)' in ORBIT
      and 'p._vmark = document.createComment("vslot:" + (p.dataset.panel || ""))' in ORBIT
      and ORBIT.index("p._vmark.parentElement.insertBefore") < ORBIT.index('".vrow,.rz-vcol,.rz-vrow"'))
check("C1 a horizontal splitter resizes the whole ROW above, per row",
      'sp.className = "rz-vrow"; sp.title = "drag to resize this row"' in ORBIT
      and '"vrowh:" + this.view + ":" + r' in ORBIT
      and "const h = Math.max(220, Math.min(3000, h0 + (ev.clientY - y0)))" in ORBIT)
check("C2 row splitter sits between the two rows",
      "deck.insertBefore(sp, rowB)" in ORBIT)
check("D1 mobile (<=1100px) keeps the plain vertical stack (no rows built)",
      'if (window.matchMedia("(max-width:1100px)").matches) return; // mobile stack' in ORBIT
      and "@media (max-width:1100px){ .rz-vrow{display:none} .vrow{height:auto} }" in ORBIT)
check("D2 window resize re-flows only when the column count changes (live panel count)",
      "if (c !== this._vlastNCols) this._layoutViewCols()" in ORBIT
      and "this._vlastNCols = ncols" in ORBIT
      and "count VISIBLE panels live" in ORBIT)
check("E1 reset layout clears ratio + row-height keys",
      'k.indexOf("vrat:") === 0 || k.indexOf("vrowh:") === 0' in ORBIT)

print("---")
ok = sum(results)
print("\nv626: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
