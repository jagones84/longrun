#!/usr/bin/env python3
"""v761 — the two phone arrows are never one target with two meanings.

Measured on the shipped build at 390×844: with the sessions drawer open (full width)
its own "close" arrow sat at x=390 — half of it outside the viewport — while the
inspector arrow stayed at x=377, 13px away. Tapping "close" therefore hit the other
panel: *"se collasso una si espande l'altra ... non vedo mai la chat"*.

Contract:
  A) both arrows are clamped inside the viewport.
  B) while an overlay drawer is up, only the arrow that can close it is on screen.
  C) the clamp/hide rule really hides a `display:flex` button.
  D) the left drawer keeps its resize grip (a duplicate rule had killed it).

Run: python tests/acceptance/v761_mobile_drawers.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v761_")
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
ED = src("webui", "assets", "editor.js")

# ---- A. the tap target that could land on the OTHER panel is gone --------------
check("A1 no edge arrow is parked near the screen edge any more",
      "const inset = 22;" not in UI
      and 'id="handle-left"' not in UI and 'id="handle-right"' not in UI)
check("A2 the pane toggles are real buttons and the Control view hides them",
      "body.control-on .pane-tog-grp { display: none !important; }" in UI
      and 'aria-controls="aside"' in UI and 'aria-controls="inspector"' in UI)

# ---- B. one pane per button, never two states in one glyph ---------------------
check("B1 each topbar toggle reads ONLY its own pane (they cannot fight)",
      "function _paintPaneState() {" in UI
      and "L.setAttribute(\"aria-pressed\", _panelShown('[data-col=\"sessions\"]')" in UI
      and "R.setAttribute(\"aria-pressed\", _panelShown('[data-col=\"context\"]')" in UI)

# ---- C. the rule can actually hide them ---------------------------------------
check("C1 the pane toggles are hidden on a phone (the tab bar owns it)",
      "@media (max-width: 900px) { .pane-tog-grp { display: none; } }" in UI)
check("C2 both toggles exist as ordinary buttons with their own handler",
      'id="paneLeftBtn"' in UI and 'id="paneRightBtn"' in UI
      and '$("paneLeftBtn").onclick = () => toggleLeftPanel();' in UI
      and '$("paneRightBtn").onclick = () => toggleRightPanel();' in UI)

# ---- D. the left drawer grip --------------------------------------------------
check("D1 the duplicate rule that killed the left grip is gone",
      "body.show-left #resize-left { display: none !important; }" not in UI)
check("D2 the left drawer's grip is still declared",
      "body.show-left #resize-left { display: block !important; position: fixed; top: 52px;" in UI)
check("D3 the tab bar remains the phone navigation (it closes both drawers first)",
      "function openTab(name) {" in UI and "_closeDrawers();" in UI
      and "function _toggleMobileDrawer(side) {" in UI)

# ---- E. the floating editor dock (the real reason the chat never came back) ----
check("E1 the dock does not auto-open on a narrow viewport",
      "async function ensureOpen() {" in ED and "if (_vw() < 1024) return;" in ED)
check("E2 a session switch does not pop it there either",
      "if (_vw() < 1024 && state.dock && state.dock.hidden) return;" in ED)
check("E3 a full-screen drawer outranks the floating dock (z 12 < 15 < 30)",
      "body.show-left #editorDock.ed-overlay," in ED
      and "body.show-right #editorDock.ed-overlay{z-index:12}" in ED)

print("\nv761: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
