#!/usr/bin/env python3
"""v1257 — the Workspace/Plan menu drops UP, the phone header has ONE anatomy, and the
filter panel is a themed sheet.

Operator (2026-11-22, round 173): *"ma perché la barra sopra msg box plan e workspace si
alzano? devono rimanere in basso, se clicco si apre il menu sopra"*; *"ci sono menu che non
sono coerenti col theme, soprattutto mobile, per esempio il filtro"*; *"icone minuscole nella
barra, il cerca lente … disallineate, guarda e capisci da solo cosa va fatto"*.

  A  the borrowed body is a DROPUP: opening a tab never moves the composer
  B  one 30×30 anatomy in the phone header (no 5 px lens, one baseline)
  C  the FilterSort panel: sentence-case labels, full-width 36 px sheet on a phone
  D  the rail toolbar is SVG (no emoji magnifier)

Deterministic and offline: static pins on webui/index.html + webui/assets/filtersort.css.
Run: python3 tests/acceptance/v1257_dropup_header_and_filter_sheet.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
FS = open(os.path.join(REPO, "webui", "assets", "filtersort.css"), encoding="utf-8").read()
FS_JS = open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


# ---- A: the dropup ---------------------------------------------------------
check("A1 the body is absolutely positioned above the strip",
      "#cmpSuper { display: flex; flex-direction: column; min-width: 0; position: relative; }" in HTML
      and ".cs-body { position: absolute; left: 0; right: 0; bottom: calc(100% + 6px);" in HTML)
check("A2 it is a menu surface, not a bare in-flow block",
      "background: var(--menubg); border: 1px solid var(--line-2); border-radius: 10px;" in HTML
      and "box-shadow: 0 18px 48px rgba(0, 0, 0, .46); z-index: 70;" in HTML)
check("A3 it stays inside the viewport height and scrolls",
      "max-height: min(52vh, 340px); overflow: auto;" in HTML)

# ---- B: one phone header anatomy ------------------------------------------
_BAND = HTML.split("@media (max-width: 480px) and (min-height: 501px)")[1][:1600]
check("B1 an icon is never the item that shrinks",
      "#topbar button > svg, #topbar a > svg, #topbar span > svg { flex: 0 0 auto; }" in HTML)
check("B2 every right-side control is the same 30×30 box",
      "#topbar #palette-open, #topbar #settingsBtn, #topbar #changelogBtn {" in _BAND
      and "width: 30px; min-width: 30px; height: 30px; padding: 0;" in _BAND
      and "#topbar .brand-menu-btn { width: 30px; height: 30px; min-height: 30px; }" in _BAND)
check("B3 the sandbox dot and the approvals ✓ share that box",
      "#topbar #sbxPill, #topbar #apprPill {" in _BAND
      and "width: 30px; height: 30px; min-height: 30px; padding: 0;" in _BAND)
check("B4 the narrower tiers shrink the SAME boxes (no mixed sizes)",
      "@media (max-width: 360px) and (min-height: 501px)" in HTML
      and "#topbar #sbxPill, #topbar #apprPill { width: 28px; height: 28px; min-height: 28px; }" in HTML
      and "#topbar #sbxPill, #topbar #apprPill { width: 25px; height: 25px; min-height: 25px; }" in HTML)

# ---- C: the filter panel ---------------------------------------------------
check("C1 labels are sentence case at the app's 11px",
      ".fs-l {\n  color: var(--dim, #9aa1ae); font-size: 11px; min-width: 34px;" in FS
      and "text-transform: uppercase" not in FS)
check("C2 a phone gets a full-width sheet with 36px controls",
      "@media (max-width: 640px)" in FS
      and "left: 8px !important; right: 8px; width: auto; min-width: 0; max-width: none;" in FS
      and ".fs-inp { height: 36px; padding: 0 8px; font-size: 13px; }" in FS
      and ".fs-dir { width: 36px; height: 36px; font-size: 14px; }" in FS)
check("C3 it keeps the shared surface (one module, one look)",
      ".fs-pop {" in FS and ".fs-pop {" not in HTML)
check("C4 every control has a NAME, not only a title (axe: label-title-only)",
      'data-fs="team" aria-label="team"' in FS_JS
      and 'data-fs="sort" aria-label="sort"' in FS_JS
      and 'aria-label="sort direction"' in FS_JS
      and 'dirBtn.setAttribute("aria-label"' in FS_JS)

# ---- D: the rail toolbar ---------------------------------------------------
_RAIL = HTML[HTML.index('id="railNew"'):HTML.index('id="runsBar"')]
check("D1 new + search are SVG glyphs, not text/emoji",
      "🔍" not in _RAIL and _RAIL.count("<svg") >= 2
      and "M12 5v14M5 12h14" in _RAIL and "m19.5 19.5-3.6-3.6" in _RAIL)
check("D2 both keep their names",
      'aria-label="new session"' in _RAIL and 'aria-label="search sessions"' in _RAIL)
_CHATSEARCH = HTML.split('id="chatSearchToggle"')[1].split("</button>")[0]
check("D3 the in-chat search is the same SVG lens, not the emoji either",
      "🔍" not in _CHATSEARCH and "m19.5 19.5-3.6-3.6" in _CHATSEARCH
      and 'aria-label="search this chat"' in _CHATSEARCH)

print("\n---\nv1257: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
