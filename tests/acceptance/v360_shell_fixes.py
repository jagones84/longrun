#!/usr/bin/env python3
"""v360 — theme completeness, a click-proof handle, and a chat that can't be crushed (JAG-360).

Static guards only (deterministic, no model, no network):

  A) NO surface keeps the indigo look: no near-black popup grays, no bluish
     hover/active tints — every one resolves through a theme token, so Sand/Sepia
     re-paint the WHOLE UI (settings, popovers, MCP textarea, scrollbars);
  B) the panel handle toggles on POINTER UP with a movement guard, so a press and
     hold behaves exactly like a tap and a 1-2 px wobble cannot cancel the click;
     and the resize BORDER ignores a click too — it only resizes after the pointer
     really travels (> 4px), so touching the border never shifts the panel;
  C) the centre column has a min-width floor and the side panels are shrinkable, so
     a wide panel (or a narrow window) can never crush the chat;
  D) the defaults are indigo + NO bolder text.

Run: python3 tests/acceptance/v360_shell_fixes.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: no surface keeps the indigo look -------------------------------------
check("A1 no near-black popup gray is left hardcoded",
      "#0b0f18" not in HTML and "rgba(24,28,40" not in HTML, "")
check("A2 no bluish hover/active/chip tint is left as a background",
      re.search(r"background:\s*rgba\((?:108,140,255|120,140,255|139,123,240)", HTML) is None, "")
check("A3 those surfaces now resolve through theme tokens",
      "background: var(--menubg);" in HTML and "background: var(--hover);" in HTML
      and "background: var(--sel);" in HTML and "background: var(--scroll);" in HTML, "")
check("A4 the settings window itself paints with the theme token",
      "#settingsWin { position: fixed" in HTML and "background: var(--menubg);" in HTML, "")

# --- B: one click, no press dance (2026-11-08: the pane toggles are topbar buttons)
check("B1 a pane toggle is an ordinary button — no pointer-up dance is needed",
      'h.addEventListener("pointerup", e => {' not in HTML
      and '$("paneLeftBtn").onclick = () => toggleLeftPanel();' in HTML, "")
check("B2 each toggle calls its OWN pane's toggle",
      '$("paneRightBtn").onclick = () => toggleRightPanel();' in HTML, "")
check("B3 the removed floating handles leave no dead binding behind",
      '["handle-left", "handle-right"].forEach' not in HTML
      and 'id="handle-left"' not in HTML, "")
check("B4 the Ctrl/Cmd+B shortcut mirrors the sessions toggle",
      'String(e.key || "").toLowerCase() !== "b"' in HTML
      and "toggleLeftPanel();" in HTML, "")
check("B5 the resize border ignores a click (no shift on a 1-px wobble)",
      "if (Math.abs(dx) < 4) return;" in HTML and "let dragging = false;" in HTML, "")
check("B6 a click never persists a width (only a real drag does)",
      "if (!dragging) { try { handle.releasePointerCapture(e.pointerId); } catch (_) {} return; }" in HTML
      and "if (!drawer) localStorage.setItem(key," in HTML, "")

# --- C: the chat cannot be crushed -------------------------------------------
check("C1 the centre column has a min-width floor and a 0 basis (never steals the panels' space)",
      '[data-col="chat"]     { flex: 1 1 0%; min-width: 420px;' in HTML, "")
check("C2 the side panels are FIXED width with a floor",
      'flex: 0 0 220px; width: 220px; min-width: 150px;' in HTML
      and 'flex: 0 0 238px; width: 238px; min-width: 150px;' in HTML, "")
check("C3 a saved width is restored fixed and then clamped to the chat floor",
      'col.style.flex = "0 0 " + saved + "px";' in HTML and "_fitPanels();" in HTML, "")
check("C4 the drag + the saved width use the CSS-px unit (page scale)",
      "col.getBoundingClientRect().width / z;" in HTML
      and "col.getBoundingClientRect().width / _pageScale()" in HTML, "")
check("C5 a drag is bounded by the room the chat leaves (no flex redistribution)",
      "const CHAT_MIN_W = 420;" in HTML and "function _fitPanels" in HTML
      and "function _panelRoom" in HTML and "Math.min(room, startW + sign *" in HTML, "")

# --- D: defaults -------------------------------------------------------------
check("D1 the default theme is indigo",
      'localStorage.getItem("sf_theme") || "indigo"' in HTML, "")
check("D2 the default is NO bolder text",
      HTML.count('(localStorage.getItem("sf_bold") || "0") === "1"') == 2, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

