#!/usr/bin/env python3
"""v758 — ONE rail grammar: same head, movable + collapsed-by-default views.

Operator, verbatim: *"no mi piace ancora RH panel non è il massimo, apri tutti i
menu vedi che roba vanno collassati … la barra sessions in alto è troppo grande e
non è simile a inspector, scegli una grafica e ripetila ovunque … i menu dell'RH
panel devono essere spostabili (come le sessioni), tutto collassabile"*.

Contract:
  A) both rails share ONE head metric (`--rail-hd`) and ONE row metric
     (`--rail-row`), and the sessions toolbar stops being a second big band;
  B) every inspector section starts COLLAPSED except Plan, and the collapsed row
     still carries its status summary;
  C) the stored "everything open" state is migrated ONCE, so the new default
     actually reaches the operator;
  D) inspector views are draggable to reorder on the shared DragSort engine and
     the order persists;
  E) the pins the old tests rely on survive (head/toolbar markup, ▲▼ controls).

Deterministic: source contracts only. No browser, no server, no model.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: one head, one row ----------------------------------------------------
check("A1 the two rail heads are declared together and share one height token",
      ":root { --rail-hd: 36px; --rail-row: 29px;" in UI
      and "aside .rail-head, #inspector .insp-tools {" in UI
      and "height: var(--rail-hd)" in UI)
check("A2 both heads use the same label typography (11px, spaced, uppercase)",
      "aside .rail-head h2, #inspector .insp-tools h2 {" in UI
      and "letter-spacing: .09em" in UI and "text-transform: uppercase" in UI)
check("A3 the sessions toolbar is a compact strip, not a second band",
      "aside .rail-tools { gap: 4px; padding: 4px 12px 8px;" in UI
      and "aside .rail-tools .rail-btn { width: 24px; height: 24px;" in UI)
check("A4 every inspector row uses the shared row height",
      "#inspector .insp-hd {" in UI and "height: var(--rail-row)" in UI
      and "flex-wrap: nowrap; overflow: hidden;" in UI)

# ---- B: collapsed by default -------------------------------------------------
sections = re.findall(r'<section data-insp="([a-z]+)"( class="insp-open")?>', UI)
open_default = [name for name, cls in sections if cls]
bodies = re.findall(r'<section data-insp="([a-z]+)"[^>]*>\s*<button[^>]*>.*?</button>\s*<div class="insp-body"([^>]*)>',
                    UI, flags=re.DOTALL)
check("B1 exactly ONE section is open by default and it is Plan",
      open_default == ["plan"], (open_default, len(sections)))
check("B2 every other section body starts hidden (no first-paint wall)",
      len(bodies) >= 8 and all(("hidden" in attrs) == (name != "plan") for name, attrs in bodies),
      [(n, a.strip()) for n, a in bodies])
check("B3 the collapsed row still carries its status summary",
      UI.count('class="ihd-s"') >= 8)

# ---- C: the migration that makes the default reachable ----------------------
check("C1 a versioned one-time migration drops the old per-section keys",
      'localStorage.getItem("sf_insp_v") !== "2"' in UI
      and 'k.indexOf("sf_insp_") === 0' in UI
      and 'localStorage.setItem("sf_insp_v", "2")' in UI)
check("C2 per-section state is still remembered after the migration",
      'localStorage.setItem("sf_insp_" + name, body.hidden ? "0" : "1")' in UI)

# ---- D: movable views -------------------------------------------------------
check("D1 a grip is injected into every inspector section (hover-only)",
      'g.className = "insp-grip"' in UI and "#inspector .insp-grip {" in UI
      and "section:hover .insp-grip" in UI)
check("D2 the drag runs on the SAME engine as the session list",
      "DragSort.bind(sec.querySelector(\".insp-grip\")" in UI
      and 'itemSel: "#inspector > section[data-insp]", idKey: "insp"' in UI)
check("D3 the order is persisted and re-applied on load",
      'const INSP_ORDER_KEY = "sf_insp_order";' in UI
      and "DragSort.moveItem(_inspSections().map(s => s.dataset.insp)" in UI
      and "_initInspectorChrome();" in UI)

# ---- E: contracts the older tests pin --------------------------------------
check("E1 the rail markup keeps its named blocks",
      '<section class="rail">' in UI and 'class="rail-head"' in UI
      and 'class="rail-tools" role="toolbar"' in UI and 'class="card rail-list"' in UI
      and '<h2>Sessions<span class="srail-tools">' in UI)
check("E2 the inspector bulk controls survive",
      'id="inspCollapseAll"' in UI and 'id="inspExpandAll"' in UI
      and '$("inspCollapseAll").onclick = () => _setAllInspector(false);' in UI)
check("E3 the pinned flex declaration of .insp-hd is untouched",
      "#inspector .insp-hd { display: flex; align-items: center; flex-wrap: wrap;" in UI)

print("\n---\nv758: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
