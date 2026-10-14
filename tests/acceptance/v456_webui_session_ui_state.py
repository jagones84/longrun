#!/usr/bin/env python3
"""v456 — per-session chat state and instant history replay (JAG-455/JAG-458).

Pins the WebUI's local-only todo disclosure and chat viewport lifecycle. Guards
against animated autoscrolling once per historical item. Deterministic source
checks only: no browser, server, model, network, or batch UI driver.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    html = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


# The expanded todo ids are browser presentation state, namespaced by session.
check("1a todo expansion has its own localStorage key",
      'const _todoOpenStorageKey = "sf_tctree_open";' in html)
check("1b open todo ids are saved under the owning session id",
      'map[sid] = [...new Set(ids.map(String))];' in html
      and 'localStorage.setItem(_todoOpenStorageKey' in html)
check("1c restored disclosure state is applied to chat todo sections",
      'function _restoreTodoOpenState(sid)' in html
      and 'querySelectorAll("details.tctree")' in html
      and '_restoreTodoOpenState(_historySid)' in html)
check("1d manual disclosure changes capture that session's open todo ids",
      'document.addEventListener("toggle"' in html
      and 'e.target.matches("details.tctree, details.fgroup")' in html
      and '_saveTodoOpenState(sessionId, open)' in html)

# Deleted and cleared sessions must not leave stale local UI state. The session
# list is also authoritative for garbage collection if an SSE event was missed.
check("2a session deletion removes its saved disclosure state",
      '_forgetTodoOpenState(d.session)' in html)
check("2b clearing a session removes its old todo disclosure state",
      'if (d.session) _forgetTodoOpenState(d.session);' in html)
check("2c stale entries are pruned only from a valid sessions response",
      'Array.isArray(out.sessions)' in html
      and '_pruneTodoOpenState(out.sessions)' in html)

# History reconstruction should not smoothly scroll for every replayed item.
check("3a scrolling is suppressed for the session being replayed",
      '_historyReplaySession === sessionId' in html)
check("3b the completed replay jumps to the bottom with smooth scrolling disabled",
      'function _jumpLogToBottom()' in html
      and 'log.style.scrollBehavior = "auto"' in html
      and '_jumpLogToBottom();' in html)
check("3c replay restoration is finalized after the historical DOM is built",
      '_historyReplaySession = null;' in html
      and 'if (!_restoreChatScrollState(_historySid)) _jumpLogToBottom();' in html)
check("3d compaction/system summaries replay as a labelled card, never an AI bubble",
      'if (m.role === "system")' in html and 't: "s", v: m' in html
      and 'harnessInject({ inject_kind: "compact", text: e.v.content, ts: e.v.ts });' in html)

# Chat viewport position is independent for each session and survives replay.
check("4a chat viewport has its own per-session localStorage key",
      'const _chatScrollStorageKey = "sf_chat_scroll";' in html)
check("4b scroll positions are saved under their session id",
      'map[sid] = Math.max(0, Number(scrollTop) || 0);' in html
      and 'localStorage.setItem(_chatScrollStorageKey' in html)
check("4c user scrolling saves position but history replay does not overwrite it",
      'addEventListener("scroll"' in html
      and '_historyReplaySession !== sessionId' in html
      and '_saveChatScrollState(sessionId, log.scrollTop)' in html)
_outgoing_save = html.find('_saveChatScrollState(sessionId, $("log").scrollTop);')
_session_change = html.find('sessionId = s.id; localStorage.setItem("sf_session", sessionId);')
check("4d switching sessions saves outgoing viewport before changing session id",
      'function selectSession(s)' in html and _outgoing_save >= 0
      and _session_change >= 0 and _outgoing_save < _session_change)
check("4e history restores saved viewport and jumps to bottom only without saved state",
      'function _restoreChatScrollState(sid)' in html
      and 'if (!_restoreChatScrollState(_historySid)) _jumpLogToBottom();' in html)
check("4f deleted sessions lose their saved viewport state",
      '_forgetChatScrollState(d.session)' in html)
check("4g clearing and stale-session cleanup remove saved viewport state",
      'session.cleared' in html and '_forgetChatScrollState(d.session)' in html
      and '_pruneChatScrollState(out.sessions)' in html)

print("---")
okc = sum(results)
print("\nv456: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
