#!/usr/bin/env python3
"""v323 — a headless/background turn must show its "running" signal (JAG-323).

SEVERE finding: an agent session was RUNNING (GPU busy, tokens burning) but the
left panel showed NO signal — a "phantom run"; the operator noticed only from GPU
usage and had to stop it. Root cause: the main app's session list (`/api/sessions`)
carried NO `running` flag, and `chat.run` was pushed ONLY to the starting browser's
own stream — never published to the global feed (`chat.done` was). So any turn this
browser did not start (a job/routine turn on another session) was invisible.

Locked here:
  * `list_sessions()` exposes an authoritative live `running` flag from `_ACTIVE_CHAT`;
  * the server publishes `chat.run` on the global feed (like `chat.done`);
  * the UI marks a session busy on `chat.run` and clears it on `chat.done`, for ANY
    session, and seeds the marker from the server flag on (re)load.

Deterministic, no model. Run: python3 tests/acceptance/v323_running_signal.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-323-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def _row(sid):
    return next((r for r in server.list_sessions() if r["id"] == sid), None)


server.get_or_create_session("v323run", "live probe")

check("A1 an idle session reports running=False",
      _row("v323run").get("running") is False, str(_row("v323run")))

with server._ACTIVE_CHAT_LOCK:
    server._ACTIVE_CHAT["v323run"] = {"ev0": 0, "ts": 0.0, "tok": object()}
check("A2 a turn in flight makes the session running=True",
      _row("v323run").get("running") is True, str(_row("v323run")))

with server._ACTIVE_CHAT_LOCK:
    server._ACTIVE_CHAT.pop("v323run", None)
check("A3 clearing the turn clears the flag",
      _row("v323run").get("running") is False, str(_row("v323run")))

# ---- wiring ---------------------------------------------------------------
srv = read("src", "longrun", "core/server.py") + read("src", "longrun", "core/httpapi.py")
check("B1 the server publishes chat.run on the global feed",
      'publish("chat.run"' in srv)
check("B2 the session list reads the live active-turn registry",
      "_active = set(_ACTIVE_CHAT.keys())" in read("src", "longrun", "memory/stores.py"))

ui = read("webui", "index.html")
check("C1 the feed marks a session busy on chat.run",
      'es.addEventListener("chat.run"' in ui
      and "if (d.session) { _streamedDone[d.session] = false; setRunning(d.session, true); }" in ui)
check("C2 chat.done clears the busy marker for ANY session",
      "setRunning(d.session, false);" in ui)
check("C3 the session list seeds the marker from the server flag",
      "if (s.running) runningSessions[s.id] = true;" in ui)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

