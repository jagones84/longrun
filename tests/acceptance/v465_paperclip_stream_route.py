#!/usr/bin/env python3
"""v465 — `POST /api/agent/run/stream`: JSON body in, SSE out (Paperclip Task 2).

The Paperclip adapter must start one agent run with the goal in the REQUEST BODY:
`GET /api/agent/run` carries it in the query string, which a task goal cannot
(URL length, escaping, and secrets-in-URL). This route keeps the existing SSE
vocabulary of the GET route and adds the Task 1 terminal classification.

Deterministic: the run worker is stubbed, so no provider/model is contacted.
Isolated: throwaway LONGRUN_* dirs.

Run: python3 tests/acceptance/v465_paperclip_stream_route.py
"""
import io
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v465-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402

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


def parse_sse(text):
    out, ev, data = [], None, []
    for line in text.split("\n"):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and ev:
            out.append((ev, "\n".join(data)))
            ev, data = None, []
    return out


def post_stream(body):
    h = FakeHandler()
    API.handle(h, "POST", "/api/agent/run/stream", {}, body)
    return h


# --- stubbed run worker: emits a start, a progress and a terminal event ------
def _scripted_run(goal, max_steps=6, model=None, on_event=None, script=None,
                  run_id=None, workspace=None, fallbacks=None):
    CALLS.append({"goal": goal, "max_steps": max_steps, "model": model,
                  "run_id": run_id})
    on_event("agent.start", run=run_id, goal=goal, max_steps=max_steps)
    on_event("agent.iteration", run=run_id, i=1, of=max_steps)
    st = API.run_get(run_id)
    if st is not None:
        st.status, st.termination, st.summary = "done", "completed", "scripted done"
    on_event("agent.finish", run=run_id, summary="scripted done", termination="completed")
    return {"run_id": run_id, "goal": goal, "model": model, "status": "done",
            "termination": "completed", "summary": "scripted done", "trace": [], "prm": None}


_ORIG_RUN = API.agent_run_v2
API.agent_run_v2 = _scripted_run
try:
    # --- 1: a JSON goal is accepted and streamed ------------------------------
    h = post_stream({"goal": "summarize the repo", "max_steps": 2})
    raw = h.wfile.getvalue().decode("utf-8", "replace")
    frames = parse_sse(raw)
    check("test_post_stream_accepts_json_goal",
          h.sent is None and h.resp_code == 200
          and ("Content-Type", "text/event-stream") in h.headers
          and bool(frames) and frames[0][0] == "run",
          "code=%s frames=%s" % (h.resp_code, [e for e, _ in frames]))

    # --- 2: ordered run → progress → terminal → done --------------------------
    import json as _json
    names = [e for e, _ in frames]
    finish = [d for e, d in frames if e == "agent.finish"]
    it_idx = names.index("agent.iteration") if "agent.iteration" in names else -1
    fin_idx = names.index("agent.finish") if "agent.finish" in names else -1
    term = _json.loads(finish[0]).get("termination") if finish else None
    check("test_post_stream_emits_run_progress_terminal_and_done",
          names and names[0] == "run" and names[-1] == "done"
          and it_idx > 0 and fin_idx > it_idx and term == "completed"
          and CALLS and CALLS[-1]["max_steps"] == 2
          and CALLS[-1]["run_id"] == _json.loads(frames[0][1])["run_id"],
          "names=%s term=%s" % (names, term))

    # --- 3: invalid goals and run settings are rejected before any run --------
    before = len(CALLS)
    cases = [
        ({}, "missing goal"),
        ({"goal": ""}, "empty goal"),
        ({"goal": 123}, "non-string goal"),
        ({"goal": "x", "max_steps": "abc"}, "non-int max_steps"),
        ({"goal": "x", "max_steps": 0}, "zero max_steps"),
        ({"goal": "x", "session": 5}, "non-string session"),
    ]
    bad = []
    for body, label in cases:
        h2 = post_stream(body)
        if not (h2.sent and h2.sent[0] == 400 and h2.sent[1].get("error")):
            bad.append("%s -> %s" % (label, h2.sent))
    check("test_post_stream_rejects_invalid_goal",
          not bad and len(CALLS) == before, "; ".join(bad))
finally:
    API.agent_run_v2 = _ORIG_RUN

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
