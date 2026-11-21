#!/usr/bin/env python3
"""v1264 — queue really queues (and is visible), steer really steers.

Operator (2026-11-21): *"queue message doesn't work, message is sent; steer interrupting
current run. I passed from steer to queue then sent the message … it shall appear in the
up msg box bar, there's the section for messages. Steer only shall steer the message
directly interrupting the agent, queue not, and multiple queue can be accepted as in Trae"*.

  A  the delivery decision asks the SERVER when this page has no turn handle, then attaches
  B  a stale "running" page that finds the server idle FLUSHES its queue (no stuck item)
  C  a queued message is visible in the bar: a count on the queue icon + a label that
     lists the queue even when a background command runs
  D  steer and queue keep their meanings, and the queue accepts many messages

Deterministic and offline. Run: python3 tests/acceptance/v1264_queue_delivery_and_badge.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


def fn(text, name, end="\n}"):
    return between(text, "function %s(" % name, end)


# ---- A: the decision consults the server when the page has no handle ------
SEND = between(UI, "async function send(", "// v1051b:")
check("A1 send() is async and asks /api/chat/live before deciding",
      "async function send(" in UI and 'api("GET", "/api/chat/live")' in SEND
      and "if (!turnSSE[sessionId]) {" in SEND)
check("A2 a live session is ATTACHED, so the queue/steer branch is the one that runs",
      "((live && live.active) || []).includes(sessionId)" in SEND
      and "attachTurn(sessionId, _resumeIdFor(sessionId));" in SEND)
check("A3 the queue branch is still guarded by the (now real) turn handle",
      'if (turnSSE[sessionId]) {' in UI
      and "enqueueMsg({ raw: _rawMsg, text: raw.replace(" in UI
      and 'api("POST", "/api/chat/steer"' in UI)

# ---- B: a stale "running" state drains instead of hiding the message ------
ATT = fn(UI, "attachIfRunning")
check("B1 when the server says IDLE the queue is flushed, not left waiting",
      'if ((out.active || []).includes(sid)) attachTurn' in ATT and "else flushQueue(sid);" in ATT)
REC = between(UI, "async function _queueReconcile() {", "function _bgPollStop()")
check("B2 a missed `done` self-heals: while something waits, the poll asks the server",
      "async function _queueReconcile() {" in UI and 'api("GET", "/api/chat/live")' in REC
      and "flushQueue(sessionId);" in REC and "delete turnSSE[sessionId];" in REC
      and "_loadBgJobs(); _queueReconcile();" in UI)

# ---- C: the queued message is VISIBLE in the bar --------------------------
check("C1 the queue icon carries a COUNT badge (CSS + accessible name)",
      ".cs-tab[data-count]::after { content: attr(data-count);" in UI
      and 'b.dataset.count = String(n); else b.removeAttribute("data-count");' in UI
      and '(k === "queue" ? " \\u2014 " + n + " queued" : " \\u2014 " + n + " running")' in UI)
check("C2 the count reads the ONE queue (and the running shell jobs)",
      '_q().length' in UI and '(_bgJobs || []).filter(j => j && j.running).length' in UI)
LBL = between(UI, "function _csLabel() {", "function _csReturn()")
check("C3 the label lists the queue even while a background command runs",
      'if (q) parts.push(q + " waiting to send");' in LBL
      and 'if (bg !== "nothing running") parts.push(bg);' in LBL and 'parts.join(" \\u00b7 ")' in LBL)
check("C4 every repaint of the queue repaints the badge",
      "_csPaint();   // ROUND 180/181: the strip follows the queue" in UI
      and 'async function _loadBgJobs() {' in UI and "_csPaint();   // label + the count on the bg icon" in UI)

# ---- D: meanings + many items -------------------------------------------
check("D1 steer posts the message into the RUNNING turn (no new turn)",
      'api("POST", "/api/chat/steer", { session: sessionId, message: _rawMsg })' in UI
      and 'who("user", "\U0001f3af steer: " + raw + _attNote);' in UI)
check("D2 queue keeps the raw text + the attachment snapshot and accumulates",
      "_q().push(m);" in UI and "function enqueueMsg(m)" in UI
      and "const q = _q(s);" in fn(UI, "flushQueue"))
check("D3 the flush sends ONE item and leaves the rest waiting (Trae accepts many)",
      "const it = _qNorm(q.shift()); _qSave(s); renderQueue();" in UI)
check("D4 a command is never steered: it waits for the next turn",
      "// Commands are therefore always QUEUED: the next turn applies them." in UI)

print("\n---\nv1264: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
