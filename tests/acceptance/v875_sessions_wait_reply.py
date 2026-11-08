#!/usr/bin/env python3
"""v875 — ONE reader for a session: `sessions.wait` agrees with `turn_reply`.

Measured live 2026-11-08 on a dispatched turn: the same session answered
`Result computed` through `stores.turn_reply` (the finish envelope) and the raw
marker through `sessions.wait` (which took `replies[-1]`). A finish followed by a
closure-gate round therefore handed the CALLER the round, not the result.

A1 a turn closed by an explicit finish answers with the FINISH summary
A2 the message AFTER the finish does not win
A3 a turn with no finish envelope still answers with its last reply

Run: python3 tests/acceptance/v875_sessions_wait_reply.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v875-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server             # noqa: E402
from longrun.memory import stores           # noqa: E402
from longrun.tools import tools as T        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


FINISH = '{"action":"finish","summary":"Result computed"}'
TAIL = "A49-R1-7k3vq"


def wait_once(messages):
    """Drive `sessions.wait` over one pending message and return its reply."""
    sess = {"id": "S-v875", "messages": messages}
    _orig = server.load_session
    server.load_session = lambda sid: sess
    server._ACTIVE_CHAT.pop("S-v875", None)
    T._SESSION_SENDS["m-v875"] = {
        "message_id": "m-v875", "session": "S-v875", "before_messages": 1,
        "state": "running", "active_token": "tok-v875", "mode": "chat"}
    try:
        out = T._sessions({"action": "wait", "message_id": "m-v875",
                           "timeout_secs": 1}, None)
    finally:
        server.load_session = _orig
        T._SESSION_SENDS.pop("m-v875", None)
    return out


turn = [{"role": "user", "content": "go"},
        {"role": "assistant", "content": FINISH},
        {"role": "assistant", "content": TAIL}]
out = wait_once(turn)
check("A1 a turn closed by an explicit finish answers with the FINISH summary",
      out.get("reply") == "Result computed",
      "reply=%r (turn_reply=%r)" % (out.get("reply"), stores.turn_reply(turn)))
check("A2 the message AFTER the finish does not win",
      TAIL not in str(out.get("reply")), out.get("reply"))
check("A2b the stdout carries the same reply", "Result computed" in (out.get("stdout") or ""),
      out.get("stdout"))

plain = [{"role": "user", "content": "go"},
         {"role": "assistant", "content": "first draft"},
         {"role": "assistant", "content": "final answer"}]
out2 = wait_once(plain)
check("A3 a turn with no finish envelope still answers with its last reply",
      out2.get("reply") == "final answer", out2.get("reply"))

print("---")
okc = sum(results)
print("\nv875: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
