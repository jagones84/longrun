#!/usr/bin/env python3
"""v274 — chat/todo UI coherence (JAG-274).

The chat must read as a CHRONOLOGICAL stream: the newest work is always at the
bottom, a todo step is an inline collapsible section, a sticky "current step"
bar shows what the agent is doing NOW even when the step scrolled up, clicking a
sidebar todo jumps the chat to that step, and a re-plan announcement is drawn
BEFORE the steps it produced (never buried under the list).

Static source assertions (no browser, no server): the WebUI is a single file and
these JS invariants are what we can freeze deterministically. Single-line probes
only (the file may carry CRLF).

Run: python3 tests/v274_chat_stream.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")
SRV = os.path.join(REPO, "src", "longrun", "core/server.py")

with open(UI, encoding="utf-8") as f:
    html = f.read()
with open(SRV, encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    srv += f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def between(text, a, b):
    """Slice text from the first occurrence of `a` to the next occurrence of `b`."""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i)
    return text[i:] if j < 0 else text[i:j]


# --- sticky "current step" bar -------------------------------------------------
check("nowbar element exists in the markup", '<div id="nowbar" hidden>' in html)
check("nowbar has its own style", "#nowbar {" in html and "#nowbar .nid" in html)
check("nowbar is a function that prefers the ACTIVE node",
      "function _updateNowBar() {" in html and "_activeNodeId && _nodeById(_activeNodeId)" in html)
check("nowbar hides itself when no step is active", "if (!n) { bar.hidden = true; return; }" in html)
check("nowbar click jumps to the step", 'bar.onclick = () => _scrollToNode(n.id);' in html)
check("the latest activity is stamped on the bar", '_nowLast = "→ " + name;' in html)

# --- open-at-bottom sections ---------------------------------------------------
check("_openSection exists", "function _openSection(nid) {" in html)
check("a section is reused ONLY while it is still the last element",
      'last.parentNode === $("log") && !last.nextElementSibling' in html)
check("otherwise a FRESH section opens at the bottom (no burying up)",
      "const det = _mkSection(_nodeById(nid) || { id: nid, label: \"\", status: \"doing\" });" in html)
check("_logAppend routes through _openSection",
      "function _logAppend(el, chapter) {" in html and "_openSection(_activeNodeId)" in html)
check("_resetChatTree clears the section map (no session leak)",
      "function _resetChatTree() { _chatNodes = {}; _chatSections = {};" in html)
check("done/cancelled/superseded close the section",
      'node.status === "done" || node.status === "cancelled" || node.status === "superseded"' in html)

# --- sidebar todo -> jump the chat to that step --------------------------------
check("_scrollToNode exists and returns a hit", "function _scrollToNode(nid) {" in html
      and "_alignChatNodeTop(log, det);" in between(html, "function _scrollToNode(nid) {", "function _updateNowBar")
      and "return true;" in between(html, "function _scrollToNode(nid) {", "function _updateNowBar"))
_scroll = between(html, "function _scrollToNode(nid) {", "function _updateNowBar")
_align = between(html, "function _alignChatNodeTop(log, det) {", "function _scrollToNode(nid) {")
check("todo click aligns within #log using the live CSS zoom scale",
      "_alignChatNodeTop(log, det);" in _scroll
      and "const scale = _pageScale();" in _align
      and "(detRect.top - scrollportTop) / scale" in _align
      and "log.scrollTo({ top: Math.max(0, nextTop), behavior: \"smooth\" });" in _align)
check("sidebar task click both shows the detail AND jumps",
      "showNodeDetail(n); _scrollToNode(n.id);" in html)
check("the sidebar todo advertises the jump", "click to show details and jump the chat to this step" in html)

# --- chronological stream on reload --------------------------------------------
_lh = between(html, "const _mts = (s.messages || [])", "es.forEach(e =>")
check("loadHistory builds one ts-ordered stream", "evs.sort((A, B) =>" in _lh)
check("cards/injects fall back to the ts at their `after`", "_tsAt(" in _lh)
check("user turns stay top-level (chronology anchor)",
      'if (m.role === "user") { who("user", m.content, m.ts, m.sender, m.subjob, m.chapter' in html)

# --- re-plan announcement BEFORE the new steps ---------------------------------
_rg = between(html, "async function replanGraph() {", "async function resetPlan()")
check("replanGraph forces a top-level announcement",
      "_activeNodeId = null; _activeScope = null;" in _rg)
check("the announcement comes BEFORE the drawn steps",
      _rg.find('who("ai", "↻ re-plan') >= 0
      and _rg.find('who("ai", "↻ re-plan') < _rg.find("chatNodeAdd(n)"))
check("a cancelled prompt does nothing", "if (note === null) return;" in _rg)
check("graph.replanned refreshes the panel/feed",
      'es.addEventListener("graph.replanned"' in html)

# --- server side: replan announces on the feed, no chat turn injected ----------
check("server publishes graph.replanned on replan",
      'publish("graph.replanned"' in srv)
_branch = between(srv, 'if action == "replan":', "return {\"added\"")
check("server does NOT inject a chat turn on replan",
      "We deliberately do NOT inject a chat" in srv
      and "_inject(" not in _branch and "push_turn" not in _branch)
check("replan branch only re-plans + publishes the feed event",
      "replan_from_model" in _branch and 'publish("graph.replanned"' in _branch)

# --- JAG-385: the live CoT lives ONLY inline in the chat -----------------------
# It used to be written twice: the inline "chain-of-thought (live)" block AND the
# mobile-only `#cotDrawer` strip at the bottom. On a phone the same monologue
# scrolled in both places. Keep the inline block, drop the drawer entirely.
check("the mobile CoT drawer is gone from the markup", 'id="cotDrawer"' not in html)
check("no cotDrawer/cotFeed plumbing remains",
      "cotDrawer" not in html and "cotFeed" not in html and "cotText" not in html)
check("the live CoT is written inline into the chat block",
      "function ensureThink()" in html
      and "const el = ensureThink();" in html
      and "el.textContent = t;" in html)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
