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
      # v640: the label is no longer title-case, and the freshness verdict joined
      # the same line (two lines said the same thing) — the facts pinned here are
      # unchanged: the state, when the watcher last ran, and the no-watcher case.
      "auto-index <b>" in UI and "_cbAgo(last.at)" in UI
      and "no watcher for this workspace" in UI
      and "cb-line cb-wrap" in UI)

# --- D: an EMPTY session folder is actionable, never a dead end --------------
# An agent session owns `<data home>/workspaces/<agent>`, which starts EMPTY: a
# build there honestly indexes 0 files and the panel used to just say "no indexable
# files", with no way out. The status/build payloads now name the folder, the
# default workspace, and the panel offers ONE explicit action.
from longrun.core import api_v02 as _api                      # noqa: E402
from longrun.memory import rules as _rules                    # noqa: E402
_rules.set_workspace(ws)
_h = _api._codebase_hint("/nowhere/empty", {"files": 0, "chunks": 0})
check("D1 an empty workspace is flagged as empty", _h.get("empty") is True, _h)
check("D2 the hint names the scanned folder and the default workspace",
      "/nowhere/empty" in (_h.get("hint") or "")
      # Windows keeps the case it was given: `TEMP` is uppercase, realpath lowercases
      # it, so compare normalized paths or this check flips with the environment.
      and os.path.normcase(_h.get("default_workspace") or "")
      == os.path.normcase(os.path.realpath(ws))
      and os.path.normcase(os.path.realpath(ws)) in os.path.normcase(_h.get("hint") or ""), _h)
_h2 = _api._codebase_hint("/ws", {"files": 7, "chunks": 9})
check("D3 a non-empty index carries no failure hint",
      not _h2.get("hint") and not _h2.get("empty") and _h2.get("default_workspace"), _h2)
check("D4 the status route exposes the hint", "return _codebase_hint(ws, out)" in API)
check("D5 the build route exposes the hint", "_codebase_hint(ws, res)" in API)
check("D6 the panel offers the explicit default-workspace action",
      'id="cbDefaultBtn"' in UI and "async function cbUseDefaultWorkspace()" in UI
      and '"/api/workspace"' in UI)
check("D6b linking the folder refreshes the Workspace rail",
      "if (typeof loadRules === \"function\") await loadRules();" in UI)
check("D7 the empty message renders the backend hint", "esc(s.hint ||" in UI)

# --- E: is the index STALE? the panel says so on its own ---------------------
# The watcher answers the question by construction; when it cannot (off, missing,
# failed, overdue) the status call does a BOUNDED scan and the panel shows a badge.
from longrun.memory import indexcfg as _indexcfg                # noqa: E402
_indexcfg.save_config({"embed_model": ""})                       # local build, no network
check("E1 the bounded freshness probe exists",
      callable(getattr(codeindex, "freshness", None)))

_ws2 = os.path.join(TMP, "ws2")
os.makedirs(_ws2)
_f1 = os.path.join(_ws2, "one.py")
with open(_f1, "w", encoding="utf-8") as f:
    f.write("def one():\n    return 1\n")
with open(os.path.join(_ws2, "two.py"), "w", encoding="utf-8") as f:
    f.write("def two():\n    return 2\n")
_built = codeindex.build(_ws2)
check("E2b the build reports the indexed files", int(_built.get("files") or 0) == 2, _built)
_fr_clean = codeindex.freshness(_ws2)
check("E2 a just-built index is NOT stale",
      _fr_clean.get("stale") is False and _fr_clean.get("checked") >= 2, _fr_clean)
check("E3 the build records the newest mtime it saw",
      codeindex.status(_ws2).get("newest_mtime") is not None)
_future = time.time() + 5
os.utime(_f1, (_future, _future))
_fr_stale = codeindex.freshness(_ws2)
check("E4 a file newer than the index makes it stale",
      _fr_stale.get("stale") is True and _fr_stale.get("newer_files") >= 1, _fr_stale)
_fr_capped = codeindex.freshness(_ws2, budget_s=0, max_files=1)
check("E5 the scan is bounded and admits it",
      _fr_capped.get("partial") is True and _fr_capped.get("checked") == 1, _fr_capped)
check("E6 the status route always answers: watcher first, bounded scan otherwise",
      'if _watcher_is_current(out["auto"]):' in API
      and '"source": "watcher"' in API
      and 'out["freshness"] = _ci.freshness(ws)' in API)
_fresh_auto = {"enabled": True, "watcher": {"watched": True, "interval_s": 10,
                                            "last": {"at": time.time(), "files": 2}}}
check("E7 a warm watcher short-circuits the scan",
      _api._watcher_is_current(_fresh_auto) is True
      and _api._watcher_is_current({"enabled": False, "watcher": {}}) is False
      and _api._watcher_is_current({"enabled": True, "watcher": {"watched": False}}) is False
      and _api._watcher_is_current({"enabled": True, "watcher": {
          "watched": True, "interval_s": 10, "last": {"at": time.time() - 3600}}}) is False)
check("E8 the panel renders the stale badge, the green OK and the build time",
      'class="cb-stale"' in UI and "newer than the index" in UI
      and 'class="cb-fresh"' in UI and "no re-index needed" in UI
      and "_cbAgo(s.built_at)" in UI)
check("E9 the indexed file list closes when `files` is clicked again",
      "if (_cbFilesOpen) { _cbFilesOpen = false;" in UI
      and 'id="cbFilesBox"' in UI)

shutil.rmtree(TMP, ignore_errors=True)
print("v542: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
