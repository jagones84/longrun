#!/usr/bin/env python3
"""v624 — operator round 2: grabbable rows, AX->org scroll, roomier table,
live sync everywhere, headed views rail, 6-wide views with resize,
model-switch vector invalidation, build watcher, SW v2.

  A  rail: PANELS + VIEWS are bold headed subpanels (.rsec boxes).
  B  views hold up to 6; columns resizable via .rz-vcol (persist + reset).
  C  agent rows show a grip, grab cursors, drag/drop states; AX click
     scrolls the org node into view.
  D  wider table columns; Sessions feed repaints on every rename/release.
  E  both shells watch /api/build with a reload chip; SW cache v2 covers
     /orbit + dragsort.
  F  codebase index drops stale vectors on embedding-model change.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v624_operator_round2.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")
INDEX = _read("webui", "index.html")
SW = _read("webui", "sw.js")
CODEINDEX = _read("src", "longrun", "memory", "codeindex.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: headed rail ----------------------
check("A1 PANELS and VIEWS are bold headed subpanels",
      # 2026-10-31: the label weight moved 800 -> 700 with the type system; it is
      # still the bold head of a boxed subpanel.
      ORBIT.count('class="rsec"') == 2 and "font-weight:700" in ORBIT
      and "#deckRail .rsec" in ORBIT)
check("A2 no unboxed rail buttons outside the subpanels",
      "data-view-add" in ORBIT and "up to 6 panels side by side" in ORBIT)

# ---------------- B: 6-wide resizable views ----------------------
check("B1 views hold up to 6 panels",
      "at most 6 panels side by side" in ORBIT and ".slice(0, 6)" in ORBIT
      and "at most 3 panels" not in ORBIT and ".slice(0, 3)" not in ORBIT)
check("B2 view columns resizable with persistence and reset",
      ".rz-vcol" in ORBIT and "_layoutViewCols" in ORBIT
      # v626: widths persist as per-row RATIOS (vrat:) — px keys are gone
      and '"vrat:" + this.view + ":" + r + ":" + c' in ORBIT
      and "this._layoutViewCols();" in ORBIT
      and "min-width:280px" in ORBIT)
check("B3 the default Desk keeps the operator-approved proportions (no agents bias)",
      # 2026-11-09 (operator, screenshot): Agents 25 - Jobs 15 - Org chart 36 -
      # Constellation 24 is the official default Desk shape. The old "agents >= 40%"
      # bias is gone, the inherited ratios are dropped once (orbit_desk_def_v1) and
      # the fallback lives in _deskDefault; the operator's own drags still save.
      "rowPanels.length > 2 ? 0.4 : 0.58" not in ORBIT
      and "ratios[ai] < target" not in ORBIT
      and "_deskDefault" in ORBIT
      and "[0.25, 0.15, 0.36, 0.24]" in ORBIT
      and 'orbit_desk_def_v1' in ORBIT
      and 'vrat:view:v-desk:' in ORBIT)

# ---------------- C: grabbable rows, org scroll ----------------------
check("C1 agent rows show a grip with grab affordance",
      'class="rowgrip"' in ORBIT and "cursor:grab" in ORBIT)
check("C2 drag and drop states visible on the row",
      "tr.dragging" in ORBIT and "drop-before" in ORBIT
      and "drop-after" in ORBIT)
check("C3 AX click scrolls the org node into view",
      "this.focusAgent(tr.dataset.sid, true)" in ORBIT)

# ---------------- D: roomier table, live sync ----------------------
check("D1 compact table cells, actions are icons (4 columns since v895)",
      "col.c-id{width:58px}" in ORBIT and "col.c-model{width:18%" in ORBIT
      and "col.c-act{width:26px}" in ORBIT
      and "table.at{width:100%;table-layout:fixed" in ORBIT
      and "\\u270E edit prompt (ROLE.md)" in ORBIT
      and "\u270e prompt" not in ORBIT and "\u21ba reset" not in ORBIT)
check("D2 Sessions repaints on every rename/release event",
      all(k in INDEX for k in ('"agent.updated"', '"agent.released"',
                               '"session.renamed"', '"session.created"',
                               '"session.deleted"'))
      and '"teams.updated": () => { loadSessions(); loadAgents(); }' in INDEX)

# ---------------- E: build watcher, SW ----------------------
check("E1 both shells watch /api/build with a reload chip",
      'id="buildChip"' in ORBIT and 'id="buildChip"' in INDEX
      and '"/api/build"' in INDEX and "_watchBuild" in ORBIT)
# 2026-11-01: the cache name is a VERSION, not a constant. It moved v2 -> v3 after
# the phone PWA rendered a months-old offline shell: `install` runs once per worker
# body, so an unchanged name keeps the "/" copy captured at install time forever.
# Pin the SHAPE (a `longrun-shell-vN` name + the shell list), not one literal, so a
# deliberate bump does not need a test edit but a silent drop still fails.
check("E2 SW cache is versioned and covers orbit and the shared engine",
      ('const CACHE = "longrun-shell-v' in SW) and '"/orbit"' in SW
      and 'dragsort.js' in SW and 'cache: "reload"' in SW)

# ---------------- F: model-switch invalidation ----------------------
check("F1 model change drops stale vectors for re-embed",
      "UPDATE chunks SET vec=NULL" in CODEINDEX
      and 'embed_model' in CODEINDEX)

print("---")
ok = sum(results)
print("\nv624: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
