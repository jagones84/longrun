#!/usr/bin/env python3
"""v440 — the chat column uses the full horizontal space (JAG-431l).

The AI answer bubbles were capped at `max-width: 860px` while the tool cards spanned
the whole chat column, so on a wide deck the answers wasted a large right margin. The
per-message cap is removed: a message (`.msg`) now uses the full width of `#log`,
consistent with the tool cards. Pins the fix in `webui/index.html`.

Deterministic, reads the source as text (no browser). Run: python3 tests/acceptance/v440_chat_full_width.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(REPO, "webui", "index.html")

with open(IDX, "r", encoding="utf-8") as f:
    idx = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("1a the message cap is gone — .msg uses the full width",
      ".msg { margin-bottom: 14px; max-width: 100%; }" in idx)
check("1b no 860px message cap remains", "max-width: 860px" not in idx)
check("1c the chat log itself is not width-capped",
      "#log { flex: 1; min-height: 0; overflow-y: auto; padding: 22px 26px; scroll-behavior: smooth; }" in idx)

print("---")
okc = sum(results)
print("\nv440: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
