#!/usr/bin/env python3
"""v359 — themed popups, graphic topbar indicators, and a zoom-proof shell (JAG-359).

Static guards only (deterministic, no model, no network):

  A) the theme reaches the settings window and every popup — they were pinned to
     the indigo dark surface (#0f1320 / #1e293b) and ignored the active theme;
  B) the topbar ctx/sandbox indicators are compact GRAPHICS (a ring + %, a status
     dot), not debug text, and the ctx one turns RED from 70% up;
  C) the shell fills the real viewport at any zoom (the CSS `zoom` on <html> used
     to scale the body's `100dvh` and leave a gap at the bottom).

Run: python3 tests/acceptance/v359_theme_shell.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: the theme reaches the settings window + every popup ------------------
check("A1 no popup is pinned to the indigo dark surface any more",
      "background: #0f1320;" not in HTML, "")
check("A2 the settings window paints with the theme token",
      "#settingsWin { position: fixed" in HTML and "background: var(--menubg);" in HTML, "")
check("A3 the harness/tools cards use tokens, not raw slate hexes",
      "#1e293b" not in HTML and "#0b1020" not in HTML, "")

# --- B: the topbar indicators are graphics -----------------------------------
check("B1 the ctx meter carries a ring svg + a % readout",
      'class="pill meter" id="ctx-meter"' in HTML and 'class="mring"' in HTML
      and 'id="ctxRing"' in HTML and 'id="ctxPct"' in HTML, "")
check("B2 the ctx JS drives the ring and the 70% red threshold",
      'pill.className = "pill meter" + (pct >= 70 ? " hot" : "")' in HTML
      and "ring.style.strokeDashoffset = String(100 - Math.max(0, Math.min(100, pct)))" in HTML, "")
check("B3 the ctx CSS turns the ring AND the % red when hot",
      ".pill.meter.hot .mfill { stroke: var(--err); }" in HTML
      and ".pill.meter.hot b { color: var(--err); }" in HTML, "")
check("B4 the ctx tooltip carries the full used/budget detail",
      # JAG-424g: the ring moved off the panel header onto the active session ROW, so the
      # detail now flows through the shared _ctxTitle (still "used / budget · %").
      "_ctxTitle = d.detail || d.short" in HTML, "")
check("B5 the sandbox pill is a status dot + one short word",
      'class="pill sbox" id="sbxPill"' in HTML and 'class="sdot" id="sbxDot"' in HTML
      and 'id="sbxTxt"' in HTML, "")
check("B6 the sandbox dot is green when isolated, amber otherwise",
      "#sbxPill.ok .sdot { background: var(--ok);" in HTML
      and "#sbxPill.warn .sdot { background: var(--warn);" in HTML, "")
check("B7 the backend detail moved to the sandbox tooltip",
      '"sandbox backend: " + sb.backend + " (requested: "' in HTML
      and 'sb.isolated ? " — sandboxed (isolated)" : " — host execution, no sandbox"' in HTML, "")

# --- C: the shell fills the viewport at any zoom -----------------------------
check("C1 the body height is divided by the live zoom",
      "height: calc(100dvh / var(--zoom, 1));" in HTML, "")
check("C2 applyZoom publishes the live zoom as --zoom",
      'document.documentElement.style.setProperty("--zoom", String(_zoom));' in HTML, "")
check("C3 a default --zoom exists (so the shell is right before applyZoom runs)",
      "--zoom: 1;" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

