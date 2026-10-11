#!/usr/bin/env python3
"""v352 — Appearance: themes + compaction model in the chat menu + panel handles (JAG-352/353).

Static guards for the WebUI/Bridge work:
  A) five English themes with real CSS token blocks (no "Sabbia");
  B) an Appearance settings category renders a swatch grid and persists the choice;
  C) the theme is applied PRE-PAINT (no flash) in BOTH the main app and Bridge;
  D) a "bolder text" preference;
  E) the chat model menu carries the compaction-model control (POST /api/routing);
  F) panel collapse is a circular handle on the border (topbar icon buttons gone);
  G) the composer bar is token-driven (contrast on light themes);
  H) the deck is renamed Bridge.

Deterministic, no model/browser. Run: python3 tests/acceptance/v352_appearance_theme.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "orbit", "api.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: themes ---------------------------------------------------------------
check("A1 six themes defined (English names)",
      all(s in HTML for s in ('id: "indigo"', 'id: "dark"', 'id: "midnight"',
                              'id: "forest"', 'id: "sand"', 'id: "sepia"')), "")
check("A2 no Italian theme name remains",
      "Sabbia" not in HTML and "sabbia" not in HTML, "")
check("A3 a real token block per theme",
      all(s in HTML for s in ('html[data-theme="dark"]', 'html[data-theme="midnight"]',
                              'html[data-theme="forest"]', 'html[data-theme="sand"]',
                              'html[data-theme="sepia"]')), "")
check("A4 Sand is creamier (lower luminance than the old near-white)",
      "--bg: #c8bda2" in HTML and "#e7d9bd" not in HTML, "")
check("A5 Sand and Sepia are no longer identical",
      "--bg: #c8bda2" in HTML and "--bg: #17120c" in HTML, "")
check("A6 Sand is the ONLY light theme (Sepia is now dark)",
      HTML.count("color-scheme: light") == 1, str(HTML.count("color-scheme: light")))

# --- B: Appearance settings + persistence -----------------------------------
check("B1 an Appearance settings category exists",
      '["appearance", "Appearance"]' in HTML, "")
check("B2 swatch grid + applyTheme persist the choice",
      'id="themeGrid"' in HTML and "function applyTheme" in HTML
      and 'localStorage.setItem("sf_theme", id)' in HTML, "")
check("B3 settingsCategory wires the appearance panel",
      'else if (name === "appearance")' in HTML and "renderThemeGrid()" in HTML, "")

# --- C: pre-paint (no flash), main app + Bridge -----------------------------
check("C1 the main app applies the saved theme before paint",
      'localStorage.getItem("sf_theme") || "indigo"' in HTML and "dataset.theme = t" in HTML, "")
check("C2 Bridge applies the same saved theme before paint",
      'localStorage.getItem("sf_theme")' in ORBIT and "dataset.theme=_t" in ORBIT, "")

# --- D: bolder text ---------------------------------------------------------
check("D1 a bolder-text preference exists",
      'html.bold-text body' in HTML and 'id="boldText"' in HTML
      and "function applyBold" in HTML, "")
check("D2 bolder-text OFF is a real normal baseline (chrome labels not bold)",
      "html:not(.bold-text) .sess .t" in HTML
      and "html:not(.bold-text) button.primary" in HTML, "")
# JAG-389: the session row is compact — the NAME is on its OWN full-width line
# below the badges (never truncated) and the meta rides the badge line, pushed right.
check("D3 the session name sits on its own FULL-WIDTH line (no truncation)",
      ".sess .t { flex-basis: 100%" in HTML and ".sess .col" not in HTML, "")
check("D4 the meta (msgs · age) rides the badge line, pushed right",
      ".sess .n { margin-left: auto" in HTML, "")

# --- E: compaction model in the chat model menu -----------------------------
check("E1 the model menu renders the compaction bar",
      'className = "mm-bar"' in HTML, "")
check("E2 selecting a model in compact mode pins the summarizer",
      "function chooseCompactionModel" in HTML
      and 'roles: { summarizer: { model: ref } }' in HTML, "")
check("E3 the current compaction ref is loaded at boot",
      "function loadCompactionRef" in HTML and "loadSkills(); loadCompactionRef();" in HTML, "")

# --- F: panel handles replace the topbar buttons ----------------------------
check("F1 the topbar toggle buttons are gone",
      'id="toggle-left"' not in HTML and 'id="toggle-right"' not in HTML, "")
check("F2 circular edge handles exist",
      'id="handle-left"' in HTML and 'id="handle-right"' in HTML
      and ".edge-handle" in HTML, "")
check("F3 handles are positioned from the panel rect + flip their arrow",
      "function positionHandles" in HTML and 'L.textContent = lOpen ? "◀" : "▶"' in HTML
      and 'R.textContent = rOpen ? "▶" : "◀"' in HTML, "")
check("F5 the resize grip cannot steal the handle press",
      'h.onmousedown = e => { e.preventDefault(); e.stopPropagation(); }' in HTML, "")
check("F4 the toggle behaviour is preserved (collapsed/show + resize)",
      "function toggleLeftPanel" in HTML and "function toggleRightPanel" in HTML
      and "collapsed-left" in HTML and "collapsed-right" in HTML, "")

# --- G: composer contrast ---------------------------------------------------
check("G1 the composer background is token-driven",
      "--composer:" in HTML and "#composer { background: var(--composer); }" in HTML, "")
check("G2 Sand gives the composer a light background; dark themes stay dark",
      "--composer: rgba(206,197,173,.85)" in HTML and "--composer: rgba(23,18,12,.7)" in HTML, "")

# --- H: the deck is renamed Control (top-level tabs) ------------------------
check("H1 the WebUI has top-level Sessions + Control tabs",
      ">Sessions</a>" in HTML and ">Control</a>" in HTML and "location.href='/orbit'" in HTML, "")
check("H2 the Control page title + its active tab",
      "<title>Control · Longrun beta</title>" in ORBIT and ">Control</span>" in ORBIT
      and ">Sessions</a>" in ORBIT, "")
check("H3 the API fallback page says Control",
      "Control beta" in API, "")

# --- I: Bridge is themed too ------------------------------------------------
check("I1 Bridge carries the per-theme token override blocks",
      all(s in ORBIT for s in ('html[data-theme="sand"]', 'html[data-theme="midnight"]',
                               'html[data-theme="forest"]', 'html[data-theme="sepia"]')), "")
check("I2 Bridge re-points its hardcoded dark bits at tokens",
      ".cbody{background:var(--cbody)}" in ORBIT and ".cnode text{fill:var(--linktext)}" in ORBIT, "")

# --- J: minimal GUI copy + a real bolder-text (JAG-356) ---------------------
check("J1 the instructional paragraphs are gone from the panels/subwindows",
      "This panel is the persistent view of the plan" not in HTML
      and "Known servers, ready to use" not in HTML
      and "Each model is <code>id</code> or" not in HTML
      and "Stored in <code>localStorage</code> (key <code>sf_token</code>)" not in HTML
      and "the session will be bound to this folder" not in HTML, "")
check("J2 the Harness tab keeps its detailed explanations",
      "keeps long jobs alive without getting stuck forever" in HTML
      and "applies them only if it passes" in HTML, "")
check("J3 bolder text really bumps the whole app (body + chat + inputs)",
      "html.bold-text body, html.bold-text .bubble" in HTML
      and "html.bold-text input," in HTML and "font-weight: 600" in HTML, "")

# --- K: handles stay glued + the collapsed session name (JAG-357/358) --------
check("K1 the handles reposition while the panel is being resized",
      "positionHandles();   // JAG-357: keep the handle glued to the border we move" in HTML
      and "new ResizeObserver(() => positionHandles())" in HTML, "")
check("K2 a collapsed panel drops its resize grip",
      "body.collapsed-left #resize-left, body.collapsed-right #resize-right { display: none; }" in HTML, "")
check("K3 the active session name shows in the topbar whenever the panel is off screen",
      'id="sessBadge"' in HTML and "function updateSessBadge" in HTML
      and "!_panelShown('[data-col=\"sessions\"]')" in HTML, "")
check("K4 the handle position compensates the real page scale (engine-agnostic)",
      "function _pageScale" in HTML and "p.getBoundingClientRect().left / 100" in HTML
      and "L.style.left = (lx / s)" in HTML, "")
check("K5 a zoom change re-glues the handles",
      "_settleHandles();    // JAG-358: a zoom change rescales the page" in HTML, "")
check("K6 a panel parked off screen is not treated as shown",
      "r.right > 1 && r.left < _vw() - 1" in HTML, "")
check("K7 the toggle thresholds match the CSS overlays (900 / 1100)",
      '_overlayLeft() ? "show-left" : "collapsed-left"' in HTML
      and '_overlayRight() ? "show-right" : "collapsed-right"' in HTML
      and "return _vw() <= 900" in HTML
      and "return _vw() <= 1100" in HTML, "")

# --- L: the side panels are OPAQUE (JAG-391) --------------------------------
# `aside { background: var(--aside); }` paints BOTH the left sessions panel and the
# right inspector rail. A translucent --aside let the chat bleed through the panel
# (the user reported the right rail as "transparent"). Every theme must use a SOLID
# colour for the token — no alpha channel — so the panels read as real surfaces.
check("L1 the panel token is a solid colour (no alpha) in every theme",
      "--aside: rgba(" not in HTML and HTML.count("--aside: #") == 6,
      str(HTML.count("--aside: #")))
check("L2 both panels paint from that token",
      "aside { background: var(--aside); }" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

