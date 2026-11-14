#!/usr/bin/env python3
"""v1013 — the composer model name uses available room before it ellipsizes."""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


check("A1 global model selector has no fixed width cap",
      re.search(r"\.model-btn\s*\{[^}]*\bmax-width\s*:", HTML) is None)
check("A2 composer model button tracks its wrapper and may shrink",
      re.search(
          r"#composerBar \.cb-right \.model-wrap > button \{"
          r"[^}]*max-width:\s*100%;[^}]*min-width:\s*34px;"
          r"[^}]*flex:\s*0 1 auto;",
          HTML,
      ) is not None)
check("A3 model name can shrink without forcing adjacent controls",
      re.search(
          r"#composerBar \.mname \{"
          r"[^}]*min-width:\s*0;[^}]*flex:\s*0 1 auto;"
          r"[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;",
          HTML,
      ) is not None)
check("A4 caret keeps its own width while the name shrinks",
      re.search(r"\.model-btn \.mc \{[^}]*flex:\s*0 0 auto;", HTML) is not None)
check("A5 action buttons remain fixed-size flex items",
      re.search(
          r"#composerBar \.cb-left > button, #composerBar \.qmode-wrap > button,"
          r"\s*#composerBar \.cb-right > button \{ flex:\s*0 0 auto;",
          HTML,
      ) is not None)
check("A6 responsive rules do not reintroduce a model width cap",
      re.search(
          r"#composerBar \.cb-right \.model-wrap > button\s*\{\s*"
          r"max-width:\s*(?:150|118|92)px|"
          r"#composerBar \.cb-right \.model-wrap > button\s*\{[^}]*"
          r"min-width:\s*(?:64|54)px",
          HTML,
      ) is None)
check("A7 the complete model reference remains available in the button tooltip",
      'b.title = ref ? ("choose the LLM for this chat' in HTML
      and '" + ref)' in HTML)
check("A8 the composer still stays on one row",
      re.search(
          r"#composerBar \{ display: flex; align-items: center; flex-wrap: nowrap",
          HTML,
      ) is not None)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
