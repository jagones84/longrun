#!/usr/bin/env python3
"""v1027 — the Marketplace explains itself: four collapsible macro-areas, a source
badge on every card, and the age of each synced catalogue.

This is a static pin on the rendered contract (the live render is verified through
Chrome DevTools); it guards the parts a refactor silently drops:

  A  the page groups by KIND, in a fixed order, with a real disclosure button
  B  the collapsed state is remembered; each card carries its catalogue badge
  C  the sync row says how old the copy is, and when it went stale
  D  Settings ▸ Skills has a marketplace bucket and Settings ▸ MCP/Connectors
     show the same badge
  E  the module still parses (node --check)
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
CSS = UI
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ── A: macro-areas ─────────────────────────────────────────────────────────
check("A1 the four kinds are ordered plugin → skill → mcp → connector",
      'const KIND_ORDER = ["plugin", "skill", "mcp", "connector"]' in JS)
check("A2 a section is a heading with a real disclosure button",
      'class="mkt-sect-h"' in JS and "mkt-sect-btn" in JS
      and 'aria-expanded="${open ? "true" : "false"}"' in JS and "aria-controls=" in JS)
check("A3 the section lists the kinds it renders (all, or the active tab)",
      'const kinds = state.kind === "all" ? KIND_ORDER : [state.kind];' in JS)
check("A4 the body is hidden, not removed, when the section is collapsed",
      'mkt-sec-body' in JS and '${open ? "" : " hidden"}' in JS)
check("A5 the section header counts its items and names their sources",
      "mkt-sect-n" in JS and "sourceBreakdown(rows)" in JS
      and "rows.forEach(i => { const k = i.origin_label" in JS)
check("A6 a card shown in Recommended is not silently missing from its section's count",
      "in Recommended" in JS and 'featured.filter(i => i.kind === kind)' in JS)
check("A7 Recommended is a collapsible section built by the same helper",
      'sectionHtml("recommended", "Recommended"' in JS and "function sectionHtml(" in JS)

# ── B: collapse memory + provenance badge ─────────────────────────────────
check("B1 the collapsed set is remembered in localStorage",
      'const COLLAPSE_KEY = "lrmkt.collapsed"' in JS and "persistCollapsed(set)" in JS)
check("B2 a click on the header toggles it without a network read",
      'closest(".mkt-sect-btn")' in JS and "persistCollapsed(set);" in JS
      and "render();" in JS.split('closest(".mkt-sect-btn")')[1][:400])
check("B3 every card carries its catalogue badge",
      "function originBadge(" in JS and 'class="mkt-origin"' in JS
      and "originBadge(item.origin, item.origin_label" in JS)
check("B4 Manage rows carry the badge and the install date",
      "originBadge(rec.origin, rec.origin_label" in JS and '"installed " + String(rec.installed)' in JS)
check("B5 the badge's tooltip names the raw origin, never a paraphrase",
      'title = "catalogue: " + (origin || "unknown")' in JS)

# ── C: freshness ──────────────────────────────────────────────────────────
check("C1 the sync row has a place for the age",
      'id="mktSyncAge"' in UI and 'el("mktSyncAge")' in JS)
check("C2 the age is a relative string with a stale warning",
      "function ageText(" in JS and '"d ago"' in JS and "stale, sync to refresh" in JS)
check("C3 the source list is read from the catalogue route",
      '"/api/market/sources"' in JS)

# ── D: Settings panels ────────────────────────────────────────────────────
check("D1 the page states what a connector IS, next to the tabs",
      'id="mktLegend"' in UI and "Connector = MCP that needs a key" in UI)
check("D2 Settings ▸ Skills has a marketplace bucket, fed by the record",
      'section("market", "From the marketplace"' in UI and "matches.filter(s => s.market)" in UI)
check("D3 those skills leave the folders' buckets (no double listing)",
      "s.auto && !s.matrix && !s.market" in UI and "s.local && !s.market" in UI
      and "!s.auto && !s.local && !s.matrix && !s.market" in UI)
check("D4 the skill row shows the catalogue label as its badge",
      "sk-market" in UI and "s.market.origin_label" in UI)
check("D5 Settings ▸ MCP shows the badge on an installed server",
      "c.market.origin_label" in UI and "sk-market" in UI)
check("D6 Settings ▸ Connectors shows which catalogue a connector came from",
      "c.origin_label" in UI)
check("D7 removing a marketplace skill removes its RECORD, not just the files",
      '"/api/market/installed/" + encodeURIComponent(s.market.id) + "?files=1"' in UI)
check("D8 the styles exist for the disclosure and the badge",
      ".mkt-sect-btn {" in CSS and ".mkt-origin {" in CSS and ".mkt-sec-body[hidden]" in CSS)

# ── E: the module parses ──────────────────────────────────────────────────
try:
    node = subprocess.run(["node", "--check", os.path.join(REPO, "webui", "assets", "market.js")],
                          capture_output=True, text=True, timeout=30)
    ok = node.returncode == 0
    detail = (node.stderr or "").strip()[:200]
except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
    ok, detail = False, str(e)
check("E1 market.js parses as a module", ok, detail)

print("\n---\nv1027: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
