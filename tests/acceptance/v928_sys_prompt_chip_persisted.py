#!/usr/bin/env python3
"""v928 — the system-prompt chip is deduped by the SESSION, not by process memory.

The operator asked why a later user message shows the system prompt again when
nothing was compacted and nothing was reset. Measured 2026-11-10 on the live event
log: the chip only fires when the prompt text CHANGES (45 of 63 changes were a
memory line), but the dedupe state lived in a module map (`_LAST_SYS_INJECT`) that
is empty after every restart — session 55a29fae70cb published the SAME digest at
19:29:33, 19:30:36 and 19:31:48 across two restarts at 19:29:44 and 19:31:00.

The fix keeps the display rule (one chip, only on change, verbatim text) and moves
its state onto the session record, so it survives a save/load cycle:

  A) the guard itself: first turn publishes, an unchanged prompt is silent;
  B) the digest is stable (SHA-1 of the sent text — `hash()` is salted per process
     and could never match after a restart) and it round-trips through the store;
  C) one truth: the module map is gone and `chat_once` delegates to the helper;
  D) nothing else changes: the prompt is still sent every turn (stateless API) and
     the chip is still transient (never persisted into the transcript).

Deterministic, no live model, no network, no server.
"""
import hashlib
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v928-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []
SID = "928a7c1d0e44"
PROMPT = "You are Longrun.\n\n## Rules\n- be useful"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _src():
    with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
              encoding="utf-8") as fh:
        return fh.read()


events = []


def emit(name, **kw):
    events.append((name, kw))


def wire(text):
    return [{"role": "system", "content": text},
            {"role": "user", "content": "hello"}]


# ---- A. the guard -----------------------------------------------------------
sess = {"id": SID, "messages": [], "created": 1.0}
check("A1 the FIRST turn publishes the prompt",
      agent.publish_system_prompt(sess, wire(PROMPT), emit) is True and len(events) == 1)
check("A2 an UNCHANGED prompt is NOT re-published",
      agent.publish_system_prompt(sess, wire(PROMPT), emit) is False and len(events) == 1)
check("A3 the chip carries the text VERBATIM, as a system message",
      events[0][0] == "harness.inject" and events[0][1].get("text") == PROMPT
      and events[0][1].get("role") == "system"
      and events[0][1].get("inject_kind") == "system",
      events[0][1] if events else "no event")

# ---- B. the digest is stable and survives a restart -------------------------
check("B1 the digest is stored ON THE SESSION",
      isinstance(sess.get("sys_prompt_hash"), str) and len(sess["sys_prompt_hash"]) == 40,
      repr(sess.get("sys_prompt_hash")))
check("B2 it is the SHA-1 of the SENT text (stable across processes, not hash())",
      sess.get("sys_prompt_hash") == hashlib.sha1(PROMPT.encode("utf-8")).hexdigest())

server.save_session(sess)
loaded = server.load_session(SID)
check("B3 the session record round-trips the field",
      bool(loaded) and loaded.get("sys_prompt_hash") == sess["sys_prompt_hash"],
      (loaded or {}).get("sys_prompt_hash"))

events.clear()
check("B4 after a RESTART an unchanged prompt stays silent (the whole point)",
      agent.publish_system_prompt(loaded, wire(PROMPT), emit) is False and not events)
check("B5 a CHANGED prompt publishes again",
      agent.publish_system_prompt(loaded, wire(PROMPT + "\n- one more rule"), emit) is True
      and len(events) == 1)
check("B6 the new digest replaces the old one",
      loaded.get("sys_prompt_hash") == hashlib.sha1(
          (PROMPT + "\n- one more rule").encode("utf-8")).hexdigest())

# ---- C. one truth ----------------------------------------------------------
check("C1 the module map is GONE", not hasattr(agent, "_LAST_SYS_INJECT"))
_src = _src()
check("C2 chat_once delegates to the helper",
      "publish_system_prompt(sess, msgs, on_event)" in _src)
check("C3 no other module still imports the removed map",
      all("_LAST_SYS_INJECT" not in open(os.path.join(REPO, "src", "longrun", p),
                                         encoding="utf-8").read()
          for p in ("core/server.py", "memory/stores.py")))

# ---- D. what must NOT change ------------------------------------------------
check("D1 the chip is still TRANSIENT (never persisted into the transcript)",
      'if kind != "system" and persist' in _src)
check("D2 a missing/foreign message list never raises",
      agent.publish_system_prompt(loaded, [], emit) is False
      and agent.publish_system_prompt(loaded, [{"role": "user", "content": "x"}], emit) is False
      and agent.publish_system_prompt({}, wire(PROMPT), emit) is True)
check("D3 a broken on_event never breaks the turn",
      agent.publish_system_prompt({"id": "s3"}, wire("other prompt"),
                                  lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
      is False)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
