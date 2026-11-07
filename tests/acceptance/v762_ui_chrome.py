#!/usr/bin/env python3
"""v762 — the chrome: a jump control that clears the composer, standard topbar icons,
and a Settings window that opens centred.

Measured before the fix (390x844): the "jump to latest" button sat at y 714..748 INSIDE
the composer (y 655..761), on top of send (287..321) — the operator's screenshot. The
topbar carried two text glyphs ("⚙" renders as a colour emoji on Android, "⌘K" is a
keyboard hint) plus a session badge clipped to 24px, so only its 🗂 emoji survived.
And `buildSettingsWin()` returned early once the nav existed, so its positioning block
never ran and the window opened flush at 0,0 (measured: inline left/top 0px).

Contract:
  A) the jump control is placed from the conversation's own bottom edge.
  B) the two topbar actions are one 32px box with monochrome SVG; the phone keeps
     brand + sections + actions and drops the duplicated session badge.
  C) Settings has ONE geometry function: the saved spot, else the centre.

Run: python tests/acceptance/v762_ui_chrome.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v762_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

# ---- A. the jump control -------------------------------------------------------
check("A1 its bottom is measured from the log, not a constant",
      'b.style.bottom = Math.round((gap > 0 ? gap : 0) + 14) + "px";' in UI
      and "chat.getBoundingClientRect().bottom - l.getBoundingClientRect().bottom" in UI)
check("A2 the old 96px anchor is gone",
      "#jumpBtn { position: absolute; right: 22px; bottom: 96px;" not in UI)
check("A3 a phone gets a >=40px target",
      "@media (max-width: 900px) { #jumpBtn { width: 40px; height: 40px; right: 14px;" in UI)
check("A4 the placement runs with the other settled geometry",
      "updateJump();   // 2026-11-01: the jump control is measured" in UI)

# ---- B. the topbar ------------------------------------------------------------
check("B1 settings is a monochrome SVG button, not the ⚙ glyph",
      # 2026-11-07: the title span carries `id="settingsTitle"` — it is the accessible
      # name of the Settings dialog (`role="dialog" aria-labelledby`), not just a label.
      'id="settingsBtn" title="settings" aria-label="settings"' in UI
      and 'data-call="toggleSettings">⚙</button>' not in UI
      and '<span class="sw-title" id="settingsTitle">Settings</span>' in UI)
check("B2 the palette is an icon with the shortcut in the tooltip",
      'id="palette-open" title="search &amp; commands (Ctrl/⌘ K)"' in UI
      and ">⌘K<" not in UI)
check("B3 both actions share one 32px box",
      "#settingsBtn, #palette-open { width: 32px; height: 32px; padding: 0; border-radius: 8px;" in UI)
check("B4 a phone drops the clipped session badge (it duplicated the chat head)",
      "#sessBadge { display: none !important; }" in UI)

# ---- C. Settings geometry -----------------------------------------------------
check("C1 one function owns the geometry",
      "function _applySettingsGeom(w) {" in UI
      and UI.count("_applySettingsGeom(") == 3
      and "_applySettingsGeom(w);" in UI and "_applySettingsGeom(settingsWin());" in UI)
check("C2 with no saved spot it is centred, never flush at 0,0",
      "w.style.left = Math.max(16, Math.round((innerWidth - r.width) / 2)) + \"px\";" in UI)
check("C3 a dragged spot is respected",
      "if (pos && (Number(pos.x) || Number(pos.y))) {" in UI)
check("C4 the dead first-build-only positioning block is gone",
      '} else { w.style.left = Math.max(20, (innerWidth - 760) / 2) + "px"; w.style.top = "70px"; }' not in UI)
check("C5 the density pass is in (8/11 padding, 14px between categories)",
      "#settingsWin .sw-main .card {\n    background: var(--bg-2); border: 1px solid var(--line);\n    border-radius: 10px; padding: 8px 11px; }" in UI
      and "#settingsWin .sw-main .card + h2 { margin-top: 14px; }" in UI)

print("\nv762: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
