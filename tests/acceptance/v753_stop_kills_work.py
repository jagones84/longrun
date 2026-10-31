#!/usr/bin/env python3
"""v753 — Stop must KILL the work, not just set a flag.

Measured 2026-10-31 (session A117, polyglot `forth`): the operator pressed Stop,
the UI printed "stop requested", and the session kept running at 9 min because
`/api/chat/abort` only set an in-memory flag — checked at the next loop iteration,
which never came while `pytest` was still inside `run_capture`. Stop now interrupts
the session terminal's child and cancels the sandbox job, so the tool returns and
the flag takes effect.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v753-")
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
from longrun.tools import sandbox, term        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. a sandbox job is cancelled mid-flight ------------------------------
box = {}


def _job():
    box["r"] = sandbox.run("sleep 30", run_id="v753-sb", timeout=20)


th = threading.Thread(target=_job, daemon=True)
th.start()
deadline = time.time() + 8
while time.time() < deadline:
    with sandbox._RUN_LOCK:
        if "v753-sb" in sandbox._RUNNING:
            break
    time.sleep(0.05)
check("A1 the running job is tracked under the run id", "v753-sb" in sandbox._RUNNING)
res = sandbox.cancel_run("v753-sb")
check("A2 cancel_run reports the job", res.get("cancelled") == 1, res)
th.join(timeout=10)
check("A3 the command RETURNS instead of waiting its timeout", not th.is_alive())
r = box.get("r") or {}
check("A4 it is reported as cancelled (exit 130)", r.get("exit_code") == 130, r)
check("A5 the reason is visible in the result",
      "cancel" in str(r.get("stderr") or "").lower(), r.get("stderr"))
check("A6 cancelling twice is safe", sandbox.cancel_run("v753-sb").get("cancelled") == 0)

# ---- B. the session terminal child is interrupted --------------------------
ws = tempfile.mkdtemp(prefix="v753-ws-")
sh = term.get("v753-term", cwd=ws)
out = {}


def _cmd():
    out["r"] = sh.run_capture("sleep 30", timeout=60)


th2 = threading.Thread(target=_cmd, daemon=True)
th2.start()
deadline = time.time() + 8
while time.time() < deadline and not sh.busy:
    time.sleep(0.05)
check("B1 the terminal reports the command as running", sh.busy is True)
hit = term.interrupt_session("v753-term")
check("B2 interrupt_session reaches the child", hit is True)
th2.join(timeout=12)
check("B3 run_capture returns instead of waiting for its timeout", not th2.is_alive())
r2 = out.get("r") or {}
check("B4 the result says it was interrupted", bool(r2.get("interrupted") or r2.get("timed_out")), r2)
check("B5 it is NOT reported as a success", r2.get("ok") is False, r2)
check("B6 the shell survives for the next command",
      sh.proc.poll() is None or not sh.busy, "poll=%r busy=%r" % (sh.proc.poll(), sh.busy))
term.reset("v753-term")

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
