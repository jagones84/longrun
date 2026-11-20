#!/usr/bin/env python3
"""v1237 — the brand ⋮ menu beside LONGRUN, and the changelog button + endpoint.

Operator, 2026-11-21:
  *"a button to restart longrun. … a three-dot menu just beside right to the LONGRUN
  title … other high level suggestions … shall not be already other buttons in the
  webui"*
  *"a changelog button (visible mobile and desktop mode pay attention) to see
  changelogs (display latest commit?)"*

Deterministic: reads webui/index.html + src/longrun/core/httpapi.py, no browser.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
HTTPAPI = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
API_V02 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


# ---- A: the brand ⋮ menu beside the wordmark -------------------------------
check("A1 a ⋮ menu button sits immediately right of the LONGRUN wordmark",
      'id="brandMenuBtn"' in UI
      and UI.index('id="brandMenuBtn"') > UI.index('LONGRUN</h1>')
      and UI.index('id="brandMenuBtn"') < UI.index('id="topTabs"'))
check("A2 it is ONE popover, anchored to the button (body-level, never clipped)",
      'id="brandMenu" class="card"' in UI
      and "#brandMenu { position: fixed;" in UI
      and "function _placeBrandMenu(" in UI
      and "toggleBrandMenu" in UI)
check("A3 restart is the menu's own act and reuses the supervised-restart route",
      'data-call="restartLongrun"' in UI
      and "async function restartLongrun()" in UI
      and 'api("POST", "/api/home/restart", {})' in UI
      and "/api/home/restart" in API_V02)   # the route itself lives server-side
check("A4 the menu carries only NEW high-level acts (no duplicate of the gear/search)",
      all(k in UI for k in ('data-call="reloadInterface"', 'data-call="copyDiagnostics"',
                            'data-call="openAbout"'))
      and "function reloadInterface(" in UI
      and "function copyDiagnostics(" in UI
      and "function openAbout(" in UI)
# 2026-11-21 (operator: "dont use frames for icon please use correct icons for last changes")
_BRAND = UI[UI.find('id="brandMenu"'):UI.find("</div>", UI.find('id="brandMenu"'))]
check("A5 every brand row wears an SVG icon, never an emoji or a text glyph",
      _BRAND.count("<svg") == 4
      and not any(g in _BRAND for g in ("\u21bb", "\u27f3", "\u29c9", "\u24d8")))
check("A6 the brand ⋮ and the changelog button are FRAMELESS glyphs (no ghost border)",
      UI.count("border: 0; background: transparent; box-shadow: none;") >= 2
      and "#changelogBtn:hover { background: var(--hover); color: var(--txt); }" in UI)

# ---- B: the changelog button + modal + endpoint ----------------------------
check("B1 a dedicated changelog button exists in the topbar action cluster",
      'id="changelogBtn"' in UI and 'data-call="openChangelog"' in UI
      and 'aria-label="changelog"' in UI)
check("B2 it is visible on desktop AND on a phone (sized in every layout)",
      "#changelogBtn { width: 32px; height: 32px;" in UI                        # desktop box
      and "#topbar #palette-open, #topbar #buildChip, #topbar #changelogBtn {" in UI  # 44px rail
      and "#topbar #palette-open, #topbar #settingsBtn, #topbar #changelogBtn {" in UI)  # phone
_CHLOG = UI[UI.find('id="changelogBtn"'):UI.find("</button>", UI.find('id="changelogBtn"'))]
check("B2b the changelog uses a HISTORY glyph (clock), not the generic document/page (2026-11-21)",
      # Operator: "the changelog icon is horrible — find a new way to represent it". It was
      # the artifact/document page+lines; it is now a history clock (circle + hands),
      # distinct from the gear, search, ⋮ and refresh.
      '<circle cx="12" cy="12" r="8.3"/>' in _CHLOG
      and "M6 3.5h8l4 4V20" not in _CHLOG)
check("B3 the modal shows release notes AND the latest commit",
      "async function openChangelog(" in UI
      and "d.head" in UI and "d.releases" in UI and "d.commits" in UI
      and "latest: " in UI)
check("B4 one shared read-only modal builder, no second modal anatomy",
      "function _infoModal(" in UI and "function _kvRows(" in UI
      and UI.count("function _infoModal(") == 1)
check("B5 the endpoint is wired and parses CHANGELOG.md + git log",
      'if path == "/api/changelog":' in HTTPAPI
      and "def changelog_payload(" in HTTPAPI
      and "def _parse_changelog(" in HTTPAPI
      and "def _git_log(" in HTTPAPI)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
