#!/usr/bin/env python3
"""v473 — the chat shows the ACTIVE session's name in its own header (JAG-480).

Operator request: "the name of the current chat session shall be put in the chat
window on top, as a small top bar with the session name, so one can copy/paste it
into the left panel search to find the session if it was previously collapsed".

Contract locked here (WebUI source lock, the same style as v472):
  * the chat hosts a header element of its own;
  * the header names the session from the REAL /api/sessions payload
    (`_sessTitle`), never a locally invented label;
  * it exposes the exact text (name + id) as a one-click copy that uses the
    existing `copyText` helper;
  * it is refreshed on every sessions load, and hidden when no session is open.

Deterministic and offline: source-only.
Run: python3 tests/acceptance/v473_chat_session_header.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("A1 the chat owns a header element",
      'id="chatHead"' in HTML, "")
check("A2 the header shows a title slot and the session id",
      'id="chatHeadTitle"' in HTML and 'id="chatHeadId"' in HTML, "")
check("A3 a copy affordance sits in the header",
      'id="chatHeadCopy"' in HTML and "copy name" in HTML, "")
check("A4 the header is styled as a compact top bar",
      "#chatHead {" in HTML and "#chatHead[hidden] { display: none; }" in HTML
      and "#chatHead .ch-title" in HTML, "")
check("A5 the title comes from the REAL sessions payload",
      "function renderChatHead(" in HTML and "_sessTitle[sessionId]" in HTML, "")
check("A6 the header hides when no session is open",
      "head.hidden = !sessionId;" in HTML, "")
check("A7 the copy uses the shared clipboard helper",
      "function _copySessionName(" in HTML and "copyText(payload)" in HTML, "")
check("A8 the header is refreshed on every sessions load",
      HTML.count("renderChatHead()") >= 2, HTML.count("renderChatHead()"))
check("A9 the copy button is wired at init",
      '$("chatHeadCopy"); if (_chc) _chc.onclick = _copySessionName;' in HTML, "")

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
