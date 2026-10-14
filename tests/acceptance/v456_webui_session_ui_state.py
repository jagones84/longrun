#!/usr/bin/env python3
"""v456 — per-session todo disclosure state and instant history replay (JAG-455).

Pins the WebUI's local-only disclosure preference lifecycle and guards against
animated autoscrolling once per historical item. Deterministic source checks only:
no browser, server, model, network, or batch UI driver.
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
      and 'if (sessionId === _historySid) { _stick = true; _jumpLogToBottom(); }' in html)

print("---")
okc = sum(results)
print("\nv456: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
