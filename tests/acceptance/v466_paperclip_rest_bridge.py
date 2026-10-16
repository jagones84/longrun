#!/usr/bin/env python3
"""v466 — Longrun REST/SSE bridge + safe event allowlist (Paperclip Task 3).

The Python half of the Paperclip adapter. It must:
  * parse `text/event-stream` incrementally (comments, multiline data, arbitrary
    chunk boundaries, keepalives);
  * forward ONLY the five allowlisted events — never model reasoning
    (`agent.think`), raw observations, tool arguments/results, or unknown events;
  * treat a disconnect before the initial run-id frame as INDETERMINATE and
    never start a second run;
  * corroborate the streamed terminal classification against the run record;
  * abort the KNOWN run id on cancellation.

Deterministic and offline: a fake opener stands in for the network.
Isolated: throwaway LONGRUN_* dirs (imported modules read them at import time).

Run: python3 tests/acceptance/v466_paperclip_rest_bridge.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v466-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.integrations import paperclip_adapter as A  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --------------------------------------------------------------- fakes ------
class FakeResponse:
    def __init__(self, chunks=None, body=b"", status=200):
        self._chunks = list(chunks or [])
        self._body = body
        self.status = status

    def read1(self, size=-1):
        if not self._chunks:
            return b""
        item = self._chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def read(self, size=-1):
        if self._chunks:
            data = b"".join(c for c in self._chunks if not isinstance(c, BaseException))
            self._chunks = []
            return data
        data, self._body = self._body, b""
        return data

    def close(self):
        pass


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        nxt = self.responses.pop(0) if self.responses else FakeResponse()
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _invocation(**over):
    kw = {"goal": "do the assigned task", "paperclip_run_id": "pc_run_1",
          "agent_id": "agent_1", "company_id": "co_1", "task_id": "task_9",
          "max_steps": 6}
    kw.update(over)
    return A.PaperclipInvocation.from_dict(kw)


def _client(opener):
    return A.LongrunApiClient("http://127.0.0.1:8790", token="LONGRUN-SECRET-TOKEN",
                              opener=opener, timeout_sec=5)


SSE_OK = (
    "event: run\ndata: {\"run_id\": \"run_abc123\"}\n\n"
    "event: agent.start\ndata: {\"run\": \"run_abc123\", \"goal\": \"private goal\"}\n\n"
    ": ping\n\n"
    "event: agent.think\ndata: {\"channel\": \"reasoning\", \"text\": \"TOP-SECRET-COT\"}\n\n"
    "event: agent.observation\ndata: {\"observation\": \"TOP-SECRET-OBS\"}\n\n"
    "event: agent.iteration\ndata: {\"run\": \"run_abc123\", \"i\": 2, \"of\": 6}\n\n"
    "event: agent.finish\ndata: {\"run\": \"run_abc123\", \"summary\": \"did the thing\", "
    "\"termination\": \"completed\"}\n\n"
    "event: done\ndata: {}\n\n"
)
RUN_RECORD_OK = json.dumps({"id": "run_abc123", "status": "done",
                            "termination": "completed",
                            "summary": "did the thing"}).encode()

# --- 1: the SSE parser is incremental and spec-faithful ---------------------
raw = (": ping\n\n"
       "event: run\ndata: {\"a\": 1}\n\n"
       "event: multi\ndata: line one\ndata: line two\n\n"
       "event: wrapped\ndata: {\"b\":\ndata:  2}\n\n")
expected = [("run", "{\"a\": 1}"), ("multi", "line one\nline two"),
            ("wrapped", "{\"b\":\n 2}")]
ok_all = True
for cut in range(len(raw) + 1):
    dec = A.SSEDecoder()
    got = dec.push(raw[:cut]) + dec.push(raw[cut:])
    if got != expected:
        ok_all = False
        break
check("test_sse_parser_handles_comments_multiline_and_split_data",
      ok_all and len(expected) == 3, "cut=%s got=%s" % (cut if not ok_all else "-", got))

# --- 2: only allowlisted events survive the mapper --------------------------
drop = ["agent.think", "agent.observation", "agent.thought", "agent.start",
        "tool.call", "approval.auto", "checkpoint.created", "done", "error?"]
kept = [
    ("run", {}, A.EVENT_STARTED),
    ("agent.iteration", {}, A.EVENT_PROGRESS),
    ("agent.finish", {"termination": "completed"}, A.EVENT_COMPLETED),
    ("agent.finish", {"termination": "max_steps"}, A.EVENT_FAILED),
    ("agent.finish", {"termination": "no_progress"}, A.EVENT_FAILED),
    ("agent.error", {}, A.EVENT_FAILED),
    ("error", {}, A.EVENT_FAILED),
    ("agent.aborted", {"termination": "aborted"}, A.EVENT_CANCELLED),
]
bad = [n for n in drop if A.map_longrun_event(n, {}) is not None]
bad += ["%s %s" % (n, p) for n, p, want in kept
        if A.map_longrun_event(n, p) != want]
check("test_event_mapper_drops_reasoning_observations_and_unknown_events",
      not bad, bad)

# --- 3: a disconnect BEFORE the run-id frame is indeterminate, never retried -
opener = FakeOpener([FakeResponse(chunks=[b"event: agent.start\ndata: {}\n\n"])])
frames = []
res = _client(opener).stream_run(_invocation()).run(frames.append)
starts = [r for r in opener.requests if r.full_url.endswith("/api/agent/run/stream")]
check("test_disconnect_before_run_id_is_indeterminate_without_retry",
      res.termination == "indeterminate" and res.run_id is None
      and len(starts) == 1 and len(opener.requests) == 1
      and len(frames) == 1 and frames[0]["run_id"] is None
      and frames[0]["event"] == A.EVENT_FAILED,
      "term=%s reqs=%d frames=%d" % (res.termination, len(opener.requests), len(frames)))

opener = FakeOpener([FakeResponse(chunks=[ConnectionResetError("peer reset")])])
frames = []
res = _client(opener).stream_run(_invocation()).run(frames.append)
check("a mid-stream drop is indeterminate too (no second start)",
      res.termination == "indeterminate"
      and len([r for r in opener.requests
               if r.full_url.endswith("/api/agent/run/stream")]) == 1,
      res.termination)

# malformed SSE JSON fails closed: never a success, never a replacement run
opener = FakeOpener([FakeResponse(chunks=[b"event: run\ndata: {not json}\n\n"])])
frames = []
res = _client(opener).stream_run(_invocation()).run(frames.append)
check("malformed SSE JSON is indeterminate and is not retried",
      not res.ok and res.termination == "indeterminate"
      and len(opener.requests) == 1 and len(frames) == 1
      and frames[-1]["event"] == A.EVENT_FAILED,
      "%s reqs=%d" % (res.termination, len(opener.requests)))

# --- 4: abort targets the KNOWN run id --------------------------------------
opener = FakeOpener([FakeResponse(body=b"{\"id\": \"run_abc123\", \"status\": \"aborted\"}")])
out = _client(opener).abort_run("run_abc123")
req = opener.requests[0]
check("test_abort_targets_the_known_run_id",
      req.full_url.endswith("/api/agent/control") and req.method == "POST"
      and json.loads(req.data.decode()) == {"action": "abort", "runId": "run_abc123"}
      and out.get("id") == "run_abc123",
      "%s %s" % (req.full_url, req.data))

# --- 5: bearer auth + configured base URL -----------------------------------
for cut in (40, 120):
    opener = FakeOpener([
        FakeResponse(chunks=[SSE_OK[:cut].encode(), SSE_OK[cut:].encode()]),
        FakeResponse(body=RUN_RECORD_OK)])
    frames = []
    res = _client(opener).stream_run(_invocation()).run(frames.append)
    start_req, record_req = opener.requests[0], opener.requests[1]
    body = json.loads(start_req.data.decode())
    full = json.dumps(frames)
    check("test_stream_uses_bearer_and_configured_base_url [cut=%d]" % cut,
          start_req.full_url == "http://127.0.0.1:8790/api/agent/run/stream"
          and start_req.get_header("Authorization") == "Bearer LONGRUN-SECRET-TOKEN"
          and start_req.get_header("Accept") == "text/event-stream"
          and body == {"goal": "do the assigned task", "max_steps": 6}
          and record_req.full_url.endswith("/api/agent/runs/run_abc123")
          and "LONGRUN-SECRET-TOKEN" not in full,
          "url=%s body=%s" % (start_req.full_url, body))
    check("test_no_reasoning_or_secret_text_in_frames [cut=%d]" % cut,
          "TOP-SECRET-COT" not in full and "TOP-SECRET-OBS" not in full
          and "private goal" not in full,
          full[:200])

# --- 6: the happy path emits started → progress → completed -----------------
opener = FakeOpener([
    FakeResponse(chunks=[SSE_OK[:77].encode(), SSE_OK[77:].encode()]),
    FakeResponse(body=RUN_RECORD_OK)])
frames = []
res = _client(opener).stream_run(_invocation()).run(frames.append)
names = [f["event"] for f in frames]
check("test_completed_run_emits_started_progress_completed",
      names == [A.EVENT_STARTED, A.EVENT_PROGRESS, A.EVENT_COMPLETED]
      and res.termination == "completed" and res.ok
      and res.run_id == "run_abc123"
      and [f["seq"] for f in frames] == [1, 2, 3]
      and all(f["schema"] == A.SCHEMA_EVENT for f in frames)
      and frames[2]["payload"].get("summary") == "did the thing",
      "names=%s term=%s" % (names, res.termination))

# --- 7: the run record must agree with the stream ---------------------------
opener = FakeOpener([
    FakeResponse(chunks=[SSE_OK.encode()]),
    FakeResponse(body=json.dumps({"id": "run_abc123", "termination": "max_steps"}).encode())])
frames = []
res = _client(opener).stream_run(_invocation()).run(frames.append)
check("test_terminal_classification_must_match_the_run_record",
      res.termination == "indeterminate" and not res.ok
      and frames[-1]["event"] == A.EVENT_FAILED
      and len([f for f in frames if f["event"] in
               (A.EVENT_COMPLETED, A.EVENT_FAILED, A.EVENT_CANCELLED)]) == 1,
      "term=%s frames=%s" % (res.termination, [f["event"] for f in frames]))

opener = FakeOpener([
    FakeResponse(chunks=[SSE_OK.encode()]),
    FakeResponse(body=b"{}")])
res = _client(opener).stream_run(_invocation()).run(lambda f: None)
check("a missing run record is indeterminate (never claimed complete)",
      res.termination == "indeterminate" and not res.ok, res.termination)

# --- 8: non-completed terminal states never count as success ---------------
for term, sse_name in (("max_steps", "agent.finish"), ("no_progress", "agent.finish")):
    payload = {"run": "run_abc123", "summary": "bounded stop", "termination": term}
    stream = ("event: run\ndata: {\"run_id\": \"run_abc123\"}\n\n"
              + "event: %s\ndata: %s\n\n" % (sse_name, json.dumps(payload)))
    opener = FakeOpener([
        FakeResponse(chunks=[stream.encode()]),
        FakeResponse(body=json.dumps({"id": "run_abc123", "termination": term}).encode())])
    frames = []
    res = _client(opener).stream_run(_invocation()).run(frames.append)
    check("test_bounded_stop_is_not_success [%s]" % term,
          res.termination == term and not res.ok and res.exit_code == 1
          and frames[-1]["event"] == A.EVENT_FAILED,
          "%s exit=%s" % (res.termination, res.exit_code))

# --- 9: invitation validation + longrun body shape -------------------------
bad = []
for kw, label in (({"goal": ""}, "empty goal"), ({"goal": 5}, "non-string goal"),
                  ({"max_steps": 0}, "zero steps"), ({"max_steps": "6"}, "string steps"),
                  ({"model": 7}, "non-string model"),
                  ({"schema": "nope"}, "bad schema"),
                  ({"agent_id": ""}, "empty agent id"),
                  ({"paperclip_run_id": ""}, "empty run id")):
    base = {"goal": "g", "paperclip_run_id": "pc", "agent_id": "a", "company_id": "c"}
    base.update(kw)
    try:
        A.PaperclipInvocation.from_dict(base)
        bad.append(label)
    except A.InvocationError:
        pass
inv = _invocation(session_id="sess-1", model="qwen")
check("test_invocation_validation_and_longrun_body",
      not bad and inv.longrun_body() == {"goal": "do the assigned task",
                                         "max_steps": 6, "model": "qwen",
                                         "session": "sess-1"},
      "%s %s" % (bad, inv.longrun_body()))

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
