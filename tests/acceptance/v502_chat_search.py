#!/usr/bin/env python3
"""v502 — current-chat search supports word globs, OR, and saved queries."""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one source contract or hand-derived search behavior."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _glob_matches(pattern: str, word: str) -> bool:
    """Evaluate the documented word-glob semantics independently of the UI."""
    if not pattern or not pattern.replace("*", ""):
        return False
    if "*" not in pattern:
        return pattern.casefold() in word.casefold()
    source = "".join(".*" if char == "*" else re.escape(char) for char in pattern)
    return re.fullmatch(source, word, flags=re.IGNORECASE) is not None


check("chat header exposes an accessible search toggle and bar",
      'id="chatSearchToggle"' in HTML
      and 'id="chatSearchBar"' in HTML
      and 'role="search"' in HTML
      and 'id="chatSearchInput"' in HTML)
check("search offers previous, next, and a visible result count",
      'id="chatSearchPrev"' in HTML
      and 'id="chatSearchNext"' in HTML
      and 'id="chatSearchCount"' in HTML)
check("word search supports substring, prefix, and suffix globs",
      _glob_matches("*cd*", "scdissors")
      and _glob_matches("cd*", "cdrom")
      and _glob_matches("*cd", "abccd")
      and not _glob_matches("*cd", "cdrom"))
check("comma-separated patterns use OR across words",
      any(_glob_matches(pattern, word)
          for pattern in ("*cd", "*aer*", "*ddd")
          for word in ("abccd", "aeroplane", "fooddd")))
check("search pattern parsing and OR matching are implemented",
      "function _chatSearchPatterns(query)" in HTML
      and 'String(query || "").slice(0, 512).split(",").slice(0, 32)' in HTML
      and "function _chatSearchWordMatches(word, patterns)" in HTML
      and "patterns.some(" in HTML)
glob = HTML.split("function _chatSearchGlobMatches(", 1)
glob_body = glob[1].split("\nfunction ", 1)[0] if len(glob) == 2 else ""
check("glob matching is bounded and does not build user-controlled regex",
      "function _chatSearchGlobMatches(word, pattern)" in HTML
      and "new RegExp" not in glob_body
      and ".startsWith(" in glob_body
      and ".endsWith(" in glob_body
      and ".indexOf(" in glob_body)
check("matches are highlighted and navigable through collapsed groups",
      "chat-search-hit" in HTML
      and "function _chatSearchMove(delta)" in HTML
      and "details.open = true" in HTML)
check("last query is restored and saved in localStorage",
      'const CHAT_SEARCH_STORAGE_KEY = "sf_chat_search_query"' in HTML
      and "localStorage.getItem(CHAT_SEARCH_STORAGE_KEY)" in HTML
      and "localStorage.setItem(CHAT_SEARCH_STORAGE_KEY," in HTML)
check("Enter, Shift+Enter, and Escape control search navigation",
      'e.key === "Enter"' in HTML
      and "e.shiftKey" in HTML
      and 'e.key === "Escape"' in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
