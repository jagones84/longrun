#!/usr/bin/env python3
"""v1254 — the tab is just "Longrun", and the composer's context ring is a real button that
opens a compact context card with `compact`.

Operator (2026-11-22): (1) *"perché si chiama longrun dgx harness? non si può chiamare solo
longrun? chi ha scelto quel nome della pagina web?"*; (2) *"se clicco sul cerchio del contesto
in msg box si deve aprire un menu coi dettagli contesto e con la possibilità di compattare,
simile al RH panel context menu ma più succinto; adesso invece se clicco non succede nulla"*.

  A  the document title is exactly "Longrun"
  B  the ring is a BUTTON with a 24x24 hit area around the same 13px ring
  C  the click is delegated + the popover toggle survives a stale node
  D  the popover is the ONE context card (the /context window's builder), with compact+settings
  E  the numbers are the ones the meter already carries (messages / tokens / budget)

Deterministic and offline: static pins on webui/index.html.
Run: python3 tests/acceptance/v1254_title_and_context_ring.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def block(start, end):
    return HTML.split(start)[1].split(end)[0] if start in HTML else ""


# ---- A: the title ---------------------------------------------------------
check("A1 the tab reads exactly Longrun",
      "<title>Longrun</title>" in HTML and "DGX Harness" not in HTML)

# ---- B: the ring is a control --------------------------------------------
_RING = block(".cmp-ctx {", ".cmp-ctx[hidden]")
check("B1 it is a real button with the context name and a dialog popup",
      '<button type="button" class="cmp-ctx" id="cmpCtx" aria-label="context details"'
      in HTML and 'aria-haspopup="dialog"' in HTML)
check("B2 the hit area is 24x24 around the same 13px ring",
      "width: 24px; height: 24px" in _RING and ".cmp-ctx .mring { width: 13px; height: 13px; }" in HTML,
      _RING[:200])
check("B3 it looks clickable (pointer, hover, focus ring) — not cursor:help",
      "cursor: pointer" in _RING and ".cmp-ctx:hover { background: var(--hover); }" in HTML
      and ".cmp-ctx:focus-visible { outline: 2px solid var(--accent);" in HTML
      and "cursor: help" not in _RING)

# ---- C: the click path ----------------------------------------------------
check("C1 the click is DELEGATED to the document, not bound to one node",
      'e.target.closest && e.target.closest("#cmpCtx")' in HTML
      and "e.preventDefault();\n  _ctxPopover();" in HTML
      and "_cc.onclick = _ctxPopover" not in HTML)
check("C2 a stale popover node cannot swallow the next click",
      "if (_ctxPopEl && !document.body.contains(_ctxPopEl)) _ctxPopEl = null;" in HTML)
check("C3 the same click still closes it (toggle)",
      "if (_ctxPopEl) { _closeCtxPop(); return; }" in HTML)

# ---- D: the compact card --------------------------------------------------
check("D1 the popover IS the shared context card (one builder)",
      "pop.innerHTML = _ctxCardHTML(d);" in HTML
      and "function _ctxCardHTML(" in HTML)
check("D2 compact and settings reuse the existing doors",
      'pop.querySelector(".cp-compact").onclick = () => { _closeCtxPop(); compactNow(); };' in HTML
      and 'pop.querySelector(".cp-settings").onclick = () => { _closeCtxPop(); openSettings("compaction"); };' in HTML)
check("D3 it is an accessible dialog with a name",
      'pop.setAttribute("role", "dialog");' in HTML
      and 'pop.setAttribute("aria-label", "context details");' in HTML)

# ---- E: the numbers -------------------------------------------------------
check("E1 the card carries messages / tokens / budget",
      "d.messages" in HTML and "d.tokens" in HTML and "d.budget" in HTML)

print("\n---\nv1254: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
