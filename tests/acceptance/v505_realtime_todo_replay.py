#!/usr/bin/env python3
"""v505 — graph events received during history replay do not duplicate chat todos."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one deterministic live-render contract."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _function_body(source: str, name: str, next_name: str) -> str:
    """Return a named function and its body from the inline UI script."""
    start = source.find(name)
    end = source.find(next_name, start + len(name))
    return source[start:end] if start >= 0 and end > start else ""


queue = _function_body(UI, "function _queueHistoryGraphEvent", "function _flushHistoryGraphEvents")
flush = _function_body(UI, "function _flushHistoryGraphEvents", "function applyGraphEvent")
apply = _function_body(UI, "function applyGraphEvent(d)", "function planNodes")
chat_apply = _function_body(UI, "function _applyChatGraphEvent(d)", "function _applyGraphPanelEvent")
panel_apply = _function_body(UI, "function _applyGraphPanelEvent(d)", "function applyGraphEvent")
history = _function_body(UI, "async function loadHistory()", "/* v1.6.3 (JAG-55): splits")

check("same-session graph events defer chat DOM updates during history replay",
      "_historyReplaySession === sessionId" in apply
      and "_queueHistoryGraphEvent(d)" in apply
      and "_applyChatGraphEvent(d)" in apply
      and apply.index("_queueHistoryGraphEvent(d)") < apply.index("_applyChatGraphEvent(d)"))
check("replay queue coalesces feed and chat events by session and node ID",
      "new Map()" in UI
      and "d.session" in queue
      and "d.node.id" in queue
      and ".set(" in queue)
check("queued node events flush only after replay releases ownership",
      "_historyReplaySession = null" in history
      and "_flushHistoryGraphEvents(_historySid)" in history
      and history.index("_historyReplaySession = null")
      < history.index("_flushHistoryGraphEvents(_historySid)"))
check("flush reuses the normal session-filtered, ID-upsert event path",
      "applyGraphEvent(event)" in flush
      and "_chatNodes[d.node.id]" in chat_apply
      and "chatNodeUpdate(d.node)" in chat_apply
      and "d.session !== sessionId" in apply)
check("newer graph state replaces older queued state for the same node",
      "_historyGraphPending.set(key, Object.assign({}, d, {session: sid}))" in queue)
check("the right-hand task graph remains live while chat replay defers rows",
      "_applyGraphPanelEvent(d)" in apply
      and "renderGraph()" in panel_apply)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
