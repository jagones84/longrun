#!/usr/bin/env python3
"""v644 — Control deck: a custom view always ends ON the browser edge.

Operator, verbatim: "guarda immagine (control page views) perché la fine dell'ultimo
RH panel non si allinea al bordo esterno? si deve adattare alle dimensioni del
browser ospitante".

Gap analysis: the view row sized every panel with `flex: 0 0 <ratio>%`. A basis
percentage is a share of the ROW, which also contains the 8px gaps and the 5px
splitters — so even a fresh 4 × 25% set overflowed by 39px, and a saved set from
a drag could hand one panel 83% (measured live: 16.6 + 15.7 + 18.3 + 83.3 =
133.8% of the row, scrollWidth 2645 > deck 1929). The right-most panel therefore
ran past the deck border instead of ending on it.

Fix: grow factors (`<share> 1 0`) which the flexbox normalises itself, a drag
that writes pixel factors for the whole row, and ratios saved as shares of the
columns' own total so they always sum to 1.

Contract:
  A) view columns are sized with grow factors, never with a percentage basis.
  B) a drag rewrites every panel of the row, so the row keeps filling the deck.
  C) saved ratios are shares of the columns' total (sum = 1).
  D) a column cannot collapse below a readable width.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v644_view_cols_fit.py
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


check("A1 view columns are sized with GROW factors",
      'p.style.flex = ratios[c] + " 1 0"' in ORBIT)
check("A2 no percentage basis is left in the view layout",
      '"0 0 " + (this._vcolRatio' not in ORBIT
      and 'p.style.flex = "0 0 "' not in ORBIT)
check("C2 a corrupt saved set (old drag math, sum != 1) falls back to equal shares",
      "if (rsum < 0.9 || rsum > 1.1) ratios = rowPanels.map(() => 1 / rowPanels.length);" in ORBIT)
check("B1 a drag rewrites the two dragged panels in pixels",
      "A.style.flex = a + \" 1 0\";" in ORBIT and "B.style.flex = b + \" 1 0\";" in ORBIT)
check("B2 the untouched panels freeze at their current width during a drag",
      'if (p !== A && p !== B) p.style.flex = p.getBoundingClientRect().width + " 1 0";' in ORBIT)
check("B3 no percentage basis is written by the drag either",
      'A.style.flex = "0 0 "' not in ORBIT)
check("C1 ratios are shares of the columns' own total (they sum to 1)",
      "const total = widths.reduce((a, b) => a + b, 0) || 1;" in ORBIT
      and "widths[c] / total" in ORBIT)
check("D1 a column keeps a readable minimum width",
      "main.view-cols .vrow > section.panel[data-panel]{min-width:180px;min-height:0}" in ORBIT)
check("D2 the rows still fit, so that minimum can never overflow the deck",
      'const minCol = 280;' in ORBIT
      and "Math.floor(Math.max(minCol, deck.clientWidth - 12) / minCol)" in ORBIT)

print("---")
ok = sum(results)
print("\nv644: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
