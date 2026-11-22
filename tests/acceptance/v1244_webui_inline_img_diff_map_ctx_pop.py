#!/usr/bin/env python3
"""v1244 — three WebUI surfaces the operator asked for (2026-11-20).

  1. An image the agent SHOWS is previewed INLINE as a medium box (not only a path
     link). "se chiedo fammi vedere una foto X, me la fai vedere in chat oltre che
     darmi il iperlink path".
  2. The diff viewer LANDS on the first change and maps the changes on the
     scrollbar, so the operator knows where to scroll. "non mostra ... dove sono le
     modifiche così non so dove scrollare per trovarle".
  3. Clicking the composer context ring opens a MINIMAL popover (the numbers + the
     `compact` action). "se ci clicchi sopra devono uscire più dettagli minimali
     più il tasto ... compact".

Deterministic and offline: static pins on `webui/index.html` (the render surface).
Live rendering is verified separately (screenshot + getComputedStyle).
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
RULES = open(os.path.join(REPO, ".trae", "rules", "project_rules.md"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:200]) if detail and not ok else ""))


# ---- 1: inline image preview ------------------------------------------------
check("1a the inline-image box exists (css + builder)",
      ".chatimgs {" in HTML and ".chatimg img {" in HTML and "function _inlineImages(" in HTML)
check("1b it reads the images the reply referenced and opens the image window",
      "a.imglink" in HTML and "showImage(src)" in HTML and "_rawUrl(u)" in HTML)
check("1c it is wired into the render path (live + reload)",
      "linkifyNodes(b);\n  _inlineImages(b);" in HTML)
check("1d fail-safe: an unservable path does not render a broken box",
      "im.onerror = () => { cell.remove();" in HTML)

# ---- 2: diff viewer lands on + maps the changes ----------------------------
check("2a a change map is added to the diff modal",
      'id="diffWrap"' in HTML and 'id="diffMap"' in HTML and "#diffMap i.a {" in HTML)
check("2b the map is built from the add/del/change rows",
      "function _buildDiffMap()" in HTML and "r-(add|del|chg)" in HTML)
check("2c the close LANDS on the first change (scroll, not just render)",
      "const first = body.querySelector(\".diffrow.r-add, .diffrow.r-del, .diffrow.r-chg\")" in HTML)
check("2d the map is called from showDiff and reset on error",
      "_buildDiffMap();" in HTML and '$("diffMap").hidden = true;' in HTML)

# ---- 3: context-ring popover + compact -------------------------------------
check("3a a ctx popover surface exists and is styled like the other popovers",
      # 2026-11-22 (ROUND 172): the builder takes the ring that was clicked (`anchor`), so
      # its signature is `_ctxPopover(anchor)`. The surface (`.ctxpop`) and the shared-anatomy
      # styling (`.ctxpop .ctxhead`) are unchanged — re-pointed, not dropped.
      ".ctxpop {" in HTML and "function _ctxPopover(anchor)" in HTML
      and ".ctxpop .ctxhead {" in HTML)
check("3b it shows the three values the panel shows (messages / tokens / budget)",
      # 2026-11-21 (round 165): the stub rows became the inspector's OWN card, so the
      # values are read from the same `/api/context` display instead of hand-rolled
      # `<span>tokens</span>` labels. Re-pointed, not weakened: same three numbers,
      # now one vocabulary with the panel (see v1249).
      "esc(d.messages" in HTML and "esc(d.tokens" in HTML and "esc(d.budget" in HTML)
check("3c it reuses the ONE compaction door (no second mechanism)",
      'pop.querySelector(".cp-compact").onclick = () => { _closeCtxPop(); compactNow(); }' in HTML
      and "async function compactNow()" in HTML)
check("3d the ring is clickable and the numbers are kept",
      # 2026-11-22 (ROUND 172): the ring's click is a DELEGATED listener now (a re-rendered
      # composer can never leave `#cmpCtx` without a handler), so `_cc.onclick` is gone.
      # Assert the delegated form; the `#cmpCtx` surface and `_ctxDisplay` are unchanged.
      '$("cmpCtx")' in HTML and 'e.target.closest && e.target.closest("#cmpCtx")' in HTML
      and "_ctxPopover(onRing)" in HTML and "_ctxDisplay = d;" in HTML)
check("3e it closes on an outside click", '_closeCtxPop();\n});' in HTML)

# ---- rules the operator asked to record ------------------------------------
check("R1 the impeccable/frontendui rule is recorded",
      "impeccab" in RULES and "frontendui" in RULES and "altre parti grafiche webui" in RULES)
check("R2 the close-your-todos rule is recorded",
      "A TASK IS NOT FINISHED UNTIL ITS TODO LIST IS CLOSED" in RULES
      and "todotool" in RULES)

print("\n---")
print("v1244: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
