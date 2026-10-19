#!/usr/bin/env python3
"""v501 — Markdown file links in chat replies open in the editor.

Deterministic source-contract checks. Web links and fragments must keep normal
navigation; local filesystem paths must use the existing editor path.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record and print one deterministic source-contract check."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


linkifier = HTML.split("function linkifyNodes(root)", 1)[1].split(
    "function linkifyFiles", 1
)[0]
helper = HTML.split("function _markdownFilePath(", 1)
helper_body = helper[1].split("\nfunction ", 1)[0] if len(helper) == 2 else ""

check("Markdown anchors are classified as local file links",
      'root.querySelectorAll("a[href]")' in linkifier
      and "_markdownFilePath(a.getAttribute(\"href\"))" in linkifier)
check("local Markdown file links prevent navigation and open the editor",
      'root.querySelectorAll("a.filelink")' in linkifier
      and "e.preventDefault(); openInEditor(a.dataset.p);" in linkifier)
check("absolute and percent-encoded local paths are normalized",
      "decodeURIComponent" in helper_body
      and "ref.split(/[?#]/, 1)" in helper_body)
check("non-web schemes, including file URLs, and fragments stay untouched",
      "^[a-z][a-z\\d+.-]*:" in helper_body
      and 'ref[0] === "#"' in helper_body
      and "protocol" not in helper_body)
check("plain-text file paths remain linkified",
      "root.querySelectorAll(\"a.filelink\")" in linkifier
      and "READABLE_RE.source" in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
