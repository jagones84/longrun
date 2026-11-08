#!/usr/bin/env python3
"""v867 — the message box keeps its width; the rail owns the controls (operator, 2026-11-07).

Operator, verbatim: "i tre tarttini e di quel menu nel MESSAGE BOX CHAT sotto la chat di
sessione devono non stare li, devono i o meglio i tre puntin imettili nella sidebar. il
menu queue steer fallo a icona cosi occupa meno spasizio poi cliccando sopra esce menu
queque e steer ovviamente. lo spazio orizzontale seve, i tre puntin devono stare in basso
nella sidebar, il autogenerate portalo sempre nella sidebar appena sopra. se vuoi
organizar e la sidebar in sezioni fai pure. il gear di settings mettilo in ALTO nella GUI."

Contract:
  A) the composer row holds ONLY the message box controls: no ⋯ menu and no native
     <select> — the queue/steer mode is ONE icon button with a two-item popup, backed by
     the single stored value `sf_qmode` every send path already reads;
  B) the rail (the "sidebar") owns the ⋯ and its menu at the FOOT, with the ✨ mounted
     directly above it, and its tools are two named sections;
  C) the settings gear is back in the TOPBAR, once;
  D) both popovers render outside their 44px/34px owner (the generic `aside` clips) and
     stay opaque, so no white flash and no clipped menu.

Deterministic: static contract on webui/index.html. No server, no model, no network.
Run: python3 tests/acceptance/v867_rail_sections_and_modes.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def slice_between(head, tail):
    at = UI.find(head)
    if at < 0:
        return ""
    end = UI.find(tail, at)
    return UI[at:end if end > 0 else len(UI)]


COMPOSER = slice_between('<div id="composerBar">', '<div id="tabbar">')
RAIL = slice_between('<aside id="toolsBar"', '<aside id="rail"')
TOPBAR = slice_between("<header id=\"topbar\">", "</header>")

# ---------------- A: the composer row belongs to the message box ----------------
check("A1 the composer has no ⋯ menu and no native queue/steer <select>",
      'id="moreBtn"' not in COMPOSER and 'id="moreMenu"' not in COMPOSER
      and 'id="qmode"' not in COMPOSER, "")
check("A2 the queue/steer mode is ONE icon button with a two-item popup",
      'id="qmodeBtn"' in COMPOSER and 'aria-haspopup="menu"' in COMPOSER
      and 'id="qmodeMenu"' in COMPOSER and COMPOSER.count('data-qmode=') == 2
      and 'data-qmode="queue"' in COMPOSER and 'data-qmode="steer"' in COMPOSER, "")
check("A3 the popup writes the ONE stored value the send paths read",
      'localStorage.getItem("sf_qmode") || "queue"' in UI
      and 'localStorage.setItem("sf_qmode", it.dataset.qmode)' in UI
      and '_isCmd && (localStorage.getItem("sf_qmode") || "queue") === "steer"' in UI, "")
check("A4 the mode is a STATE glyph: one icon per mode, the hidden one takes no space",
      'id="qmodeIcoQueue"' in COMPOSER and 'id="qmodeIcoSteer"' in COMPOSER
      and "#composerBar .qmode-wrap svg[hidden] { display: none; }" in UI, "")
check("A5 the button's accessible name follows the mode (never a colour-only signal)",
      'b.setAttribute("aria-label", "delivery mode: " + m +' in UI
      and 'el.setAttribute("aria-checked", String(el.dataset.qmode === m)' in UI, "")

# ---------------- B: the rail owns the ⋯, the ✨ sits above it ----------------
check("B1 the ⋯ and its menu live in the rail",
      'id="moreBtn"' in RAIL and 'id="moreMenu"' in RAIL
      and 'data-call="compactNow"' in RAIL and 'data-call="newSession"' in RAIL, "")
check("B2 the ⋯ is the rail's LAST control (the foot), not a mid-cluster tool",
      RAIL.index('class="tb-foot"') < RAIL.index('id="moreBtn"')
      and RAIL.index('id="moreBtn"') < RAIL.index("</aside>"), "")
check("B3 the ✨ acts on the draft: it rides the chat group (v890)",
      '"chat.prompt", "#inp", "#toolsBar #chatViewSec", null,' in UI, "")
check("B4 the rail's tools are FOUR SECTIONS with one hairline between",
      RAIL.count('class="tb-sec"') == 4
      and "#toolsBar .tb-sec + .tb-sec { margin-top: 8px; padding-top: 10px;" in UI, "")
check("B5 the foot stays at the rail's BOTTOM even with no session cluster",
      "#toolsBar .tb-foot {" in UI and "margin-top: auto;" in UI, "")

# ---------------- C: the gear is at the TOP of the GUI ----------------
check("C1 settings lives in the topbar",
      'id="settingsBtn" title="settings" aria-label="settings"' in TOPBAR, "")
check("C2 settings exists ONCE and is NOT in the rail any more",
      UI.count('id="settingsBtn"') == 1 and 'id="settingsBtn"' not in RAIL, "")
check("C3 the topbar action keeps the ONE 32px box",
      "#settingsBtn, #palette-open { width: 32px; height: 32px; padding: 0; border-radius: 8px;" in UI, "")

# ---------------- D: both popovers open outside their owner, opaque ----------------
check("D1 the rail does not clip its own popover (the generic `aside` does)",
      "#toolsBar {" in UI and "overflow: visible;" in UI, "")
check("D2 ⋯ opens to the LEFT of the rail; queue/steer opens UP in the composer",
      "#moreMenu { right: calc(100% + 10px); bottom: 0; }" in UI
      and "#qmodeMenu { left: 0; bottom: calc(100% + 8px); min-width: 132px; }" in UI, "")
check("D3 both popups are opaque (no see-through, no white flash)",
      "#moreMenu, #qmodeMenu { position: absolute; min-width: 178px; padding: 4px; z-index: 60;"
      in UI and "#slashMenu, #qmodeMenu { background: var(--menubg); }" in UI
      and "#plusMenu, #moreMenu, #qmodeMenu, #modelMenu, .smodal" in UI, "")

print("\nv867: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
