#!/usr/bin/env python3
"""v1028 — the squeezed topbar keeps EVERY object visible, at every width.

Operator, 2026-11-15:
  *"in mobile squeezed format not all objects are visible, you have to find a better way
    for the squeezed case."*
  *"still there are sizes that do not display all … every size shall fit … leave an icon
    (mouse ON reveals what they are)."*

Measured on the live page before the fix (real approval chip painted):
  * 770 px bar → 820 px of content: the settings gear sat OUTSIDE the viewport;
  * 390 px bar → the search and the gear were gone;
  * 320 px bar → the gear was clipped.
The header answered with `overflow-x: auto`, so its right end silently slid out of sight.
The fix is a squeezed grammar, not less content:

  A) the four section tabs are drawn SVG icons at EVERY width (aria-label + title carry
     the names — the operator: "use only icons always"); below 980 px the sandbox
     becomes its dot and the approval mode its ✓, also with aria-label + title;
  B) the session badge leaves the squeezed bar (below 1101 px, the panel-drawer
     threshold) and is never shown on My Artifacts / Marketplace, which own their row;
  C) at 320 px the tabs/chip tighten so the gear still keeps the bar's padding;
  D) nothing is removed: sandbox, approval mode, search and settings all remain.

Deterministic: static contract on webui/index.html. No browser, no server, no net.
Run: python3 tests/acceptance/v1028_squeezed_header.py
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def block(marker, length=1400):
    at = UI.find(marker)
    if at < 0:
        return ""
    end = UI.find("\n  }", at)
    return UI[at:end if end > 0 else at + length]


SQUEEZED = block("@media (max-width: 980px) and (min-height: 501px)")
NARROW = block("@media (max-width: 360px) and (min-height: 501px)")
TOPBAR = UI[UI.find('<header id="topbar">'):UI.find("</header>", UI.find('<header id="topbar">'))]

TABS = re.findall(r'<a class="ttab[^>]*>.*?</a>', UI, re.S)

# ---- A: the squeezed bar is icons + tooltips -----------------------------------
check("A1 a squeezed-width rule exists (980 px, portrait)", bool(SQUEEZED), SQUEEZED[:70])
check("A2 the tabs are drawn SVG icons at every width (never a text label)",
      len(TABS) == 4
      and all("<svg" in t and 'stroke-width="1.8"' in t for t in TABS)
      and ".topTabs .ttab svg { display: block; width: 17px; height: 17px; }" in UI
      and "data-ic" not in UI)
check("A3 every tab still carries its accessible name AND a hover title",
      all('aria-label="' in t and 'title="' in t for t in TABS))
check("A4 the sandbox becomes its dot, the words stay in the a11y tree",
      "#topbar #sbxTxt { position: absolute;" in SQUEEZED
      and "#topbar #sbxPill { padding: 3px 7px; }" in SQUEEZED
      and 'id="sbxPill" title="sandbox backend"' in UI)
check("A5 the approval mode becomes its ✓ glyph",
      "#topbar #apprPill { font-size: 0; padding: 3px 7px; }" in SQUEEZED
      and '#topbar #apprPill::before { content: "\\2713"; font-size: 12px; line-height: 1; }' in SQUEEZED)
check("A6 the approval chip still SAYS its mode on hover and to screen readers",
      'el.title = "tool approval mode: " + mode +' in UI
      and 'el.setAttribute("aria-label", "approvals: " + mode +' in UI)

# ---- B: the redundant session badge leaves ------------------------------------
check("B1 the badge is hidden below 1101 px (chat head owns the name)",
      "@media (max-width: 1100px) {" in UI
      and "#sessBadge { display: none !important; }" in
      UI[UI.rfind("@media (max-width: 1100px) {"):UI.rfind("@media (max-width: 1100px) {") + 120])
check("B2 My Artifacts and Marketplace never show it (they own their row)",
      "body.artifacts-on #sessBadge, body.market-on #sessBadge { display: none !important; }" in UI)
check("B3 the badge is still in the DOM for the desktop sessions view",
      'id="sessBadge"' in UI and "function updateSessBadge" in UI)

# ---- C: 320 px still fits, with the gear inside the padding -------------------
# 2026-11-22 ROUND 173: the 360 tier narrows the SAME boxes as the 480 one (30 -> 28 px),
# so the header keeps one anatomy and one baseline instead of mixing six sizes.
check("C1 the narrowest phone narrows the tab targets",
      "gap: 3px; padding: 8px 6px;" in NARROW
      and "#topbar #topTabs .ttab { width: 30px; }" in NARROW
      and "#topbar #sbxPill, #topbar #apprPill { width: 28px; height: 28px; min-height: 28px; }" in NARROW)

# ---- D: no object was dropped from the bar -----------------------------------
check("D1 the sandbox state, approval mode, search and settings all remain",
      'id="sbxPill"' in TOPBAR and 'id="apprPill"' in TOPBAR
      and 'id="palette-open"' in TOPBAR and 'id="settingsBtn"' in TOPBAR)
check("D2 the squeezed rules only hide WORDS, never a control",
      "#topbar #sbxTxt { position: absolute;" in SQUEEZED
      and "#topbar #apprPill { font-size: 0;" in SQUEEZED
      and "#sbxPill { display: none" not in UI
      and "#apprPill { display: none" not in UI)
check("D3 the squeezed rules are declared after the topbar base rules (cascade)",
      UI.find("#topbar { gap: 10px; }") < UI.find("@media (max-width: 980px) and (min-height: 501px)"))

print("---")
passed = sum(results)
print("v1028: %d/%d PASS" % (passed, len(results)))
raise SystemExit(0 if passed == len(results) else 1)
