#!/usr/bin/env python3
"""v1249 — the composer context popover IS the inspector's Context card.

Operator (2026-11-21): *"clicking on compact in msg box doesn't open the wanted menu
with more context details … similar to the RH panel. Don't duplicate code backend."*

The composer ring used to open a stub of its own (four `cp-row`s and a full-width
`cp-compact` button) with its own class vocabulary. It now renders the SAME card the
inspector's Context section draws — percentage + meter + state, then
messages / tokens / budget, then the two text actions — from the SAME `/api/context`
read (`_ctxDisplay`) and the SAME two doors: `compactNow()` (the ONLY compaction call)
and `openSettings("compaction")`. One anatomy, one vocabulary, no second endpoint.

  A  the popover renders the inspector's card anatomy
  B  the stub vocabulary is gone (no cp-head / cp-row / cp-compact-only CSS)
  C  the two actions are the ONE doors (compactNow + the compaction settings)
  D  the data is `_ctxDisplay` (the same /api/context read the panel uses)
  E  no new backend call was introduced (one /api/context/compact in the file)
  F  the ring is still the trigger, and the popover still closes on an outside click

Deterministic and offline: static pins on webui/index.html.
Run: python3 tests/acceptance/v1249_ctx_popover_mirrors_panel.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
# 2026-11-22: the builder takes the clicked ring (`anchor`), so the marker must include the
# parameter — splitting on the bare `_ctxPopover()` raised IndexError and the script died
# before printing a single check. Re-pointed to the real signature.
_POP = HTML.split("function _ctxPopover(anchor)")[1].split("\ndocument.addEventListener")[0]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# --- A: the inspector's anatomy ---------------------------------------------
# 2026-11-22: the card markup moved into ONE builder (`_ctxCardHTML`) that the popover
# and the `/context` window both render, so the anatomy is asserted there and the
# popover must be using it — the intent (one card, one vocabulary) is unchanged.
_CARD = HTML.split("function _ctxCardHTML(d)")[1].split("function _ctxPopover(")[0]
for cls in ("ctxhead", "ctxpct", "meter", "ctxstate", "ctxrow", "ctxacts"):
    check("A the shared card renders .%s (the panel's anatomy)" % cls, cls in _CARD)
check("A6 the popover renders that builder, not its own copy",
      "pop.innerHTML = _ctxCardHTML(d);" in _POP)
check("A7 the two actions are `.lnk` text actions, like the panel's",
      _CARD.count('class="cp-') == 2 and _CARD.count(" lnk\"") == 2)
check("A8 the card is built once (inspector's static copy + the shared builder)",
      HTML.count('class="ctxhead"') == 2, HTML.count('class="ctxhead"'))

# --- B: no second vocabulary -------------------------------------------------
check("B1 the old stub CSS is gone",
      ".cp-head" not in HTML and ".cp-row" not in HTML
      and ".ctxpop .cp-compact {" not in HTML)
check("B2 the popover only styles the shared card (spacing, not a new look)",
      ".ctxpop {" in HTML and ".ctxpop .ctxhead {" in HTML
      and ".ctxpop .ctxacts {" in HTML)

# --- C: the ONE doors --------------------------------------------------------
check("C1 compact reuses `compactNow()` (the single compaction call)",
      'pop.querySelector(".cp-compact").onclick = () => { _closeCtxPop(); compactNow(); }' in HTML)
check("C2 settings opens the SHARED compaction policy",
      'openSettings("compaction")' in _POP)
check("C3 the panel's compact link routes to the same door (`compactNow`)",
      # 2026-11-27: the panel link used `$("compactBtn").onclick = compactNow;`, a bespoke
      # wiring that handed the CLICK EVENT to `compactNow(sid)` — `_commandTarget` then saw a
      # MouseEvent where it wanted a session id and refused ("the active session changed").
      # It now rides the ONE delegated dispatcher (`data-call`) every other control uses.
      'data-call="compactNow"' in HTML.split('id="compactBtn"')[1][:40]
      and '$("compactBtn").onclick' not in HTML)

# --- D/E: one data source, no new endpoint -----------------------------------
check("D1 the popover reads `_ctxDisplay` (the /api/context display, same as the panel)",
      "const d = _ctxDisplay || {};" in _POP
      and "_ctxDisplay = d;" in HTML)
check("D2 every field it shows is one the panel already shows",
      all(f in HTML.split("const { d = c.display")[1][:400] if False else f in HTML
          for f in ("d.pct", "d.tokens", "d.budget", "d.messages", "d.state")))
check("E1 exactly ONE /api/context/compact CALL SITE in the whole WebUI",
      HTML.count('api("POST", "/api/context/compact"') == 1,
      HTML.count('api("POST", "/api/context/compact"'))
check("E2 the popover adds no fetch of its own",
      "fetch(" not in _POP and "api(" not in _POP)

# --- F: the trigger and the dismissal ---------------------------------------
check("F1 the composer ring is still the trigger",
      # 2026-11-22 (ROUND 172): the click is a DELEGATED listener on `#cmpCtx` now, so a
      # re-rendered composer can never leave the ring without a handler. Same ONE trigger,
      # re-pointed from `_cc.onclick`.
      '$("cmpCtx")' in HTML and 'e.target.closest && e.target.closest("#cmpCtx")' in HTML
      and "_ctxPopover(onRing)" in HTML)
check("F2 an outside click still closes it",
      "_ctxPopEl && !_ctxPopEl.contains(e.target)" in HTML)
check("F3 the popover is a labelled dialog and stays on screen",
      # 2026-11-22 (ROUND 176): the on-screen clamp is now computed in LAYOUT px (the
      # ring's visual rect divided by the app zoom `_uiZoom`), so the old
      # `window.innerWidth - pop.offsetWidth - 8` literal is gone. Re-pointed to the
      # zoom-aware clamp; the dialog labelling is unchanged.
      'setAttribute("role", "dialog")' in _POP
      and 'setAttribute("aria-label", "context details")' in _POP
      and "window.innerWidth / z" in _POP and "vw - pw - 8" in _POP)

print("\n---\nv1249: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
