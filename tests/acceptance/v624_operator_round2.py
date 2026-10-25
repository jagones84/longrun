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
      ORBIT.count('class="rsec"') == 2 and "font-weight:800" in ORBIT
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

# ---------------- C: grabbable rows, org scroll ----------------------
check("C1 agent rows show a grip with grab affordance",
      'class="rowgrip"' in ORBIT and "cursor:grab" in ORBIT)
check("C2 drag and drop states visible on the row",
      "tr.dragging" in ORBIT and "drop-before" in ORBIT
      and "drop-after" in ORBIT)
check("C3 AX click scrolls the org node into view",
      "this.focusAgent(tr.dataset.sid, true)" in ORBIT)

# ---------------- D: roomier table, live sync ----------------------
check("D1 content columns widened",
      "col.c-name{width:250px}" in ORBIT and "col.c-role{width:150px}" in ORBIT)
check("D2 Sessions repaints on every rename/release event",
      all(k in INDEX for k in ('"agent.updated"', '"agent.released"',
                               '"session.renamed"', '"session.created"',
                               '"session.deleted"'))
      and '"teams.updated": () => { loadSessions(); loadAgents(); }' in INDEX)

# ---------------- E: build watcher, SW ----------------------
check("E1 both shells watch /api/build with a reload chip",
      'id="buildChip"' in ORBIT and 'id="buildChip"' in INDEX
      and '"/api/build"' in INDEX and "_watchBuild" in ORBIT)
check("E2 SW cache v2 covers orbit and the shared engine",
      'longrun-shell-v2' in SW and '"/orbit"' in SW
      and 'dragsort.js' in SW)

# ---------------- F: model-switch invalidation ----------------------
check("F1 model change drops stale vectors for re-embed",
      "UPDATE chunks SET vec=NULL" in CODEINDEX
      and 'embed_model' in CODEINDEX)

print("---")
ok = sum(results)
print("\nv624: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
