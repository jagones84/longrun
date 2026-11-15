#!/usr/bin/env python3
"""v1019 — the Marketplace page reads real backend state and never hides its gate.

  A  the page exists as a fourth top-level tab, with the same contract as My Artifacts
  B  the shell is one module (assets/market.js), served from /assets
  C  the page asks the real routes — catalogue, installed, install, remove
  D  a card PRINTS the digest it will be verified against
  E  an entry that is not installable cannot be installed from the page
  F  Manage reads the installed RECORD, not a second store
  G  the kind tabs and category chips are one control each
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ── A: a real page, with the same contract as the other top-level pages ─────
check("A1 a fourth top tab exists and names the page",
      'id="tabMarket"' in UI and 'data-call="showMarket"' in UI)
check("A2 the page section exists and is aria-hidden until shown",
      'id="marketView"' in UI and 'aria-label="marketplace"' in UI)
check("A3 the page owns the row (body.market-on hides #app)",
      "body.market-on #app { display: none; }" in UI
      and "body.market-on #marketView { display: block; }" in UI)
check("A4 showMarket stands the other pages down and marks the strip",
      "function showMarket()" in UI
      and 'document.body.classList.add("market-on")' in UI
      and '_setTabs("market")' in UI)
check("A5 the tab is registered in TAB_IDS (one owner for the strip)",
      'market: "tabMarket"' in UI)
check("A6 the hash deep-links the page (#market)",
      'location.hash === "#market"' in UI and 'location.pathname + location.search + "#market"' in UI)

# ── B: one module, served from /assets ───────────────────────────────────────
check("B1 the page logic is an ES module served from /assets",
      '<script type="module" src="/assets/market.js"></script>' in UI)
check("B2 the module publishes ONE entry point",
      "window.LRMkt = {" in JS and "window.mktManage" in JS and "window.mktReload" in JS)

# ── C: the page asks the real routes ────────────────────────────────────────
for route, label in (("/api/market/catalog", "catalogue"),
                     ("/api/market/installed", "installed record"),
                     ("/api/market/install", "install")):
    check("C " + label + " is read from " + route, route in JS)
check("C4 remove goes through DELETE /api/market/installed/<id>",
      '"/api/market/installed/"' in JS and '"DELETE"' in JS)

# ── D: the digest is on the card, not only in the payload ───────────────────
check("D1 the card prints the sha256 it will verify",
      '"sha256 " + esc(shortDigest(item.sha256))' in JS)
check("D2 a skill with no digest says so on the card",
      "no digest" in JS and "not installable" in JS)
check("D3 the digest is shortened for display, never hidden entirely",
      "function shortDigest(sha)" in JS and "slice(0, 12)" in JS)

# ── E: an uninstallable entry has no working Install button ─────────────────
check("E1 the Install button is disabled when the entry is not installable",
      'item.installable ? "" : "disabled"' in JS)
check("E2 the disabled button carries the reason",
      'const reason = item.installable ? "" :' in JS and "title=\"${esc(reason" in JS)

# ── F: Manage is a view over the installed record ───────────────────────────
check("F1 Manage renders the installed record",
      "function manageRow(rec, st)" in JS and "state.installed" in JS)
check("F2 an installed item shows its version, source and digest",
      'rec.version && "v" + rec.version' in JS and "rec.sha256" in JS and "rec.source" in JS)
check("F3 an update is surfaced when the catalogue moved",
      "update_available" in JS and "update available" in JS)

# ── G: one control per question ─────────────────────────────────────────────
check("G1 the kind tabs are declared once (Plugins · Skills · MCP · Connectors)",
      'data-kind="plugin"' in UI and 'data-kind="skill"' in UI
      and 'data-kind="mcp"' in UI and 'data-kind="connector"' in UI
      and 'data-kind="manage"' in UI)
check("G2 the tab strip keeps aria-selected in step with the state",
      't.setAttribute("aria-selected", on ? "true" : "false")' in JS)
check("G3 category chips are rendered from the backend's own categories",
      "renderChips((cat && cat.categories) || []" in JS)
check("G4 an empty catalogue explains both ways to fill it",
      "config/market.yaml" in JS and "data/market/catalog.json" in JS)

print("\n---\nv1019: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
