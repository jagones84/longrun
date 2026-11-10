#!/usr/bin/env python3
"""v955 — a chatbox message the agent received must be IN the operator's chat, and
the composer queue must accumulate instead of evaporating.

Live 2026-11-11 (operator): *"i messaggi della chatbox in queue (e forse anche
steer) devono essere accumulabili … noto il bug che non appaiono nella chat
sessione quando inviati, l'agente li vede ma io nella sessione non li vedo"*.

Measured cause (three separate holes on the same path):

  1. The bubble for a message THIS tab sent was painted by `send()` alone. The
     turn's OWN SSE stream never carries `chat.user` (the generator publishes it
     to the feed only), so a transcript repaint that fetched its snapshot BEFORE
     the server appended the message (the turn appends it inside its worker, after
     the turn lock) wiped the bubble — and nothing put it back: the agent answered
     words the chat did not show.
  2. The feed's `chat.user` did nothing but re-attach a running stream. A message
     accepted by the server (a steer from another tab/device, an agent's message)
     therefore never reached the open transcript until a manual reload.
  3. A live user message could be inserted at the log root while a task section
     was active; the section's next event MOVED the section to the bottom, i.e.
     BELOW the operator's own message, burying it mid-transcript. Queued messages
     vanished the same way (a late graph event for the old step).

  Plus: the queue lived in a plain JS object, so a reload / tab switch / the phone
  silently dropped every message still waiting.

Locked here:
  * a message this tab sent is re-appended by `loadHistory` when the painted
    snapshot predates it (`_pendingUser`), and dropped once it is in the snapshot;
  * the durable feed renders `chat.user` (and `chat.steer`, labelled) for the open
    session, deduped against a bubble that already contains the text;
  * `chat.steer` owns the steer bubble; `chat.user(steer=True)` does not draw it
    a second time, bare;
  * a user turn is a BOUNDARY: it closes the task scope and no section may be
    moved past it;
  * the queue is per session, persisted (`sf_queue:<sid>`), accumulates, and is
    flushed as soon as its session is idle on screen.

Behaviour was proven live in the real page (headless Chrome, CDP): the queue kept
two items through a reload of the module state, a repaint without the message
still showed it, and a section could no longer jump below it. This file pins the
contract so a later rewrite cannot silently reopen it.

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v955_queued_message_visible.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()


def between(start, end):
    i = HTML.find(start)
    if i < 0:
        return ""
    j = HTML.find(end, i + len(start))
    return HTML[i:j if j > 0 else len(HTML)]


SEND = between("function send(text, display, atts)", "function attachTurn(")
LOADHIST = between("async function loadHistory()", "/* v1.6.3 (JAG-55): splits a trailing")
WHO = between("function who(role, text, ts", "/* v1.6.3 (JAG-55): inline tool-call mini-card")
OPENSEC = between("function _openSection(nid)", "function _logAppend(")
QUEUE = between("let msgQueue = {}", "/* JAG-364: a queued message is now")
BIND = between("function _bindRenderStream(es, live, adopt)", "function attachTurn(")
# the FEED block: anchored on its own `push("💬 user: ")` (the per-turn binder has a
# `chat.user` listener too, so the event name alone would match the wrong one)
_fi = HTML.find('push("💬 user: "')
FEED = HTML[max(0, _fi - 500):HTML.find('es.addEventListener("chat.done"', _fi)] if _fi > 0 else ""

# --- A: a message this tab sent is never missing from a repaint --------------
check("A1 the pending-user ledger exists (bounded)",
      "let _pendingUser = [];" in HTML and "_pendingUser.length > 8" in HTML)
check("A2 send() records the message it painted",
      "_pendingUserAdd(sessionId, (_splitAttBlock(msg).rest" in SEND)
check("A2b the STEER path records it too",
      "_pendingUserAdd(sessionId, (_splitAttBlock(_rawMsg).rest" in SEND)
check("A3 a brand-new chat re-keys the entry when the server names it",
      "_pendingUser.forEach(p => { if (!p.sid) p.sid = s; });" in SEND)
check("A4 loadHistory reconciles AFTER it painted",
      "_reconcilePendingUser(_historySid)" in LOADHIST
      and LOADHIST.find("applyThreadTitles();") < LOADHIST.find("_reconcilePendingUser(_historySid)"))
check("A5 the reconcile re-appends only what the snapshot lacks",
      "_userBubblePresent(p.text)" in HTML and "who(\"user\", p.text, p.ts)" in HTML)
check("A6 presence is tested by CONTAINment (a steer renders its label)",
      "return bubs.some(b => b.indexOf(t) >= 0);" in HTML)

# --- B: the durable feed is the second writer --------------------------------
check("B1 the feed renders `chat.user` for the OPEN session",
      "if (!_userBubblePresent(clean || d.text))" in FEED
      and "who(\"user\", clean || d.text, null, d.sender" in FEED)
check("B2 the feed renders `chat.steer` with its label",
      'es.addEventListener("chat.steer"' in FEED and "who(\"user\", \"🎯 steer: \" + t);" in FEED)
check("B3 it still follows a turn it did not start",
      "attachIfRunning(sessionId);" in FEED)
check("B4 ONE event owns a steer bubble (chat.user skips steer=True)",
      "if (d.steer) return;" in BIND)
check("B5 the own-turn binder still renders a turn this tab did not start",
      "who(\"user\", clean || txt, null, d.sender, d.subjob, null, d.sender_session); });" in BIND)

# --- C: a user turn is a boundary -------------------------------------------
check("C1 who() closes the task scope for a user turn",
      "_activeNodeId = null; _activeScope = null;\n    _freeClose(); _freeAppend(d, chapter);" in WHO)
check("C2 a section is never moved past a user group",
      "_next.classList.contains(\"fgroup\")" in OPENSEC)
check("C3 ... and its next work lands after the boundary, not inside it",
      "_activeNodeId = null; _activeScope = null; return lg;" in OPENSEC)

# --- D: the queue accumulates and survives ----------------------------------
check("D1 the queue lives per session, in localStorage",
      "function _qKey(sid) { return \"sf_queue:\" + (sid || \"\"); }" in QUEUE
      and "JSON.parse(localStorage.getItem(_qKey(k))" in QUEUE)
check("D2 it is saved on enqueue / remove / edit / steer / flush",
      HTML.count("_qSave") >= 6, HTML.count("_qSave"))
check("D3 the in-memory-only queue is GONE (one truth)",
      "msgQueue[k] = msgQueue[k] || []" not in HTML)
check("D4 switching to an idle session drains its queue",
      "if (!turnSSE[s.id]) flushQueue(s.id);" in HTML)
check("D5 flushQueue still refuses another session / a live turn",
      "if (sessionId !== s || turnSSE[s]) return;" in HTML)

# --- E: the operator wording is recorded once -------------------------------
check("E1 the reason is in the source, not only in a plan",
      "l'agente li vede" in HTML or "the operator's own words" in HTML)

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
