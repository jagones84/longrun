#!/usr/bin/env python3
"""v495 — the session-create button remains visible as the sidebar narrows."""
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


row = re.search(
    r'<div id="sessionCreate" class="session-create[^"]*">(.*?)</div>',
    UI,
    flags=re.DOTALL,
)
input_rule = re.search(r"#sessInp\s*\{([^}]*)\}", UI)
button_rule = re.search(r"\.session-create\s*>\s*button\s*\{([^}]*)\}", UI)
row_rule = re.search(r"\.session-create\s*\{([^}]*)\}", UI)

check("A1 title input and new-session button share the sidebar row",
      bool(row) and 'id="sessInp"' in row.group(1)
      and 'data-call="newSession"' in row.group(1))
check("A2 title input can shrink below its intrinsic width",
      bool(input_rule) and re.search(r"min-width\s*:\s*0", input_rule.group(1)))
check("A3 new-session button keeps its width and label",
      bool(button_rule)
      and re.search(r"flex\s*:\s*0\s+0\s+auto", button_rule.group(1))
      and re.search(r"white-space\s*:\s*nowrap", button_rule.group(1)))
check("A4 row itself has no intrinsic minimum width",
      bool(row_rule) and re.search(r"min-width\s*:\s*0", row_rule.group(1)))

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
