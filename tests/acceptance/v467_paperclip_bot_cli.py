#!/usr/bin/env python3
"""v467 — `forge.py paperclip-bot` CLI contract (Paperclip Task 4).

The CLI is the child process Paperclip's TypeScript adapter spawns. It must:

  * read exactly one invocation envelope on stdin and validate it BEFORE any
    network call;
  * take the Longrun URL and bearer token from ``LONGRUN_URL``/``LONGRUN_TOKEN``
    only — never from task content, argv, or stdout;
  * write protocol frames (Task 3 schema) and nothing else to stdout, all
    diagnostics to stderr;
  * exit ``0`` only for a corroborated ``completed`` run, ``1`` otherwise, and
    ``130`` after an operator signal, aborting the known Longrun run id.

Deterministic and offline: a local fixture HTTP server stands in for Longrun
(no LLM, no external network). Isolated: the subprocess talks only to the
loopback fixture on an ephemeral port.

Run: python3 tests/acceptance/v467_paperclip_bot_cli.py
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN = "LONGRUN-SECRET-TOKEN"
RUN_ID = "run_abc123"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --------------------------------------------------------------- fixture ----
RUN_FRAME = b"event: run\ndata: {\"run_id\": \"" + RUN_ID.encode() + b"\"}\n\n"


def _finish(termination, summary="did the thing"):
    payload = json.dumps({"run": RUN_ID, "termination": termination, "summary": summary})
    return ("event: agent.finish\ndata: %s\n\n" % payload).encode()


def start_fixture(segments, record=None, hold_last_s=0.0):
    """Serve a controlled SSE stream + run record. Returns (server, state)."""
    state = {"seen": [], "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):  # keep the test output clean
            pass

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _json(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = self._read_body()
            state["seen"].append({"method": "POST", "path": self.path,
                                  "auth": self.headers.get("Authorization"), "body": body})
            if self.path == "/api/agent/run/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for i, segment in enumerate(segments):
                        if i and i == len(segments) - 1 and hold_last_s:
                            state["release"].wait(hold_last_s)
                        self.wfile.write(segment)
                        self.wfile.flush()
                except OSError:
                    pass  # client cancelled and closed the socket: fine
            elif self.path in ("/api/agent/control", "/api/agent/run"):
                self._json({"id": RUN_ID, "status": "aborted"})
            else:
                self._json({}, 404)

        def do_GET(self):
            state["seen"].append({"method": "GET", "path": self.path,
                                  "auth": self.headers.get("Authorization"), "body": b""})
            if self.path.startswith("/api/agent/runs/"):
                self._json(record if record is not None else {})
            else:
                self._json({}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def base_url(server):
    return "http://127.0.0.1:%d" % server.server_address[1]


def envelope(**over):
    body = {"schema": "longrun.paperclip.invocation.v1", "goal": "do the assigned task",
            "paperclip_run_id": "pc_run_1", "agent_id": "agent_1",
            "company_id": "co_1", "task_id": "task_9", "max_steps": 6}
    body.update(over)
    return json.dumps(body)


def run_cli(stdin_text, server, timeout=30):
    """Run the real CLI against the fixture; returns the completed process."""
    env = dict(os.environ)
    env["LONGRUN_URL"] = base_url(server)
    env["LONGRUN_TOKEN"] = TOKEN
    return subprocess.run([sys.executable, "forge.py", "paperclip-bot"], cwd=REPO,
                          input=stdin_text.encode("utf-8"), capture_output=True,
                          timeout=timeout, env=env)


def frames_of(stdout_text):
    return [json.loads(line) for line in stdout_text.splitlines() if line.strip()]


def stop(server, state):
    state["release"].set()
    server.shutdown()
    server.server_close()


# --- 1: a valid invocation emits only NDJSON protocol frames ---------------
server, state = start_fixture([RUN_FRAME, _finish("completed")],
                              record={"id": RUN_ID, "termination": "completed"})
proc = run_cli(envelope(), server)
out, err = proc.stdout.decode(), proc.stderr.decode()
frames = frames_of(out)
posts = [r for r in state["seen"] if r["method"] == "POST"]
starts = [r for r in posts if r["path"] == "/api/agent/run/stream"]
check("test_cli_emits_only_ndjson_for_valid_invocation",
      proc.returncode == 0
      and all(f.get("schema") == "longrun.paperclip.event.v1" for f in frames)
      and [f["seq"] for f in frames] == list(range(1, len(frames) + 1))
      and [f["event"] for f in frames] == ["longrun.run.started", "longrun.run.completed"]
      and len(starts) == 1 and starts[0]["auth"] == "Bearer " + TOKEN
      and json.loads(starts[0]["body"].decode()) == {"goal": "do the assigned task",
                                                     "max_steps": 6}
      and all(r["path"].startswith("/api/agent/") for r in state["seen"]),
      "rc=%s frames=%s seen=%s" % (proc.returncode, [f["event"] for f in frames],
                                   [r["path"] for r in state["seen"]]))
stop(server, state)

# --- 2: bad stdin is rejected before any network call ----------------------
bad_cases = [("empty input", ""), ("invalid JSON", "{not json"),
             ("missing goal", envelope(goal="")),
             ("no envelope fields", "{}")]
bad = []
for label, payload in bad_cases:
    server, state = start_fixture([], record={})
    proc = run_cli(payload, server)
    if proc.returncode == 0 or proc.stdout.strip() or not proc.stderr.strip() or state["seen"]:
        bad.append("%s(rc=%s out=%r seen=%d)" % (label, proc.returncode,
                                                 proc.stdout[:60], len(state["seen"])))
    stop(server, state)
check("test_cli_rejects_invalid_stdin_before_network", not bad, bad)

# --- 3: diagnostics stay on stderr, stdout carries no secret ---------------
server, state = start_fixture([RUN_FRAME, _finish("completed")],
                              record={"id": RUN_ID, "termination": "completed"})
proc = run_cli(envelope(), server)
out, err = proc.stdout.decode(), proc.stderr.decode()
check("test_cli_keeps_diagnostics_on_stderr",
      bool(err.strip()) and TOKEN not in out and TOKEN not in err
      and "paperclip-bot" in err and all(line.startswith("{") for line in out.splitlines()),
      "err=%r" % err[:120])
stop(server, state)

# --- 4: exit status tracks the terminal classification ---------------------
cases = [("completed", 0), ("max_steps", 1), ("no_progress", 1)]
bad = []
for termination, want in cases:
    record = {"id": RUN_ID, "termination": termination}
    server, state = start_fixture([RUN_FRAME, _finish(termination)], record=record)
    proc = run_cli(envelope(), server)
    frames = frames_of(proc.stdout.decode())
    terminal = [f for f in frames if f["event"] != "longrun.run.progress"
                and f["event"] != "longrun.run.started"]
    if proc.returncode != want or len(terminal) != 1 or not frames:
        bad.append("%s(rc=%s want=%s terminal=%s)" % (termination, proc.returncode, want,
                                                     [f["event"] for f in terminal]))
    stop(server, state)
check("test_cli_exit_code_tracks_terminal_classification", not bad, bad)

# a contradictory record must never be reported as success
server, state = start_fixture([RUN_FRAME, _finish("completed")],
                              record={"id": RUN_ID, "termination": "max_steps"})
proc = run_cli(envelope(), server)
check("an unconfirmed completion is not a success (exit 1, failed frame)",
      proc.returncode == 1
      and frames_of(proc.stdout.decode())[-1]["event"] == "longrun.run.failed",
      "rc=%s" % proc.returncode)
stop(server, state)

# --- 5: an operator signal aborts the known run and exits 130 --------------
server, state = start_fixture([RUN_FRAME, _finish("completed")],
                              record={"id": RUN_ID, "termination": "completed"},
                              hold_last_s=10.0)
env = dict(os.environ)
env["LONGRUN_URL"] = base_url(server)
env["LONGRUN_TOKEN"] = TOKEN
child = subprocess.Popen([sys.executable, "forge.py", "paperclip-bot"], cwd=REPO,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
child.stdin.write(envelope().encode("utf-8"))
child.stdin.close()
deadline = time.time() + 15
while time.time() < deadline:
    if any(r["path"] == "/api/agent/run/stream" for r in state["seen"]):
        break
    time.sleep(0.05)
time.sleep(1.0)  # let the CLI read the run-id frame and remember it
child.send_signal(signal.SIGTERM)
try:
    rc = child.wait(timeout=15)
except subprocess.TimeoutExpired:
    child.kill()
    rc = None
if rc is None:
    child.wait()
out = child.stdout.read().decode()
err = child.stderr.read().decode()
aborts = [r for r in state["seen"] if r["path"] == "/api/agent/control"]
check("operator signal aborts the known run id and exits 130",
      rc == 130 and len(aborts) == 1
      and json.loads(aborts[0]["body"].decode()) == {"action": "abort", "runId": RUN_ID}
      and all(line.startswith("{") for line in out.splitlines())
      and "longrun.run.completed" not in out,
      "rc=%s abort=%s" % (rc, aborts[0]["body"] if aborts else None))
stop(server, state)

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
