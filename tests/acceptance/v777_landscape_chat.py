#!/usr/bin/env python3
"""v777 — a phone in LANDSCAPE gives its room to the CHAT (RH-19).

Operator, verbatim: *"se metto il cellulare in orizzontale ruota lo schermo però in quel
layout non vedo la chat, troppo coperta … la barra in alto fa perdere spazio in primis e
va rimossa (quella con nome longrun, i tab control e sessions, sandbox e settings) … usa
icone invece dei nomi e mettile … crea un'altra barra laterale a sinistra"*.

Measured live on 844x390 (zoom .9) BEFORE the change: topbar 52 + chatHead 43 +
composer 152 + tabbar 68 = 315 of 390 px, so the transcript was 96 px. AFTER: the top
bar is a 44 px left rail (it leaves the flow), the tab bar keeps the icons and drops
the words, the session header loses only its duplicated id, and the composer tightens —
the transcript measures 225 px.

Deterministic: source contracts only. No browser, no server, no model.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The block itself: it must be the ONLY owner of this behaviour, gated on landscape.
_BLK = UI[UI.find("@media (orientation: landscape) and (max-height: 500px)"):]
_BLK = _BLK[:_BLK.find("\n  }") + 4] if "\n  }" in _BLK else _BLK
_REST = UI.replace(_BLK, "")
check("A0 the landscape block exists and is gated on orientation + height",
      "@media (orientation: landscape) and (max-height: 500px)" in UI and len(_BLK) > 800,
      len(_BLK))

check("A1 the TOP BAR leaves the flow and becomes a 44px LEFT RAIL",
      "#topbar {\n      position: fixed; left: 0; top: 0; bottom: 0; right: auto;" in _BLK
      and "width: 44px; height: auto; min-height: 0;" in _BLK
      and "flex-direction: column; align-items: center; justify-content: flex-start;" in _BLK)
check("A2 its labels are replaced by ICONS, and every icon keeps its NAME",
      "#topbar .logo { font-size: 0;" in _BLK
      and '#topbar #topTabs .ttab::before { content: attr(data-ic);' in _BLK
      and 'data-ic="▤"' in UI and 'data-ic="◫"' in UI
      and 'id="tabSessions"' in UI and 'aria-label="sessions"' in UI
      and 'aria-label="control deck"' in UI)
check("A3 the session name is printed ONCE (chatHead owns it, the badge goes)",
      "#topbar .sessbadge, #topbar .u-f1 { display: none; }" in _BLK
      and "#chatHead { height: 26px; min-height: 26px; padding: 0 8px; }" in _BLK
      and "#chatHead .ch-id { display: none; }" in _BLK)
check("A4 everything below the rail starts at its right edge",
      "#app { margin-left: 44px; }" in _BLK
      and "#controlView { top: 0; left: 44px; }" in _BLK
      and "body.show-left #aside {" in _BLK and "top: 0; left: 44px;" in _BLK
      and "body.show-right [data-col=\"context\"] { top: 0; }" in _BLK)
check("A5 the tab bar keeps the five icons and drops the five words",
      "#tabbar { height: 44px; min-height: 44px; }" in _BLK
      and "#tabbar button > span { display: none; }" in _BLK)
check("A6 the two floating edge handles are hidden (the rail and the tabs do their job)",
      ".edge-handle { display: none !important; }" in _BLK)
check("A7 the composer and the transcript get the reclaimed pixels",
      "#composer { padding-top: 4px; padding-bottom: 4px; gap: 4px; }" in _BLK
      and "#goalBar { height: 26px; min-height: 26px; }" in _BLK
      and "#inp { min-height: 32px; padding: 7px 11px; }" in _BLK
      and "#log { padding: 10px 12px; }" in _BLK)

# Regression guard: the landscape rule must not leak into the other layouts. Every
# selector above is INSIDE the media query, so a rule of the same name outside it would
# mean a second truth — assert the base declarations are untouched.
check("A8 the desktop/portrait layout is untouched",
      "#topbar { position: sticky; top: 0; z-index: 25; }" in _REST
      and "#tabbar button > span { display: none; }" not in _REST
      and "#app { margin-left: 44px; }" not in _REST)

print("\n---\nv777: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
