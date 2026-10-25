#!/usr/bin/env python3
"""v532 — a change made ANYWHERE repaints the WebUI without F5 (JAG-532).

The WebUI, Orbit, the CLI and an agent all end up in the SAME layer-2 writers. A
panel that only repaints on the click that caused a change is therefore a lie: a
batch CLI run, an agent turn or another tab leaves it showing the previous value.

This locks the two halves of the contract:

  A) the writers ANNOUNCE their change (single-writer functions, not route
     handlers, so every caller is covered);
  B) the WebUI SUBSCRIBES to those kinds and re-reads the panel they invalidate —
     through ONE table shared by the live EventSource and the backlog replay.

Deterministic: temp dirs, no live model, no network.
Run: python3 tests/acceptance/v532_live_sync.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v532-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB", "COSTS_DIR",
           "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events as E          # noqa: E402
from longrun.memory import stores             # noqa: E402
from longrun.orchestrate import roles as R    # noqa: E402

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


def kinds():
    return [e.get("kind") for e in E.events_since(0)]


# --- A: the single writers announce ----------------------------------------
sid = "v532-sess"
stores.save_session({"id": sid, "title": "v532", "workspace": TMP, "model": "",
                     "messages": []})
_m = stores._set_session_model(sid, "openrouter:foo")
check("A1 a session model change is announced",
      _m == "openrouter:foo" and "session.updated" in kinds(), kinds()[-4:])
_before = len(kinds())
stores._set_session_model(sid, "openrouter:foo")
check("A2 re-writing the SAME model is silent (no feed noise on reconcile)",
      len(kinds()) == _before, len(kinds()) - _before)

R.write(sid, "You are the v532 role.")
check("A3 a ROLE.md write is announced",
      "roles.update" in kinds()
      and [e for e in E.events_since(0) if e.get("kind") == "roles.update"][-1]
      .get("session") == sid, "")
R.write(sid, "")
check("A4 clearing a ROLE.md is announced too",
      sum(1 for e in E.events_since(0) if e.get("kind") == "roles.update") >= 2, "")

with open(os.path.join(REPO, "src", "longrun", "orchestrate", "teams.py"),
          encoding="utf-8") as f:
    TEAMS = f.read()
with open(os.path.join(REPO, "src", "longrun", "orchestrate", "routines.py"),
          encoding="utf-8") as f:
    ROUTINES = f.read()
check("A5 the team registry announces from its only writer",
      "def _save(d):" in TEAMS and "_announce(d)" in TEAMS
      and 'publish("teams.updated"' in TEAMS, "")
check("A6 the routines registry announces from its only writer",
      "def _save(d):" in ROUTINES and 'publish("routines.updated"' in ROUTINES, "")

# --- B: the WebUI subscribes to the published kinds ------------------------
_tbl = HTML.split("const _FEED_REFRESH = {", 1)[1].split("};", 1)[0]
_entries = [ln.split('"')[1] for ln in _tbl.splitlines() if ln.strip().startswith('"')]
check("B1 the refresh table is non-trivial and keyed by event kind",
      len(_entries) >= 15 and all("." in k for k in _entries), "%d kinds" % len(_entries))
check("B2 the live feed subscribes to EVERY kind in the table",
      "Object.keys(_FEED_REFRESH).forEach" in HTML and "_feedReplay(d)" in HTML, "")
check("B3 the replay dispatcher consults the SAME table (no half-wired kind)",
      "_FEED_REFRESH[kind]" in HTML, "")
# every kind the table names must be published by SOME layer-2 writer
_src = []
for _root, _dirs, _files in os.walk(os.path.join(REPO, "src")):
    for _f in _files:
        if _f.endswith(".py"):
            with open(os.path.join(_root, _f), encoding="utf-8") as fh:
                _src.append(fh.read())
_SRC = "\n".join(_src)
_unpublished = [k for k in _entries
                if 'publish("%s"' % k not in _SRC and "publish(kind" not in _SRC]
check("B4 every kind the UI listens for is really published by the backend",
      not _unpublished, _unpublished)
check("B5 the model + rail panels are repainted by the event, not by the click",
      '"session.updated": () => { loadSessions(); loadAgents(); loadSettingsForms(); }'
      in HTML and '"teams.updated": () => { loadSessions(); loadAgents(); },' in HTML, "")
check("B6 a cleared session reloads the transcript of the OPEN session",
      '"session.cleared": () => { loadSessions(); if (sessionId) loadHistory(); }'
      in HTML, "")

print("---")
ok = sum(results)
print("v532: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
