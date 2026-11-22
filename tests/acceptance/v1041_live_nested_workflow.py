#!/usr/bin/env python3
"""v1041 — the live chat nests the turn's work under its todo, exactly like a reload.

Operator: *"the chat session is not refreshed realtime … i don't see the chat
workflow under the todo/justifications, i see it only if i press the refresh
button — but that button causes a temporary blackout of the chat."*

Every card/inject is PERSISTED with the step it belongs to (`node=_cur_node()`,
the same value `persist_tool_card` / `persist_inject` store), so a RELOAD nests
the work under that todo. The LIVE render events carried no node, so the stream
piled the work into the free group ABOVE the todo cards; and a completed step's
section was collapsed live while loadHistory reopens every step that holds work.
Hence: nothing under the todos until ↻.

This pins both halves of the fix:

  A) the chat loop stamps the SAME step on the live render events (and never on
     a transient frame a reload cannot reproduce);
  B) the WebUI points the next card/inject at that step, opens the step the work
     landed in, and never hides a completed step that holds cards.

Deterministic: reads the two sources; no server, no model, no network.
Run: python3 tests/acceptance/v1041_live_nested_workflow.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as f:
    AGENT = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one deterministic live-nesting contract."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _body(source: str, name: str, next_name: str) -> str:
    """Return a named block of source up to the next occurrence of `next_name`."""
    start = source.find(name)
    end = source.find(next_name, start + len(name))
    return source[start:end] if start >= 0 and end > start else ""


# --- A: the chat loop stamps the live render events --------------------------
_loop = AGENT[AGENT.find("def _cur_node():"):AGENT.find("def _after():")]
check("A1 the live emitter is wrapped ONCE, from the same _cur_node() a reload uses",
      "_live_on_event = on_event" in _loop
      and "def on_event(kind, **d):" in _loop
      and "_nid = _cur_node()" in _loop
      and 'd["node"] = _nid' in _loop)
check("A2 every persisted card/inject kind is stamped",
      all(('"%s"' % k) in _loop for k in
          ("tool.call", "tool.result", "tool.blocked", "harness.inject")))
check("A3 transient frames are NOT stamped (a reload cannot reproduce them)",
      'd.get("inject_kind") == "system"' in _loop
      and 'd.get("repeat")' in _loop
      and 'd.get("tool") == "todo.write"' in _loop)
check("A4 the persisted writers keep using the SAME _cur_node() (one truth)",
      AGENT.count("node=_cur_node()") >= 5
      and 'persist_inject(sess, kind, wire["content"], node=_cur_node()' in AGENT)

# --- B: the WebUI honours that node -----------------------------------------
_at = _body(UI, "function _atNode(nid) {", "function _openSection(nid) {")
check("B1 _atNode points the next append at the stamped step",
      "_activeNodeId = nid" in _at and "_activeScope = null" in _at)
check("B2 a live tool card is placed under its step",
      # 2026-11-22 (ROUND 177): the tool rows carry no time, so the live handler calls
      # `toolCard(d.tool, d.args)` — the ts argument was dropped. Same placement, no clock.
      "_atNode(d.node); toolCard(d.tool, d.args)" in UI)
check("B3 a live harness inject is placed under its step",
      "_atNode(d.node); harnessInject(d)" in UI)
_open = _body(UI, "function _openSection(nid) {", "function _logAppend(el, chapter)")
check("B4 reusing a step OPENS it, so work landing there is visible live",
      "last.open = true;" in _open)
_upd = _body(UI, "function chatNodeUpdate(node) {", "function _repaintChatNodes()")
check("B5 a completed step with cards is never collapsed (a reload reopens it)",
      "kids.children.length" in _upd
      and "if (!kids || !kids.children.length) d.open = false;" in _upd)
_apply = _body(UI, "function applyGraphEvent(d) {", "function planNodes(g)")
check("B6 the SESSION is the boundary — an event without a run is not dropped",
      "if (!d || !d.node) return;" in _apply
      and "!d.run" not in _apply)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
