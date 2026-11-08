#!/usr/bin/env python3
"""v881 — the Control deck's panels: one head anatomy, honest widths, one toggle.

Operator, 2026-11-08: *"control sheet page is horrible see the image. refactor with
correct movement of objects in the frontend, buttons, make more elegant and ordered
and no-space-wasting."*

What the screenshot showed: every column forced to ~280px (`flex:1 1 0`), so the org
chart was illegible, the jobs text wrapped on every word and the last panel was cut
at the window edge; six controls (a text "reset layout" + ▲ ▼ + ◀ ▶ ✕) crammed in a
12px head that also wrapped.

Pinned here:
  A) each job is ONE control (the ▲/▼ group pair is one fold toggle);
  B) one head anatomy — 34px, title never wraps, 24px icon actions on the right;
  C) column widths follow the CONTENT (agents widest) and wrap instead of clipping;
  D) the per-column move/remove cluster is a quiet icon group revealed on hover;
  E) motion is opt-out.

Deterministic: reads src/longrun/orbit/web/orbit.html, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
            encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one toggle for the agent groups -----------------------------------
check("A1 the ▲/▼ pair is gone", "agCollapseAll" not in HTML and "agExpandAll" not in HTML)
check("A2 one fold control drives the groups",
      'id="agToggleAll"' in HTML and "toggleAll(){" in HTML)
check("A3 its glyph follows the real state",
      "this._paintToggle();" in HTML
      and 'b.classList.toggle("is-open", !anyClosed && this._groupIds.length > 0);' in HTML)
check("A4 the click reads the groups, not a remembered flag",
      "if (this._groupIds.some(id => this.closed.has(id))) this.expandAll();" in HTML)

# ---- B: one head anatomy ---------------------------------------------------
check("B1 the head is a fixed-height, single-line row",
      ".panel > h2{min-height:34px;padding:6px 8px 6px 12px;white-space:nowrap;overflow:hidden}"
      in HTML)
check("B2 its actions are 24px icons with a name",
      '.panel > h2 .btn.ictl{padding:0;width:24px;justify-content:center}' in HTML
      and 'aria-label="reset panel sizes"' in HTML)
check("B3 no text button is left in the head",
      'id="rzReset" title="reset panel sizes">reset layout<' not in HTML)

# ---- C: widths follow the content -----------------------------------------
check("C1 the old equal-width rule is gone",
      "section.panel[data-panel]{flex:1 1 0;min-width:280px" not in HTML)
check("C2 the agents table gets the most room",
      'section.panel[data-panel="agents"]{flex:1.7 1 420px}' in HTML)
check("C3 the graphs have a real floor",
      'section.panel[data-panel="org"]{flex:1 1 330px}' in HTML
      and 'section.panel[data-panel="const"]{flex:1.1 1 350px}' in HTML)
check("C4 a panel grows/shrinks and wraps instead of being clipped",
      "section.panel[data-panel]{flex:1 1 320px;min-width:280px;max-width:100%;" in HTML
      and "flex-wrap:wrap" in HTML)

# ---- D: the view cluster is quiet, and keyboard reachable -----------------
check("D1 the move/remove cluster is a 22px icon group",
      ".vcols button{width:22px;height:22px;" in HTML)
check("D2 it is quiet until the panel is hovered/focused",
      ".panel:hover > h2 .vcols,.vcols:focus-within{opacity:1}" in HTML)
check("D3 it remains focus-visible",
      ".vcols button:focus-visible{outline:2px solid var(--acc)" in HTML)

# ---- E: motion is opt-out --------------------------------------------------
check("E1 reduced motion keeps the glyphs still",
      "@media (prefers-reduced-motion: reduce){.fold-tg svg{transition:none}}" in HTML
      and "@media (prefers-reduced-motion: reduce){.vcols{transition:none}}" in HTML)

# ---- F: the toolbar loses its clutter (operator, same day) -----------------
check("F1 the ✨ is ONE frameless glyph, not a sentence",
      'class="btn gen-only" id="lraAutoBtn"' in HTML
      and ">✨</button>" in HTML
      and "automate (Teamorg)</button>" not in HTML)
check("F2 it is still named for a screen reader",
      'aria-label="automate team, agent and job setup with Architect"' in HTML)
check("F3 the ROLE.md scope choice lives in the automation bar it belongs to",
      HTML.index('id="lraAutoPrompts"') > HTML.index('id="lraAutoBar"'))
_policy = HTML[HTML.index("async applyModelPolicy(){"):]
_policy = _policy[:_policy.index("\n  /* v622:")]
check("F4 model policy is the SERVER policy, not a second rule in the browser",
      '"/api/teams/" + encodeURIComponent(tid) + "/models"' in _policy
      and 'this.api.post("/api/agents"' not in _policy
      and "/api/orbit/models" not in _policy
      and "cloud[0]" not in _policy)
check("F5 it reports the refs the server used and the agents that really changed",
      "r.lead_model" in _policy and "r.member_model" in _policy
      and "changed.length" in _policy)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
