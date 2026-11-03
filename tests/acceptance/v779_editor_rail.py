#!/usr/bin/env python3
"""v779 — the editor toggle lives in the rail and wears the rail's anatomy.

Source (operator, 2026-11-03): "open editor button shall be in the sidebar (icon). look
also at the frontend-ui-skill: make icon same style of the others".

What was wrong: the dock — the panel that opens RIGHT NEXT TO the chat — was reachable
from the composer's `⋯` overflow and from Settings ▸ Workspace, i.e. two clicks away
from the surface it opens beside, and it was the only `⋯` row that opens a panel
instead of acting on the session. The rail (`#toolsBar`) is where a session-scoped tool
belongs, and its buttons already share one anatomy.

Contract:
  A) the toggle is inside `#toolsBar .tb-mid` (the session-scoped cluster) and the
     `⋯` menu no longer carries a second copy — one control, one place;
  B) the icon is the SAME anatomy as its siblings: 17px, `viewBox 0 0 24 24`,
     `fill:none`, `stroke:currentColor`, `stroke-width:1.8`, round caps and joins;
  C) it is named (title + aria-label) and the glyph is `aria-hidden`;
  D) it is icon-only — no label text, no colour emoji (a rail is an instrument).

Deterministic: static contract on webui/index.html. No server, no model, no net.
Run: python3 tests/acceptance/v779_editor_rail.py
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()


def block(marker, end="</button>"):
    """The markup element that carries `marker`, opening tag included."""
    at = ui.find(marker)
    if at < 0:
        return ""
    start = ui.rfind("<button", 0, at)
    stop = ui.find(end, at)
    return ui[start:stop + len(end)] if start >= 0 and stop >= 0 else ""


RAIL = ui[ui.find('<aside id="toolsBar"'):ui.find("</aside>", ui.find('<aside id="toolsBar"'))]
MID = RAIL[RAIL.find('class="tb-mid"'):RAIL.find('class="tb-foot"')]
DOCK = block('id="dockBtn"')
SIBLING = block('id="kbSessionBtn"')

# ---------------- A: one control, in the rail, in the session cluster ----------------
check("A1 the editor toggle lives inside the rail's session cluster",
      'id="dockBtn"' in MID)
check("A2 the ⋯ menu no longer duplicates it (one control, one place)",
      'id="dockBtn"' not in ui[ui.find('id="moreMenu"'):ui.find("</div>", ui.find('id="moreMenu"'))])
check("A3 exactly one dock toggle exists in the shell",
      ui.count('id="dockBtn"') == 1)
check("A4 the same handler still opens the dock",
      'data-call="SparkEditorToggle"' in DOCK and "function SparkEditorToggle" in ui)

# ---------------- B: the icon wears the sibling anatomy ----------------
def icon_attrs(markup):
    m = re.search(r"<svg[^>]*>", markup)
    if not m:
        return {}
    return dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', m.group(0)))


dock_svg = icon_attrs(DOCK)
sib_svg = icon_attrs(SIBLING)
check("B1 both rail icons are 17px with the same viewBox",
      dock_svg.get("width") == "17" and dock_svg.get("height") == "17"
      and dock_svg.get("viewBox") == sib_svg.get("viewBox") == "0 0 24 24",
      {k: dock_svg.get(k) for k in ("width", "height", "viewBox")})
check("B2 the stroke recipe is the rail's, not a new one",
      all(dock_svg.get(k) == sib_svg.get(k) for k in
          ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin")),
      {k: dock_svg.get(k) for k in ("fill", "stroke", "stroke-width")})
check("B3 it is a ghost button like its neighbours",
      'class="ghost"' in DOCK)

# ---------------- C: it is named ----------------
check("C1 title + aria-label, and the glyph is decorative",
      'aria-label="open the editor"' in DOCK and "title=" in DOCK
      and dock_svg.get("aria-hidden") == "true")

# ---------------- D: icon-only, no emoji, no word ----------------
check("D1 the button carries no text label",
      re.search(r"</svg>[^<]+\S", DOCK) is None, DOCK[-60:])
check("D2 no colour emoji in the rail markup",
      not re.search("[\U0001F000-\U0001FAFF\u2705\u274c\u26d4]", RAIL))

print("---")
ok = sum(results)
print("\nv779: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
