#!/usr/bin/env python3
"""v938 — a turn interrupted by a RESTART is resumed, a stopped one is not.

Operator: *"dopo un hard restart da systemd l'harness dovrebbe capire che è stato
fatto il restart e inviare messaggi alle sessioni bloccate dal restart che stavano
in RUN … (solo per restart, no per chiusura)."*

`core/inflight.py` mirrors the running turns to disk at every turn_begin/turn_end
and, on boot, hands a continuation message to each session whose turn never ended
— but ONLY when the previous exit was a restart:

  * no stop marker  -> crash / kill -9           -> resume
  * fresh marker    -> systemctl restart          -> resume
  * old marker      -> operator stop, later start -> DO NOT resume

Deterministic: no model, no network, no server (load/active/deliver injected).

Run: python3 tests/acceptance/v938_restart_resume_inflight.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v938-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import inflight as I  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _reset():
    I.clear()
    try:
        os.remove(I.STOP_MARK)
    except OSError:
        pass


def _sess(interrupted=True, matrix=False):
    msgs = [{"role": "user", "content": "do the thing"}]
    if matrix:
        msgs.append({"role": "user", "content": "continue",
                     "meta": {"matrix_continuation": True}})
    s = {"messages": msgs}
    if interrupted:
        s["interrupted"] = {"effect": "unknown_effect", "executed": 1}
    return s


def _run(sessions, window=60, maxn=10):
    calls = []

    def deliver(sid, text):
        calls.append((sid, text))
        return {"ok": True, "mode": "turn"}

    rep = I.recover(window, maxn, load=lambda sid: sessions.get(sid),
                    active=lambda sid: False, deliver=deliver)
    return rep, calls


# --- A) the real-time file ------------------------------------------------
_reset()
tok = object()
I.begin("s-a", tok)
check("A1 an in-flight turn is on disk", "s-a" in I.snapshot(), I.snapshot())
I.end("s-a", object())
check("A2 an OLDER turn's end does not erase a newer record", "s-a" in I.snapshot())
I.end("s-a", tok)
check("A3 the owning turn's end removes it", I.snapshot() == {}, I.snapshot())

# --- B) the event bracket is wired ----------------------------------------
from longrun.core import events as E  # noqa: E402

tok2 = E.turn_begin("s-wire")
check("B1 turn_begin writes the durable mirror", "s-wire" in I.snapshot(), I.snapshot())
E.turn_end("s-wire", tok2)
check("B2 turn_end clears it", I.snapshot() == {}, I.snapshot())

# --- C) crash (no marker) resumes -----------------------------------------
_reset()
I.begin("s-crash", object())
rep, calls = _run({"s-crash": _sess()})
check("C1 a crash-resumed turn is delivered", rep["resumed"] == ["s-crash"], rep)
check("C2 the message says restart and asks to continue",
      calls and "[Harness restart]" in calls[0][1] and "Continue" in calls[0][1], calls)
check("C3 the record is cleared after recovery", I.snapshot() == {})

# --- D) a FRESH marker is a restart: resume -------------------------------
_reset()
I.begin("s-restart", object())
I.note_stop("signal:15")
rep, calls = _run({"s-restart": _sess()}, window=60)
check("D1 systemctl restart (fresh marker) resumes", rep["resumed"] == ["s-restart"], rep)
check("D2 it is not reported as a deliberate stop", rep["stopped"] is False, rep)

# --- E) an OLD marker is a closure: do not resume -------------------------
_reset()
I.begin("s-stopped", object())
I._write(I.STOP_MARK, {"ts": time.time() - 600, "pid": 1, "reason": "stop"})
rep, calls = _run({"s-stopped": _sess()}, window=60)
check("E1 an operator stop followed by a later start is NOT resumed",
      rep["stopped"] is True and rep["resumed"] == [] and calls == [], rep)
check("E2 the record is cleared anyway", I.snapshot() == {})

# --- F) sessions that must be left alone ----------------------------------
_reset()
I.begin("s-done", object())
I.begin("s-gone", object())
I.begin("s-matrix", object())
rep, calls = _run({"s-done": _sess(interrupted=False),
                   "s-matrix": _sess(matrix=True)})
check("F1 a finished turn is not resumed",
      {"session": "s-done", "why": "no interrupted turn"} in rep["skipped"], rep)
check("F2 a deleted session is skipped",
      {"session": "s-gone", "why": "session no longer exists"} in rep["skipped"], rep)
check("F3 a Matrix continuation already in the tail is skipped",
      {"session": "s-matrix", "why": "already resumed by Matrix"} in rep["skipped"], rep)

# --- G) the cap ------------------------------------------------------------
_reset()
I.begin("s-1", object())
I.begin("s-2", object())
rep, calls = _run({"s-1": _sess(), "s-2": _sess()}, maxn=1)
check("G1 the cap resumes one and reports the other",
      len(rep["resumed"]) == 1 and any(s.get("why") == "cap reached" for s in rep["skipped"]),
      rep)

_reset()
print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
