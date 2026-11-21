#!/usr/bin/env python3
"""v1259 — a tighter Sessions rail (the agent id asked for, not printed) and ONE themed
popup for every native <select>.

Operator (2026-11-22, round 175): *"riduci di poco la spaziatura tra agenti sessione in LH
panel ed l'id agente nascondilo, rendilo visibile al passaggio mouse sopra"*; *"ci sono
menu in mobile mode che si aprono senza tema grafico, sono bianche. Esempio jobs assign to
nel pannellone agents jobs etcetera: controllali tutti gli spawning menus, devono essere in
linea col tema generale impostato da settings"*.

  A  the rail row is 4px-padded and the A-id chip appears only on hover / focus
  B  every <select> popup is the app's own themed listbox (both documents, one module)

Deterministic and offline: static pins on webui/index.html, webui/assets/filtersort.js,
webui/assets/filtersort.css and src/longrun/orbit/web/orbit.html.
Run: python3 tests/acceptance/v1259_rail_density_and_themed_select.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
FS = src("webui", "assets", "filtersort.js")
CSS = src("webui", "assets", "filtersort.css")
DECK = src("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def rule(selector, text):
    i = text.find(selector + " {")
    return text[i:text.find("}", i)] if i >= 0 else ""


# ---- A: the Sessions rail ---------------------------------------------------
SESS = rule(".sess", UI)
check("A1 the row is 4px-padded with a 1px gap (was 6 / 2)",
      "padding: 4px 8px;" in SESS and "margin-bottom: 1px;" in SESS, SESS[:160])
check("A2 the agent id is NOT printed on every row",
      "display: none;" in rule(".sess .jid", UI))
check("A3 it appears on hover and when the row holds the focus",
      ".sess:hover .jid, .sess:focus-within .jid { display: inline-block; }" in UI)
check("A4 the row tooltip still carries the id (a hidden chip hides nothing)",
      '(ag && _anum ? ("agent A" + _anum) : "")' in UI)
check("A5 the organigram door survives in the row menu",
      '<button data-a="org">' in UI)

# ---- B: one themed <select> popup ------------------------------------------
check("B1 the shared module exports the picker and installs it on pointerdown",
      "window.ThemedSelect = {open: _tsOpen, close: _tsClose};" in FS
      and 'document.addEventListener("pointerdown", function (e) {' in FS
      and 'e.target.closest("select")' in FS)
check("B2 a dialog carries the listbox, options carry the selection state",
      'pop.setAttribute("role", "dialog");' in FS
      and 'role="listbox"' in FS
      and 'role="option"' in FS
      and 'aria-selected' in FS
      and 'aria-expanded' in FS)
check("B3 picking writes the REAL select and fires its change (one contract)",
      "sel.selectedIndex = i;" in FS
      and 'sel.dispatchEvent(new Event("change", {bubbles: true}));' in FS)
check("B4 the surface wears the page theme tokens, never a hard-coded white",
      "background: var(--menubg, var(--panel2, #171b23));" in CSS
      and "border: 1px solid var(--line-2, var(--line, #2d323b));" in CSS
      and "#fff" not in rule(".ts-pop", CSS) and "white" not in rule(".ts-pop", CSS).lower())
check("B5 a phone gets a bottom sheet, not a dropdown off a zoomed control",
      ".ts-pop.sheet {" in CSS and "bottom: 8px;" in CSS)
check("B6 the keyboard works without a mouse (open, walk, pick, cancel)",
      'e.key === "ArrowDown"' in FS and 'e.key === "Escape"' in FS
      and 'e.key === "Enter" || e.key === " "' in FS)
check("B7 ONE implementation for both pages (the deck loads the same file)",
      '/assets/filtersort.js' in UI and '/assets/filtersort.js' in DECK
      and FS.count("function _tsOpen(") == 1)

print("\n---\nv1259: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
