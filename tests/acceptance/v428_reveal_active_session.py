#!/usr/bin/env python3
"""v428 — WebUI "reveal the active session in the rail" (JAG-428).

The user, while talking in a chat, could collapse the active session's team group in
the left rail (or collapse the whole panel) with no quick way back: the rail offered
no control to re-expand the group AND center the row you are actually talking to.

Pinned here (static guards on webui/index.html):
  * a topbar 🎯 control exists and calls `revealActiveSession`, shown only with an open
    session;
  * `revealActiveSession` opens the panel, forces the active group(s) open (via the
    existing `_forceExpandActive` path), clears the search filter and centers the row;
  * `_centerActiveRow` scrolls the active row into view and flashes it;
  * clicking the collapsed-panel session badge does the same (same gesture).

Deterministic (no model, no network).

Run: python3 tests/acceptance/v428_reveal_active_session.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: the chat tools bar (JAG-429: moved next to the todo controls) --------
check("1a the reveal button exists", 'id="revealSessionBtn"' in HTML, "")
check("1b it is wired to revealActiveSession",
      'data-call="revealActiveSession"' in HTML, "")
# JAG-429/JAG-457: the control moved into #toolsBar (the vertical tools bar
# between the chat and the right inspector, also holding the todo controls).
tt = HTML[HTML.index('id="toolsBar"'):]
tt = tt[:tt.index("</aside>")]
check("1c it lives inside #toolsBar (the chat tools bar)",
      'id="revealSessionBtn"' in tt, "")
check("1f chat refresh lives in #toolsBar",
      'id="chatReloadBtn"' in tt, "")
check("1g chat refresh calls the transcript reload path",
      'id="chatReloadBtn"' in tt and '$("chatReloadBtn").onclick = () => reloadChat();' in HTML
      and "function reloadChat()" in HTML
      and "loadHistory(); loadPlan(); loadCtx();" in HTML, "")
check("1d #toolsBar starts hidden (shown only with an open session)",
      re.search(r'id="toolsBar"[^>]*hidden', HTML) is not None, "")
check("1e visibility is driven by _updateTreeTools()",
      "function _updateTreeTools(" in HTML
      and re.search(r't\.hidden\s*=\s*!sessionId', HTML) is not None, "")

# --- 2: the functions --------------------------------------------------------
check("2a revealActiveSession() is defined", "function revealActiveSession(" in HTML, "")
check("2b _centerActiveRow() is defined", "function _centerActiveRow(" in HTML, "")
check("2c _bindSessBadgeReveal() is defined and invoked",
      "function _bindSessBadgeReveal(" in HTML and "_bindSessBadgeReveal();" in HTML, "")

body = HTML[HTML.index("function revealActiveSession("):]
body = body[:body.index("\n/* JAG-358")] if "\n/* JAG-358" in body else body[:2500]

# --- 3: revealActiveSession opens the panel ---------------------------------
check("3a it opens the sessions panel when hidden",
      "_panelShown('[data-col=\"sessions\"]')" in body and '"show-left"' in body
      and '"collapsed-left"' in body, "")
check("3b it forces the active group(s) open (reuses _forceExpandActive)",
      "_forceExpandActive = true" in body, "")
check("3c it re-renders the rail", "loadSessions()" in body, "")
check("3d it clears a search filter that could hide the row",
      "session-search" in body, "")
check("3e it centers the row after render", "_centerActiveRow" in body, "")

# --- 4: _centerActiveRow actually centers + flashes -------------------------
cbody = HTML[HTML.index("function _centerActiveRow("):]
cbody = cbody[:cbody.index("\n}") + 2]
check("4a it targets the ACTIVE row", "#sessions .sess.active" in cbody, "")
check("4b it uses scrollIntoView with block:center",
      "scrollIntoView" in cbody and 'block: "center"' in cbody, "")
check("4c it flashes the row", "dotflash" in cbody, "")

# --- 5: the flash style exists ----------------------------------------------
check("5 a .sess.dotflash style is defined", ".sess.dotflash" in HTML, "")

# --- 6: the collapsed-panel badge is clickable to the same effect ------------
bbody = HTML[HTML.index("function _bindSessBadgeReveal("):]
bbody = bbody[:bbody.index("\n}") + 2]
check("6 clicking the session badge reveals the session",
      "sessBadge" in bbody and "revealActiveSession" in bbody, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
