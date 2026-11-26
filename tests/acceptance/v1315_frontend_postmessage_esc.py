#!/usr/bin/env python3
"""v1315 — two frontend fixes from the 2026-11-27 audit (CodeQL JS).

  A  `editor.js` `esc()` escaped `&`, `<`, `>` but not `"`/`'`, yet it is used
     inside HTML attributes (`data-sheet="…"`). A sheet name carrying a quote
     could break out of the attribute — incomplete attribute sanitisation
     (codeql `js/incomplete-html-attribute-sanitization`). Pinned: quotes escape.
  B  four `postMessage(…, "*")` calls targeted every origin, while two other call
     sites already used `location.origin` (codeql `js/cross-window-information-leak`).
     Every one of them reads `contentDocument` first, so the target is same-origin.
     Pinned: no `"*"` target remains.

Source-level assertions (the UI is one big HTML/JS file read as text); no browser.

Run:  python3 tests/acceptance/v1315_frontend_postmessage_esc.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


ED = read("webui", "assets", "editor.js")
UI = read("webui", "index.html")

# ── A · esc() neutralises quotes ────────────────────────────────────────────
_esc = ED[ED.index("function esc("):ED.index("function esc(") + 260]
check("A1 esc() escapes the double quote",
      "&quot;" in _esc, _esc[:120])
check("A2 esc() escapes the single quote",
      "&#39;" in _esc, _esc[:120])
check("A3 esc() still escapes &, <, >",
      all(t in _esc for t in ("&amp;", "&lt;", "&gt;")))

# ── B · no postMessage targets "*" ──────────────────────────────────────────
_wild = [m.start() for m in re.finditer(r"postMessage\([^;]*?,\s*\"\*\"\s*\)", UI)]
check("B1 no postMessage uses the wildcard target", not _wild,
      "%d occurrence(s)" % len(_wild))
check("B2 the same-origin targets are explicit",
      UI.count("location.origin") >= 4, str(UI.count("location.origin")))

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
