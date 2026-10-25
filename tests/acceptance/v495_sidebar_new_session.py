#!/usr/bin/env python3
"""v495 — the create-session entry stays visible as the sidebar narrows.

v631 superseded the inline "title input + new" row: the rail top is now ONE
compact toolbar, the ＋ opens the new-session DIALOG (which already owns the
name field `#nsTitle` and the workspace picker), and the search field appears
only when the magnifier is pressed. What must NOT regress is the reason this
test exists: the create entry is never squeezed out of the panel.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as source:
    UI = source.read()

checks = []


def check(name, passed):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name)


btn = re.search(r'<button[^>]*id="railNew"[^>]*>', UI)
btn_rule = re.search(r"\.rail-btn\s*\{([^}]*)\}", UI)

check("A1 the create entry is a compact icon button in the rail toolbar",
      bool(btn) and 'data-call="newSession"' in btn.group(0))
check("A2 it is a FIXED-size hit area (never squeezed by a narrowing rail)",
      bool(btn_rule)
      and re.search(r"flex\s*:\s*0\s+0\s+auto", btn_rule.group(1))
      and re.search(r"width\s*:\s*26px", btn_rule.group(1))
      and re.search(r"height\s*:\s*26px", btn_rule.group(1)))
check("A3 the session NAME lives in the dialog (#nsTitle), not in a rail input",
      'id="nsTitle"' in UI and 'id="sessInp"' not in UI
      and "newSession()" in UI)
check("A4 the old inline title row is gone (no dead CSS/ids)",
      "#sessInp" not in UI and 'id="sessionCreate"' not in UI)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
