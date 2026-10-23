#!/usr/bin/env python3
"""v542 — automatic codebase indexing is observable.

The background pass used to be silent: the Codebase panel showed a stale
"Embedding incomplete" line until the operator clicked status. Now a pass that
CHANGED the index publishes `index.done` (the WebUI already re-renders on it),
`watch_state()` reports the watcher, and `/api/codebase/status` carries it.
Session-scoped workspaces get a watcher too.
"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v542-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import events                 # noqa: E402
from longrun.memory import autoidx              # noqa: E402
from longrun.memory import codeindex            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def events_of(kind):
    return [e for e in events.events_since(0) if e.get("kind") == kind]


ws = os.path.join(TMP, "ws")
os.makedirs(ws)
with open(os.path.join(ws, "a.py"), "w", encoding="utf-8") as f:
    f.write("def a():\n    return 1\n")

# --- announce(): one event per CHANGE, never per no-op pass -----------------
slot = {}
counts = {"files": 1, "chunks": 2, "embedded": 2}
autoidx._announce(ws, counts, {"embed_error": None}, slot)
first = events_of("index.done")
autoidx._announce(ws, dict(counts), {"embed_error": None}, slot)
second = events_of("index.done")
check("A1 a changed pass publishes index.done with the workspace",
      len(first) == 1 and first[0].get("workspace") == ws
      and first[0].get("auto") is True, first)
check("A2 a no-op pass publishes nothing",
      len(second) == len(first), len(second))

# --- watch_state(): says whether a watcher exists ---------------------------
before = autoidx.watch_state(ws)
check("B1 an unwatched workspace says so", before.get("watched") is False, before)

_orig_build = codeindex.build
_orig_delay = autoidx.STARTUP_DELAY_S
try:
    codeindex.build = lambda target, force=False, progress=None: {
        "files": 1, "chunks": 2, "embedded": 2, "embed_error": None}
    autoidx.STARTUP_DELAY_S = 0.01
    started = autoidx.start(ws)
    deadline = time.time() + 4
    state = autoidx.watch_state(ws)
    while time.time() < deadline and not (state.get("last") or {}).get("files"):
        time.sleep(0.05)
        state = autoidx.watch_state(ws)
    check("B2 start() launches the watcher and reports it",
          started is True and state.get("watched") is True, state)
    check("B3 the watcher records its last pass (files/chunks/interval)",
          (state.get("last") or {}).get("files") == 1
          and (state.get("last") or {}).get("chunks") == 2
          and int(state.get("interval_s") or 0) >= 10, state)
    check("B4 the background pass announced the index",
          any(e.get("workspace") == ws for e in events_of("index.done")))
finally:
    autoidx.stop(ws)
    autoidx.STARTUP_DELAY_S = _orig_delay
    codeindex.build = _orig_build

check("B5 stop() removes the watcher",
      autoidx.watch_state(ws).get("watched") is False)

with open(os.path.join(ROOT, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8") as f:
    API = f.read()
check("C1 /api/codebase/status reports the watcher and the auto toggle",
      'out["auto"] = {"enabled": bool(_indexcfg.auto_index()),' in API
      and '"watcher": _autoidx.watch_state(ws)}' in API)
check("C2 a session-scoped workspace starts its own watcher",
      API.count("_autoidx.start(real)") >= 2)

with open(os.path.join(ROOT, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
check("C3 the Codebase panel renders the auto-index state",
      "Auto-index · <b>" in UI and "_cbAgo(last.at)" in UI
      and "no watcher for this workspace" in UI)

shutil.rmtree(TMP, ignore_errors=True)
print("v542: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
