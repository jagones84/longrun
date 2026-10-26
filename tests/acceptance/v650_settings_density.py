#!/usr/bin/env python3
"""v650 — every Settings menu is as wide as its content, not as wide as the panel.

Source (operator): "ma poi in generale tutti i menu sono poco compatti, super
larghi .. non mi sta benissimo".

Measured live before the change: the window restored a saved 850px, the main
column was 640px, and every control had been built to FILL it — a 577px select
for the value `openrouter:z-ai/glm-5.3-flash`, a 577px box for the number `2`,
a 577px field for a skill filter. The panel was a landing page, not a panel.

Contract:
  A) a Settings control stops stretching at a content width (340px);
  B) a number stops much earlier (110px) and keeps a usable minimum;
  C) a textarea KEEPS the full width — its content is long text;
  D) checkboxes / radios / ranges are untouched by the width cap;
  E) the rule is scoped to Settings, so the chat composer and the Inspector
     keep their own sizing;
  F) a saved window size is clamped to the design width, so an older roomy
     layout cannot re-inflate every field.

Deterministic: static contract checks on webui/index.html. No server, no model.
Run: python3 tests/acceptance/v650_settings_density.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()

# ---- A/B/C/D. the density rule ----------------------------------------------
RULE = "#swMain select,\n  #swMain input:not([type=checkbox]):not([type=radio]):not([type=range]),\n  #swMain .u-w100:not(textarea) { max-width: 340px; min-width: min(160px, 100%); }"
check("A1 selects and text inputs cap at a content width",
      RULE in ui and "max-width: 340px" in ui)
check("B1 numbers cap at 110px with a usable minimum",
      # v653: the rule must repeat the `:not(...)` chain, otherwise the 160px
      # control minimum above outranks it and a count box keeps stretching
      # (live: "max sources" wrapped because its 160px input squeezed the label).
      "#swMain input[type=number]:not([type=checkbox]):not([type=radio]):not([type=range]) {\n    max-width: 110px; min-width: 72px; }" in ui)
check("C1 a textarea is excluded from the cap (its content IS long text)",
      "#swMain .u-w100:not(textarea)" in ui)
check("D1 checkbox / radio / range keep their intrinsic size",
      ":not([type=checkbox]):not([type=radio]):not([type=range])" in ui)
check("E1 the cap is scoped to the Settings main column",
      ui.count("#swMain select,") == 1
      and "#composer" not in ui.split("#swMain select,")[1].split("}")[0])

# ---- F. the window cannot re-inflate ---------------------------------------
check("F1 a saved window width is clamped to the design width",
      "w.style.width = Math.min(pos.w, innerWidth, 760) + \"px\";" in ui)
check("F2 the clamp keeps the phone case working (innerWidth is still a bound)",
      'const w = settingsWin();' in ui
      and "if (pos.h) w.style.height = Math.min(pos.h, innerHeight) + \"px\";" in ui)

# ---- the two panels that carry the most fields still cap ------------------
check("G1 the generated settings forms inherit the cap (they live in #swMain)",
      'id="swMain"' in ui and "_setFieldEl" in ui)
check("G2 the obsolete duplicate select rule is gone",
      "#swMain .card select.u-w100 { max-width: 340px; text-overflow: ellipsis; }" not in ui)

# ---- H. no prose paragraph left inside a Settings card -----------------------
PARAS = [
    "Stateless system automation agent",
    "Model that writes the cited summary for Research",
    "Semantic vectors for the codebase",
    "One topic bar, two modes",
    "Manual sources for the selected notebook",
]
for i, text in enumerate(PARAS, 1):
    check("H%d the explanation of %r is a tooltip, not a paragraph" % (i, text[:28]),
          'class="remaining u-m006"' not in ui and ('title="' + text) in ui,
          text[:28])

print("---")
passed = sum(results)
print("\nv650: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
