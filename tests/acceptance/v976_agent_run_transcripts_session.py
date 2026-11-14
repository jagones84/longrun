#!/usr/bin/env python3
"""v976 — a session-scoped `GET /api/agent/run` transcripts into ITS session.

2026-11-14 (operator): two `v66-consumer-longrun` sessions sat EMPTY in the WebUI
while a real tool run (76 tool calls) was working in them. The GET route read
`session=` only to resolve the WORKSPACE and dropped the session object, so the
visibility path that already exists for `POST /api/agent/run/stream` (JAG-476/479:
goal = user turn, outcome = reply, chat.run/chat.done bracket) never ran.

Deterministic: the run worker is stubbed, so no provider/model is contacted.
Isolated: throwaway LONGRUN_* dirs.

Run: python3 tests/acceptance/v976_agent_run_transcripts_session.py
"""
import io
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v976-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402

RESULTS = []
CALLS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class _WFile(io.BytesIO):
    def flush(self):
        pass


class _Conn:
    def setsockopt(self, *a):
        pass

    def shutdown(self, *a):
        pass


class FakeHandler:
    """Minimal stand-in for the HTTP handler used by the SSE writer."""

    def __init__(self):
        self.wfile = _WFile()
        self.connection = _Conn()
        self.close_connection = False
        self.resp_code = None
        self.headers = []
        self.sent = None

    def send_response(self, code):
        self.resp_code = code

    def send_header(self, k, v):
        self.headers.append((k, v))

    def end_headers(self):
        pass

    def _send(self, code, obj):
        self.sent = (code, obj)


def _scripted_run(goal, max_steps=6, model=None, on_event=None, script=None,
                  run_id=None, workspace=None, fallbacks=None, token_budget=None,
                  session=None):
    CALLS.append({"goal": goal, "model": model, "run_id": run_id, "session": session})
    on_event("agent.start", run=run_id, goal=goal, max_steps=max_steps)
    on_event("agent.finish", run=run_id, summary="scripted done", termination="completed")
    return {"run_id": run_id, "goal": goal, "model": model, "status": "done",
            "termination": "completed", "summary": "scripted done", "trace": [], "prm": None}


def _get_run(sid, goal="do the v66 rehearsal", model="openrouter:z-ai/glm-5.3-flash"):
    qs = {"goal": goal, "max_steps": "1", "model": model}
    if sid:
        qs["session"] = sid
    h = FakeHandler()
    API.handle(h, "GET", "/api/agent/run", qs, None)
    return h, h.wfile.getvalue().decode("utf-8", "replace")


_ORIG_RUN = API.agent_run_v2
API.agent_run_v2 = _scripted_run
try:
    sess = STORES.get_or_create_session(None, "v976 consumer")
    sid = sess["id"]
    h, raw = _get_run(sid, goal="do the v66 rehearsal")

    # --- 1: the run is BOUND to the session (billing + a session-scoped Stop) ----
    check("A1 the route hands the session to the run",
          bool(CALLS) and CALLS[-1].get("session") == sid,
          "session=%r" % (CALLS[-1].get("session") if CALLS else None))

    # --- 2: the goal becomes the user turn, the outcome the reply ---------------
    sd = STORES.load_session(sid) or {}
    msgs = sd.get("messages") or []
    check("A2 the session carries the goal as its user turn",
          len(msgs) >= 1 and msgs[0].get("role") == "user"
          and msgs[0].get("content") == "do the v66 rehearsal",
          [(m.get("role"), (m.get("content") or "")[:30]) for m in msgs])
    check("A3 the session carries the run's outcome as its reply",
          len(msgs) >= 2 and msgs[-1].get("role") == "assistant"
          and msgs[-1].get("content") == "scripted done",
          [(m.get("role"), (m.get("content") or "")[:30]) for m in msgs])

    # --- 3: JAG-478 — the run and its session share ONE model -------------------
    check("A4 the session records the model the run actually used",
          str(sd.get("model") or "") == "openrouter:z-ai/glm-5.3-flash",
          sd.get("model"))

    # --- 4: the SSE vocabulary is unchanged (run … done) ------------------------
    names = [line[6:].strip() for line in raw.split("\n") if line.startswith("event:")]
    check("A5 the stream still opens with `run` and ends with `done`",
          bool(names) and names[0] == "run" and names[-1] == "done", names)

    # --- 5: a run with NO session keeps its old meaning (nothing written) ------
    before = len(STORES.list_sessions())
    h2, _ = _get_run(None)
    check("A6 a run without a session writes no transcript",
          len(STORES.list_sessions()) == before and CALLS[-1].get("session") is None,
          "sessions=%d session=%r" % (len(STORES.list_sessions()), CALLS[-1].get("session")))
finally:
    API.agent_run_v2 = _ORIG_RUN

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
