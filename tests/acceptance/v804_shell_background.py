#!/usr/bin/env python3
"""v804 — a long command must not park the turn (background jobs, 2026-11-05).

Operator: *"Yes shell may be backgrounded but i think its not blocking agent the
shell tool call or agent wait for it? But when command is unfinished agent shall
know look how works modern IDE for that"*.

The foreground `shell` tool WAITED for the command (120 s default), so a build or
an install froze the whole turn with no way to check on it. Now:

  A  `background: true` returns a job id immediately and the process keeps going;
  B  `action=status` reports running / exit code / the tail of the log, so an
     UNFINISHED command is visible instead of invisible;
  C  `action=stop` kills the whole process group (a build spawns children);
  D  the schema and the policy expose the new actions (a poll is never gated);
  E  background is refused under an isolating sandbox (a host process would
     escape it) instead of silently running outside the boundary.

Deterministic: real short processes, temp data dir, no model, no network.
Run: python3 tests/acceptance/v804_shell_background.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v804-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order: agent needs it)
from longrun.tools import bgjobs, registry, tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def wait_exit(job, secs=6.0):
    end = time.time() + secs
    while time.time() < end:
        st = bgjobs.status(job)
        if not st.get("running"):
            return st
        time.sleep(0.1)
    return bgjobs.status(job)


# ---- A: start returns immediately ---------------------------------------
t0 = time.time()
st = bgjobs.start("echo started; sleep 1; echo done")
_elapsed = time.time() - t0
check("A1 start returns a handle", st.get("ok") is True and st.get("background") is True, st)
check("A2 the call does NOT wait for the command", _elapsed < 0.9, "%.2fs" % _elapsed)
check("A3 the handle carries a job id, a pid and a log path",
      str(st.get("job") or "").startswith("bg-") and int(st.get("pid") or 0) > 0
      and str(st.get("log") or "").endswith(".log"), st)
check("A4 the hint tells the model how to check on it",
      "action:'status'" in str(st.get("hint")), st.get("hint"))
check("A5 the observation says it is NOT finished (never a fake exit=0)",
      "still running" in T.observation(dict(st, tool="shell.exec"))
      and "exit=0" not in T.observation(dict(st, tool="shell.exec")),
      T.observation(dict(st, tool="shell.exec")))
JOB1 = st.get("job")

# ---- B: an unfinished command is VISIBLE -------------------------------
time.sleep(0.35)
s1 = bgjobs.status(JOB1)
check("B1 status says it is still running", s1.get("running") is True, s1)
check("B2 the tail shows the output produced so far",
      "started" in str(s1.get("tail")), s1.get("tail"))
s2 = wait_exit(JOB1)
check("B3 after it ends: running=False and the real exit code",
      s2.get("running") is False and s2.get("exit_code") == 0, s2)
check("B4 the tail now holds the LAST line too", "done" in str(s2.get("tail")), s2.get("tail"))
check("B5 status reports elapsed time", float(s2.get("elapsed_s") or 0) >= 0.9, s2)

# ---- C: stop kills the group -------------------------------------------
st3 = bgjobs.start("sleep 30")
JOB3 = st3.get("job")
time.sleep(0.2)
k = bgjobs.stop(JOB3)
check("C1 stop reports it stopped", k.get("ok") is True and k.get("stopped") is True, k)
time.sleep(0.2)
check("C2 the job is no longer running", bgjobs.status(JOB3).get("running") is False)
check("C3 stopping a finished job is honest, not an error",
      bgjobs.stop(JOB1).get("stopped") is False, bgjobs.stop(JOB1))

# ---- D: the shell tool exposes them ------------------------------------
check("D1 the shell handler routes action=status",
      T._shell({"action": "status", "job": JOB1}, "v804").get("job") == JOB1)
check("D2 action=stop is routed too",
      "stopped" in T._shell({"action": "stop", "job": JOB3}, "v804"))
_d = registry.catalog()
_shell = [t for t in _d if t["name"] == "shell.exec"][0]
check("D3 the schema advertises status/stop",
      set(["status", "stop"]).issubset(
          set((_shell.get("inputSchema") or {}).get("properties", {})
              .get("action", {}).get("enum") or [])))
check("D4 the schema advertises background + job",
      "background" in (_shell.get("inputSchema") or {}).get("properties", {})
      and "job" in (_shell.get("inputSchema") or {}).get("properties", {}))
_dv, _rv = registry.classify("shell", {"action": "status", "job": JOB1})
check("D5 a poll is auto-approved (never a card per check)", _dv == "auto", (_dv, _rv))
check("D6 the shipped auto_approve names both controls",
      "^status$" in (registry.load_config()["tools"]["shell"].get("auto_approve") or [])
      and "^stop$" in (registry.load_config()["tools"]["shell"].get("auto_approve") or []))

# ---- E: refused where it would escape the sandbox ---------------------
_orig = T.sandbox.probe
try:
    T.sandbox.probe = lambda: {"backend": "docker"}
    r = T._shell({"command": "sleep 5", "background": True}, "v804")
    check("E1 background is refused under an isolating sandbox",
          r.get("ok") is False and "escape" in str(r.get("error")), r)
    T.sandbox.probe = lambda: {"backend": "none"}
    r2 = T._shell({"command": "echo from-bg", "background": True}, "v804")
    check("E2 on the host it starts a real job",
          r2.get("ok") is True and r2.get("background") is True, r2)
    wait_exit(r2.get("job"))
finally:
    T.sandbox.probe = _orig

check("E3 an empty command is refused", bgjobs.start("  ").get("ok") is False)
check("E4 an unknown job is named, not guessed",
      bgjobs.status("bg-nope").get("ok") is False)

print("\n---")
print("v804: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
