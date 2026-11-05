#!/usr/bin/env python3
"""v807 — a finished background job announces itself (2026-11-05).

Operator: *"1. Yes."* — answering "a background job that finishes should
announce itself in the session instead of waiting to be polled", plus
*"i don't want automatic human in the loop or agent calling humans if not
strictly necessary"* (the strict `human.ask` question, pinned here too).

  A  `announce(sid)` hands a finished job over exactly ONCE, with its exit code
     and the tail of its output;
  B  `describe()` is the ONE text both the transcript copy and the model's
     observation use;
  C  a job with no session is never announced to anybody;
  D  the chat loop injects the notice as an observation and does not write a
     second transcript copy when the watcher already did;
  E  the shell tool hands the session to the job (otherwise nobody to tell);
  F  the strict question rule: a card needs a '?' and three words of decision.

Deterministic: real short processes, temp data dir, no model, no network.
Run: python3 tests/acceptance/v807_bgjob_announce.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v807-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order: agent needs it)
from longrun.tools import bgjobs, tools as T  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
TOOLS_SRC = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def wait_finished(sid, secs=8.0):
    """Poll `announce` until the job shows up (the watcher is a thread)."""
    end = time.time() + secs
    while time.time() < end:
        got = bgjobs.announce(sid)
        if got:
            return got
        time.sleep(0.1)
    return []


# ---- A: the notice is handed over once -----------------------------------
SID = "sess-v807-a"
st = bgjobs.start("echo hello-from-the-job", session=SID)
check("A1 the job started", st.get("ok") is True and bool(st.get("job")), st)
_got = wait_finished(SID)
check("A2 the finished job is announced", len(_got) == 1, _got)
check("A3 the notice carries the exit code and the command",
      _got and _got[0].get("exit_code") == 0
      and "echo hello-from-the-job" in str(_got[0].get("command")), _got)
check("A4 the notice carries the tail of its output",
      _got and "hello-from-the-job" in str(_got[0].get("tail")), _got)
check("A5 it is announced ONCE (the second read is empty)",
      bgjobs.announce(SID) == [])
check("A6 another session hears nothing", bgjobs.announce("some-other-session") == [])

# ---- B: one text shape for the transcript and the model ------------------
_text = bgjobs.describe(_got) if _got else ""
check("B1 the text says it FINISHED with the exit code",
      "FINISHED exit=0" in _text, _text)
check("B2 the text names the job", bool(_got) and str(_got[0].get("job")) in _text)
check("B3 the text carries the command", "echo hello-from-the-job" in _text)
check("B4 the text carries the output tail", "hello-from-the-job" in _text)

# ---- C: nobody to announce to -------------------------------------------
_anon = bgjobs.start("echo anonymous")
_anon_job = str(_anon.get("job") or "")
_c = bgjobs.announce("")
check("C1 an empty session id announces nothing", _c == [], _c)
check("C2 a job with no session is never returned for any session",
      bgjobs.announce(SID) == [])
rec = bgjobs._JOBS.get(_anon_job) or {}
check("C3 the session-less job is still tracked (status works)",
      bool(rec) and rec.get("session") == "", rec.get("session"))

# ---- D: the loop seam ----------------------------------------------------
check("D1 the loop asks the module what finished",
      'from longrun.tools import bgjobs as _bgj' in SRC
      and '_bgj.announce(sess["id"])' in SRC)
check("D2 the loop injects it as an observation",
      '_bgj.describe([_bj])' in SRC and '"observation"' in SRC)
check("D3 the loop does not duplicate a transcript copy",
      'persist=not _bj.get("persisted")' in SRC)
check("D4 _inject accepts the flag", "def _inject(content, kind, persist=True):" in SRC)
check("D5 the flag actually guards the write",
      'if kind != "system" and persist:' in SRC)
check("D6 the announce runs before the model call",
      SRC.find("_bgj.announce(sess[\"id\"])") < SRC.find("collected = []", SRC.find("_bgj.announce")))

# ---- E: the shell tool passes the session --------------------------------
check("E1 the shell tool hands the session to the job",
      "bgjobs.start(command, cwd=cwd or os.getcwd(), session=sid)" in TOOLS_SRC)

# ---- the idle path: the watcher writes the transcript copy --------------
_calls = []
_orig_persist = bgjobs._persist
_orig_active = bgjobs._turn_active
try:
    bgjobs._persist = lambda sid, text: (_calls.append((sid, text)) or True)
    bgjobs._turn_active = lambda sid: False
    _idle = bgjobs.start("echo idle-notice", session="sess-v807-idle")
    _idle_job = str(_idle.get("job") or "")
    _end = time.time() + 8
    while time.time() < _end and not _calls:
        time.sleep(0.1)
    check("F1 with no turn running the notice is written to the transcript",
          bool(_calls) and _calls[0][0] == "sess-v807-idle", _calls)
    check("F2 the written text is the same shape as the model's observation",
          bool(_calls) and "FINISHED" in _calls[0][1]
          and _idle_job in _calls[0][1], _calls)
    _idle_got = bgjobs.announce("sess-v807-idle")
    check("F3 the model still hears it (with the transcript copy flagged)",
          bool(_idle_got) and _idle_got[0].get("persisted") is True, _idle_got)

    _calls2 = []
    bgjobs._persist = lambda sid, text: (_calls2.append((sid, text)) or True)
    bgjobs._turn_active = lambda sid: True     # a turn IS running
    bgjobs.start("echo live-notice", session="sess-v807-live")
    time.sleep(1.5)
    check("F4 with a turn running the watcher stays silent (the loop injects)",
          _calls2 == [], _calls2)
finally:
    bgjobs._persist = _orig_persist
    bgjobs._turn_active = _orig_active

# ---- G: the strict question rule (operator: only a real need) -----------
for bad in ("Continue?", "Proceed?", "Which one?", "placeholder", "Apply it now"):
    check("G1 refused: %r" % bad, bool(T.human_question_problem(bad)), bad)
for good in ("Which branch should the release cut from?",
             "Apply the migration to production now?"):
    check("G2 accepted: %r" % good, T.human_question_problem(good) == "", good)
check("G3 the refusal text tells the model what is missing",
      "no '?'" in T.human_question_problem("Apply the migration now")
      and "too short" in T.human_question_problem("Continue?"))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
