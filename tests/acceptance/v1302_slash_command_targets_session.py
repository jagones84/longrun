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
  E  `/reset` RESETS the chat it is typed in (same session id: `POST
     /api/sessions/<sid>/clear`), and never creates another session; the old
     "fresh chat" verb is `/new`, which names the source session as untouched;
  F  `/plan` and `/spec` post the captured id too.

No model, no network, no server.

Run: python3 tests/acceptance/v1302_slash_command_targets_session.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
SW = open(os.path.join(REPO, "webui", "sw.js"), encoding="utf-8").read()
SRV = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()

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
NEW = _between("async function newChat(sid) {", "\n/* `/reset`: reset the chat it is typed in")
COMPACT = _between("async function compactNow(sid) {", "\nasync function docBarPaint")
UNLOCK = _between("async function docUnlock(sid) {", "\nasync function goalAct")
STATUS = _between("async function openSessionStatus(sid) {", "\n/* 2026-11-22 (operator): `/context`")
CTX = _between("async function openContextDetails(sid) {", "\n/* 2026-11-22 (operator): `/restart`")
DOC = _between("async function _runDocCommand(kind, ask, sid) {", "\nasync function docBarPaint")
GUARD = _between("function _commandTarget(sid, label) {", "\n}")

_FN = {"compact": "compactNow", "status": "openSessionStatus", "reset": "resetChat",
       "new": "newChat", "unlock": "docUnlock", "context": "openContextDetails"}

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
check("D4 /reset re-checks the target after the wipe",
      "if (S !== sessionId)" in RESET)
check("D5 /status and /context do not render after a switch",
      "if (S !== sessionId) return;" in STATUS and "if (S !== sessionId) return;" in CTX)

# ---- E: /reset RESETS the same chat; /new is the fresh-chat verb ------------
check("E1 /reset wipes the SAME session (the harness's own `sessions.reset`)",
      '"/api/sessions/" + encodeURIComponent(S) + "/clear"' in RESET)
check("E2 /reset never creates another session",
      "createSession(" not in RESET and "createSession(" in NEW)
check("E3 /reset does not repaint a view the operator left",
      "if (S !== sessionId)" in RESET and "transcript and plan cleared" in RESET)
check("E4 /new names the workspace and the untouched source session",
      "was not touched" in NEW and '"GET", "/api/workspace?session="' in NEW)
check("E5 the two verbs are distinct in BOTH tables (one verb, one meaning)",
      'id: "new"' in FALLBACK and 'id: "reset"' in FALLBACK
      and "new: (sid) => newChat(sid)" in RUNMAP
      and "reset: (sid) => resetChat(sid)" in RUNMAP)

# ---- F: the document commands post the captured id --------------------------
check("F1 /plan and /spec post the captured session",
      "session: S" in DOC and "prompt: ask" in DOC,
      [ln for ln in DOC.splitlines() if "session" in ln][:3])
check("F2 send() hands the captured id to the document command",
      "_runDocCommand(_docKind, _docAsk, _cmdSid)" in SEND)

# ---- H: /restart really comes back, and a turn keeps its captured session ----
RESTART = _between("async function restartService(sid) {", "\n/* ---- approvals")
check("H1 /restart waits for the service to go down and to answer again",
      '"GET", "/api/build"' in RESTART and "location.reload()" in RESTART)
check("H2 /restart never calls a function that does not exist",
      "feedReconnect" not in HTML)
check("H3 a message (and `/goal`) runs in the chat it was typed in",
      "let turnSession = _cmdSid || sessionId;" in HTML
      and "_pendingUserAdd(turnSession," in HTML)
# 2026-11-25 (operator: *"non sembra succedere nulla con slash restart, neanche un
# messaggio in webui che accerti che il restart command e stato effettivamente mandato
# e recepito nella chat"*): a toast is erased by the reload, so a WORKING restart used
# to look like a dead command. The command and the service's answer must be transcript
# rows, written in the capped session, before the request leaves.
check("H4 /restart is declared with the captured session in BOTH tables",
      "run: (sid) => restartService(sid)" in FALLBACK
      and "restart: (sid) => restartService(sid)" in RUNMAP)
check("H5 the command appears in the chat as a row, not only as a toast",
      'who("user", "/restart")' in RESTART, RESTART[:200])
check("H6 the service's answer appears in the chat (accepted / refused / not delivered)",
      "restart **accepted**" in RESTART and "restart **refused**" in RESTART
      and "restart **not delivered**" in RESTART)
check("H7 the rows are written only in the chat the command was typed in",
      "const _here = !!_sid && _sid === sessionId;" in RESTART
      and "if (_here) who(" in RESTART)
check("H8 both failure ends leave a row too (timeout / same process)",
      "did not come back within 60 s" in RESTART
      and "the SAME process (started" in RESTART)
# 2026-11-25 (operator's screenshot: "restart accepted" then "still the OLD process"
# while journalctl showed the unit started at 04:15:18): a ~3 s downtime is invisible
# to a polled timer, so the proof must be the PROCESS IDENTITY, not a caught refusal.
check("H9 the restart is proven by the answering process's identity",
      '"started_at": _started' in SRV
      and 'typeof b.started_at === "number"' in RESTART
      and "if (b > _boot0 + 1) { _reloadNow(); return; }" in RESTART)
check("H10 the baseline is read BEFORE the restart is requested",
      RESTART.find('_bootOf(await api("GET", "/api/build"))')
      >= 0
      and RESTART.find('_bootOf(await api("GET", "/api/build"))')
      < RESTART.find('action: "restart"'))
check("H11 the reload keeps a marker only for a NEW process, and boot turns it into a chip",
      'localStorage.setItem("lr_restart_at"' in RESTART
      and RESTART.find('localStorage.setItem("lr_restart_at"')
      < RESTART.find("location.reload();")
      and 'localStorage.getItem("lr_restart_at"' in _between("function _restartArrival() {",
                                                            "\nfunction _offerReload() {")
      and "10 * 60 * 1000" in _between("function _restartArrival() {",
                                       "\nfunction _offerReload() {")
      and "_restartArrival();" in HTML)

# ---- G: the offline shell follows (a cached old composer is a stale contract) --
check("G1 the service-worker cache is DERIVED from the served build (no hand-bump)",
      'const SHELL_VERSION = "__SHELL_VERSION__";' in SW
      and 'const CACHE = "longrun-shell-" +' in SW)

print("---")
ok = sum(results)
print("v1302: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
