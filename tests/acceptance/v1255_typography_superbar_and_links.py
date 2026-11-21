#!/usr/bin/env python3
"""v1255 — one transcript typography, the Workspace/Plan bar above the message box, the ✨
inside the message box, +A −D opens the diff, and an out-of-workspace read opens the preview.

Operator (2026-11-22, round 171): *"trae li ha [workspace e plan] come sovrabar intercambiabile
sopra la msg box … implementalo anche tu (non distruggere il RH panel), non duplicare codice"*;
*"l'autogenerate … dentro la msg box piccolo in alto a dx … rimuovilo dalla sidebar"*;
*"i diff del wrote/edit … se clicco su +48 −5 deve aprirsi il diff, non l'espansione"*;
*"il nomefile deve essere piccolino come la riga di harness … command executed è bold e font
diverso … perché il testo di risposta è BOLD di default? … il font size deve essere uguale e
uniforme, rimpicciolirei risposte e thought"*; *"i file out of workspace in read > nomefile non
li apre nell'editor — risolvi"*.

  A  ONE typography: answer and thought 12.5px/400; file name 11.5px italic; bold pref excluded
  B  the Workspace/Plan bar borrows the live inspector body (one implementation)
  C  the chat ✨ lives at the right end of that strip, not in the sidebar
  D  +A −D opens the diff window and never toggles the row
  E  the file NAME opens the editor for every tool — an out-of-workspace path included

Deterministic and offline: static pins on webui/index.html + webui/assets/editor.js.
Run: python3 tests/acceptance/v1255_typography_superbar_and_links.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
EDITOR = open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


# ---- A: one typography ----------------------------------------------------
check("A1 an answer and a thought are the SAME 12.5px/400 text",
      "font-size: 12.5px; font-weight: 400; line-height: 1.55;" in HTML
      and "details.think .t { color: var(--txt); font-size: 12.5px; font-weight: 400; line-height: 1.55;"
      in HTML)
check("A2 the file name is one step smaller than the row verb (11.5px, italic)",
      ".toolcard .tc-file { font-style: italic; font-size: 11.5px; }" in HTML)
check("A3 the row verb is the normal 12px/400 text in BOTH bold modes",
      ".toolcard .tc-name { font-weight: 400; color: var(--txt); font-size: 12px; }" in HTML
      and "html:not(.bold-text) .toolcard .tc-name," not in HTML)
check("A4 the bolder-text preference never reaches the transcript body",
      "html.bold-text body, html.bold-text .card" in HTML
      and "html.bold-text body, html.bold-text .bubble" not in HTML
      and "html.bold-text .bubble p" not in HTML)

# ---- B: the switchable bar ------------------------------------------------
check("B1 the bar sits ABOVE the message box with the two tabs",
      '<div id="cmpSuper">' in HTML and 'data-cs="files"' in HTML and 'data-cs="plan"' in HTML
      and HTML.index('id="cmpSuper"') < HTML.index('id="inpWrap"'))
check("B2 it BORROWS the live inspector body and returns it (no second panel)",
      "var _cs = { key: null, node: null, parent: null, next: null, wasHidden: false };" in HTML
      and '_cs.parent.insertBefore(_cs.node, _cs.next || null);' in HTML
      and '$("csBody").appendChild(node);' in HTML)
check("B3 the inspector keeps working (a lent body is returned by its header)",
      "if (!body) { _csReturn(); return; }" in HTML)
_CMSUPER = HTML[HTML.index('<div id="cmpSuper">'):HTML.index('<div id="inpWrap">')]
check("B4 the strip carries NO summary line and NO copied count (round 174)",
      'id="csSum"' not in _CMSUPER and 'class="cs-sum"' not in HTML
      and '["sPlan", "sWorkspace"].forEach' not in HTML)
check("B5 one control is pressed at a time and close is explicit",
      'b.setAttribute("aria-pressed", String(k === on));' in HTML and 'aria-selected' not in _CMSUPER
      and 'role="group" aria-label="session status"' in _CMSUPER
      and 'id="csClose"' in HTML)

# ---- C: the spark inside the box -----------------------------------------
check("C1 the chat.prompt spark mounts into the composer, not the sidebar",
      '["chat.prompt", "#inp", "#cmpSpark", null,' in HTML
      and '#toolsBar #chatViewSec", null,' not in HTML)
check("C2 it is the RIGHT END of the strip and the strip is the message box's top row (round 174)",
      '<span id="cmpSpark"></span>' in _CMSUPER
      and "#cmpSpark { margin-left: auto;" in HTML
      and HTML.index('id="cmpSpark"') < HTML.index('id="inpWrap"')
      and "#composer #inpWrap #inp { padding-right: 36px; }" not in HTML)

# ---- D: the stat opens the diff ------------------------------------------
check("D1 +A −D is wired to the SAME diff window and stops the row toggle",
      'const st = card.querySelector(".tc-stat");' in HTML
      and 'st.addEventListener("click", e => {' in HTML
      and 'e.preventDefault(); e.stopPropagation();' in HTML
      and '      showDiff(path);' in HTML)

# ---- E: the name opens the file ------------------------------------------
_WTN = HTML[HTML.index("function _wireToolName"):HTML.index("const _editStatSeen")]
check("E1 the name opens the FILE in the editor for EVERY tool (round 174)",
      'nm.title = "open " + p;' in _WTN
      and "openInEditor(path);" in _WTN
      and "openPreview(" not in _WTN
      and "⚠ outside the workspace" in EDITOR
      and _WTN.index("openInEditor(path);") < _WTN.index('const st = card.querySelector(".tc-stat")'))
check("E2 only +A −D opens the diff (the two readings have one gesture each)",
      "showDiff(path);" in _WTN
      and _WTN.index("showDiff(path);") > _WTN.index('const st = card.querySelector(".tc-stat")')
      and "function openPreview(path, row)" in HTML)

print("\n---\nv1255: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
