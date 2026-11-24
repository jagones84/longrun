#!/usr/bin/env python3
"""v1302 — a `/` command belongs to the session it was TYPED in.

Operator (2026-11-24): *"se eseguo un comando in una chat session per esempio /reset …
me lo fa in un'altra … nella architect chat … me lo ha fatto nella chat che avevo
selezionato PRIMA … il comando viene redirezionato ad un altra sessione."*

Contract locked here (static, because a `/` command is a composer action):
  A  `send()` captures the session ONCE (`_cmdSid`) before any await;
  B  a trailing space no longer turns `/reset ` into prose for the MODEL (which is how a
     token could reach a session tool and act on another chat);
  C  every session-scoped `/` command receives that id in BOTH tables — the first-paint
     fallback AND `_SLASH_RUN` re-attached after the backend catalogue;
  D  ONE guard (`_commandTarget`) refuses when the screen moved on, and each async
     action re-checks it after its await (no retarget, no wiping another view);
  E  `/reset` says where it went and that a stateless session (Architect) is not reset —
     it opens a NEW chat in that session's workspace;
  F  `/plan` and `/spec` post the captured id too.

No model, no network, no server.

Run: python3 tests/acceptance/v1302_slash_command_targets_session.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
SW = open(os.path.join(REPO, "webui", "sw.js"), encoding="utf-8").read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(extra)[:300]) if extra else ""))


def _between(start, end, src=HTML):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:j if j >= 0 else len(src)]


SEND = _between("async function send(text, display, atts) {", "\n  let msg = raw;")
FALLBACK = _between("let SLASH_COMMANDS = [", "\nconst SLASH_BY_ID")
RUNMAP = _between("const _SLASH_RUN = {", "\n};")
RESET = _between("async function resetChat(sid) {", "\n/* JAG-121:")
COMPACT = _between("async function compactNow(sid) {", "\nasync function docBarPaint")
UNLOCK = _between("async function docUnlock(sid) {", "\nasync function goalAct")
STATUS = _between("async function openSessionStatus(sid) {", "\n/* 2026-11-22 (operator): `/context`")
CTX = _between("async function openContextDetails(sid) {", "\n/* 2026-11-22 (operator): `/restart`")
DOC = _between("async function _runDocCommand(kind, ask, sid) {", "\nasync function docBarPaint")
GUARD = _between("function _commandTarget(sid, label) {", "\n}")

_FN = {"compact": "compactNow", "status": "openSessionStatus", "reset": "resetChat",
       "unlock": "docUnlock", "context": "openContextDetails"}

# ---- A: the session is captured once, before any await ----------------------
check("A1 send() captures the session the command was typed in",
      "const _cmdSid = sessionId;" in SEND, SEND[:200])
check("A2 the capture happens before the first await",
      SEND.find("const _cmdSid = sessionId;") >= 0
      and SEND.find("const _cmdSid = sessionId;") < SEND.find("await "))

# ---- B: trailing whitespace is still the command ----------------------------
check("B1 the solo-command match tolerates trailing whitespace",
      "/^\\/([A-Za-z0-9_.\\-]+)\\s*$/" in SEND,
      [ln for ln in SEND.splitlines() if "_solo =" in ln][:2])
check("B2 the action receives the captured id, not the global",
      "_c.run(_cmdSid)" in SEND, [ln for ln in SEND.splitlines() if "_c.run" in ln][:2])

# ---- C: every session command is declared with the id, in BOTH tables -------
for cid, fn in _FN.items():
    check("C1 the fallback declares /%s with the captured session" % cid,
          ('run: (sid) => %s(sid)' % fn) in FALLBACK, FALLBACK[:120])
    check("C2 the catalogue re-attaches /%s with the captured session" % cid,
          ("%s: (sid) => %s(sid)" % (cid, fn)) in RUNMAP, RUNMAP[:160])
check("C3 no session command closes over the global any more",
      "run: () => resetChat()" not in FALLBACK
      and "run: () => compactNow()" not in FALLBACK
      and "reset: () => resetChat()" not in RUNMAP)

# ---- D: one guard, and the async actions re-check it ------------------------
check("D1 the guard refuses when the screen moved on",
      "S !== sessionId" in GUARD and "cancelled" in GUARD, GUARD[:200])
for label, body in (("compact", COMPACT), ("unlock", UNLOCK),
                    ("status", STATUS), ("context", CTX), ("reset", RESET)):
    check("D2 /%s resolves its target through the guard" % label,
          '_commandTarget(sid, "%s")' % label in body, body[:160])
check("D3 compaction never wipes another session's view",
      "if (S !== sessionId) return;" in COMPACT)
check("D4 /reset re-checks the target after the workspace read",
      "if (S !== sessionId)" in RESET)
check("D5 /status and /context do not render after a switch",
      "if (S !== sessionId) return;" in STATUS and "if (S !== sessionId) return;" in CTX)

# ---- E: /reset says where it went, and what a stateless session is ----------
check("E1 /reset names the workspace and the untouched source session",
      "was not touched" in RESET and '"GET", "/api/workspace?session="' in RESET)
check("E2 /reset states the Architect session is stateless",
      "stateless" in RESET and "Architect" in RESET and "_isSystemSess" in RESET)

# ---- F: the document commands post the captured id --------------------------
check("F1 /plan and /spec post the captured session",
      "session: S" in DOC and "prompt: ask" in DOC,
      [ln for ln in DOC.splitlines() if "session" in ln][:3])
check("F2 send() hands the captured id to the document command",
      "_runDocCommand(_docKind, _docAsk, _cmdSid)" in SEND)

# ---- G: the offline shell follows (a cached old composer is a stale contract) --
check("G1 the service-worker cache was bumped for this shell change",
      'longrun-shell-v14' in SW)

print("---")
ok = sum(results)
print("v1302: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
