#!/usr/bin/env python3
"""v1245 — the phone topbar fits OnePlus 15R, and an image link carries ONE truth.

Operator (2026-11-20): *"on mobile la barra superiore è satura e non si vede tutta, i
tre dot accanto all'icona LONGRUN vanno avvicinati all'icona per risparmiare horizontal
space. Devi essere visualizzato in modalità mobile OnePlus 15R."*

Measured with headless Chrome mobile emulation (dpr 2, touch), approvals chip VISIBLE:
at 363 and 380 wide the bar carried 388 px of content — 25/8 px OVER — so the header
scroller clipped the right end (the gear). The 361–480 band is exactly where a OnePlus
15R lands (~363 CSS px at dpr 3.5). The fix: the ⋮ is part of the BRAND, so it hugs
the wordmark (the logo's 6 px padding and the bar gap were dead space), every target
loses 1–2 px. Re-measured: overflow 0 at 412/400/380/363/360, ⋮ 0 px from the logo.

Also: `a.imglink` used to carry `_rawUrl(p)` in `data-u` on ONE path and the bare path
on the other, so `_inlineImages` wrapped the URL a SECOND time and the preview 404'd.
One truth: `data-u` is always the PATH; the two readers build the URL.

Deterministic and offline: static pins on webui/index.html.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:220]) if detail and not ok else ""))


# ---- A: the 361..480 phone band fits ---------------------------------------
_BAND = HTML.split("@media (max-width: 480px) and (min-height: 501px)")[1].split("}")[0:1]
_band = HTML.split("@media (max-width: 480px) and (min-height: 501px)")[1][:1400]
check("A1 the band exists and tightens the bar padding + gap",
      "#topbar { gap: 3px; padding: 8px 7px; }" in _band, _band[:300])
check("A2 the ⋮ hugs the wordmark (logo padding gone, brand pulled in)",
      "#topbar .logo { padding-right: 0; }" in _band
      and "#topbar .brand-wrap { margin-left: -3px; }" in _band)
check("A3 the tabs and the three icon buttons shave the last pixels",
      "#topbar #topTabs .ttab { width: 32px; }" in _band
      and "width: 27px; min-width: 27px; height: 27px;" in _band)
check("A4 the tighter tiers still come LAST (480 before 360)",
      HTML.index("@media (max-width: 480px) and (min-height: 501px)")
      < HTML.index("@media (max-width: 360px) and (min-height: 501px)"))

# ---- B: one truth for an image link ---------------------------------------
check("B1 the text-scan path stores the PATH, not a raw URL",
      'if (_isImage(p)) { a.className = "imglink"; a.dataset.u = p; }' in HTML)
check("B2 the click reader builds the raw URL itself",
      "showImage(_rawUrl(a.dataset.u))" in HTML)
check("B3 no second wrap: the old `_rawUrl(p)` assignment is gone",
      "a.dataset.u = _rawUrl(p)" not in HTML)
check("B4 the inline preview builds the URL from the path",
      "const src = /^https?:\\/\\//i.test(u) ? u : _rawUrl(u);" in HTML)

print("\n---")
print("v1245: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
