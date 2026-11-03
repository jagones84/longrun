#!/usr/bin/env python3
"""v763 — the chrome is ONE instrument: monochrome icons, one box, no colour emoji.

Source (operator, 2026-11-01): "what is on top that orrible icon? a folder? thats
confusing... in general the settings button and the other on top are not standard
well placed" + "see for any other things to change according to your personal
screenshots in desktop and mobile image view".

Gap analysis (live, before this change):
  * the phone tab bar carried five COLOUR emoji (💬 🗂 ✅ 📊 📡) and each tab was a
    bordered pill, so the bar read as a row of stickers, not navigation;
  * the chat tool rail carried four colour emoji (📖 🎯 🧠 🏷) plus two text glyphs
    (⊞ ⊟) mixed with a painted diagonal bar over 🧠;
  * the composer mic was 🎙 (renders colour on Android);
  * the topbar session badge prefixed its title with 🗂 and, clipped to a sliver,
    rendered as a lone folder glyph — the icon the operator asked about.

Contract:
  A) the bottom tab bar is icon OVER label, one CSS truth, accent on the active tab;
  B) the chat tool rail is monochrome SVG, and the painted "slashed" bar is gone;
  C) the mic is an SVG with an accessible name;
  D) the session badge has no glyph, and its text is the title alone.

Deterministic: static contract checks on webui/index.html. No server, no model.
Run: python3 tests/acceptance/v763_ui_icons.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()

TABBAR = ui[ui.index('<div id="tabbar">'):]
TABBAR = TABBAR[:TABBAR.index("</div>")]
TOOLSBAR = ui[ui.index('<aside id="toolsBar"'):]
TOOLSBAR = TOOLSBAR[:TOOLSBAR.index("</aside>")]

# ---- A. the bottom tab bar ----------------------------------------------------
check("A1 five tabs, each an icon plus a label",
      TABBAR.count("<button data-tab=") == 5 and TABBAR.count("<svg") == 5
      and TABBAR.count("<span>") == 5)
check("A2 no colour emoji left in the tab bar",
      not re.search("[💬🗂✅📊📡]", TABBAR), "")
# RH-21 (ccf0b0e, 2026-11-03) gave the tab button a SECOND declaration: the landscape
# rail override (36px, icon only). The icon-over-label truth is still declared ONCE —
# the base/mobile rule — so the count is 2 and the FIRST one carries the 48px column shape.
check("A3 the tab button is declared ONCE (icon over label, 48px target)",
      ui.count("#tabbar button {") == 2
      and "flex-direction: column" in ui.split("#tabbar button {")[1].split("}")[0]
      and "min-height: 48px" in ui.split("#tabbar button {")[1].split("}")[0])
check("A4 the active tab is the single accent, not a second frame",
      "#tabbar button.active { color: var(--accent); background: transparent; }" in ui
      and "#tabbar button.active { color: var(--txt); border-color: var(--line-2)" not in ui)
check("A5 the bar keeps the theme token for its own background",
      "background: var(--menubg)" in ui[ui.index("#tabbar {"):ui.index("#tabbar button {")])

# ---- B. the chat tool rail ----------------------------------------------------
# RH-27 (operator, 2026-11-03): 8, not 7 — the settings gear moved into the rail's
# foot (level with the send button), so the static rail markup carries one more SVG.
# 2026-11-03 (later): 11 — the editor toggle (v779) plus the two pending-state controls
# (v780: changes / approvals), all wearing exactly this anatomy.
check("B1 every rail control is an SVG (11 of them)",
      TOOLSBAR.count("<button") == 11 and TOOLSBAR.count("<svg") == 11)
check("B2 no colour emoji and no box-drawing glyph left in the rail",
      not re.search("[📖🎯🧠🏷⊞⊟↻]", TOOLSBAR), "")
check("B3 the painted diagonal bar is gone (the icon carries the meaning)",
      "#toolsBar button.slashed" not in ui and 'class="ghost slashed"' not in ui)
check("B4 each rail control keeps its accessible name",
      len(re.findall(r"<button[^>]*>", TOOLSBAR)) == 11
      and all("aria-label=" in b and "title=" in b
              for b in re.findall(r"<button[^>]*>", TOOLSBAR)))

# ---- C. the composer mic ------------------------------------------------------
mic = ui[ui.index('id="micBtn"'):]
mic = mic[:mic.index("</button>")]
check("C1 the mic is an SVG, not the colour emoji",
      "<svg" in mic and "🎙" not in mic and 'aria-label="voice input"' in mic)

# ---- D. the topbar session badge ---------------------------------------------
check("D1 the badge shows the title alone (no 🗂 prefix)",
      'if (on) b.textContent = _activeTitle;' in ui and "\\uD83D\\uDDC2" not in ui)
check("D2 a phone hides it (the chat head directly below already names the session)",
      "#sessBadge { display: none !important; }" in ui)

# ---- E. the two topbar actions ----------------------------------------------
check("E1 settings and search share one monochrome 32px box",
      "#settingsBtn, #palette-open { width: 32px; height: 32px; padding: 0; border-radius: 8px;" in ui
      and ui.count("<circle cx=\"12\" cy=\"12\" r=\"3\"") == 1)
PAL = ui[ui.index("function paletteItems() {"):]
PAL = PAL[:PAL.index("\n}\n")]
check("E2 the command palette rows carry no colour glyph (⚙ / 🗂)",
      "\\u2699" not in PAL and "\\uD83D\\uDDC2" not in PAL
      and 'label: "Open settings"' in PAL and 'label: "Settings \\u25B8 "' in PAL)

print("---\n\nv763: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
