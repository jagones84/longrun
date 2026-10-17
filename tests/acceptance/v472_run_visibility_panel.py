#!/usr/bin/env python3
"""v472 — every run is VISIBLE, and the rail counts what is in flight (JAG-479).

Operator report (two parts):
  1. "I did not see the running symbol on the chats … and the finished-answer
     icon when the user is not looking at that chat";
  2. the Sessions panel must make the NUMBER of running agents evident, with a
     separate panel listing the running sessions and the sessions that finished
     but were not read yet.

Root cause of (1), proved by reading the code, not guessed:
  * the rail's spinner is driven by the server flag `running` (stores.list_sessions
    -> `_ACTIVE_CHAT`) and by the `chat.run` / `chat.done` feed events;
  * `chat_once` / the in-process MCP chat DO bracket themselves with
    `turn_begin` / `turn_end` (JAG-325);
  * `agent_stream_gen_v2` — the path a Paperclip task / job takes, and the one that
    owns the visible session (JAG-476) — never did. Its run produced a task graph
    and feed lines but never registered as a turn, so `running` stayed False and
    no `chat.done` was ever published: no spinner, and no "finished" bell.

Contract locked here:
  * an agent run that owns a session registers in `_ACTIVE_CHAT` for its WHOLE
    duration and releases it on any outcome (also publishing `chat.run`/`chat.done`);
  * a run with NO session (pure headless, nothing to show) touches no registry;
  * the rail exposes the two REAL signals — agents in flight and sessions finished
    while the operator was elsewhere — as a count plus a separate panel whose rows
    are hyperlinks to the chat, and the "unread" set survives a reload.

Deterministic: the run worker is stubbed, so no provider/model is contacted.
Isolated: throwaway LONGRUN_* dirs.

Run: python3 tests/acceptance/v472_run_visibility_panel.py
"""
import io
import os
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v472-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.core import events as EV  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
API_SRC = _read("src", "longrun", "core", "api_v02.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- stubbed run worker: blocks until released, then reports a summary -------
started = threading.Event()
release = threading.Event()
CALLS = []


def _blocking_run(goal, max_steps=6, model=None, on_event=None, script=None,
                  run_id=None, workspace=None, fallbacks=None):
    CALLS.append({"goal": goal, "run_id": run_id})
    on_event("agent.start", run=run_id, goal=goal, max_steps=max_steps)
    if len(CALLS) == 1:                     # only the FIRST run is held open
        started.set()
        release.wait(10)
    on_event("agent.finish", run=run_id, summary="agent says hi")
    return {"run_id": run_id, "goal": goal, "model": model, "status": "done",
            "termination": "completed", "summary": "agent says hi", "trace": [],
            "prm": None}


_ORIG_RUN = API.agent_run_v2
API.agent_run_v2 = _blocking_run
try:
    # --- 1: a run that owns a session is RUNNING while it runs ---------------
    sess = STORES.get_or_create_session(None, "paperclip task")
    sid = sess["id"]
    before = set(EV._ACTIVE_CHAT.keys())
    gen = API.agent_stream_gen_v2("do the thing", 2, "local:test-model", "run-v472",
                                  session_obj=sess)
    first = next(gen)
    check("A1 the stream opens with the run frame", first.startswith("event: run"), first[:40])
    started.wait(10)
    with EV._ACTIVE_CHAT_LOCK:
        live = sid in EV._ACTIVE_CHAT
    check("A2 the session is registered as RUNNING for the whole run", live,
          sorted(EV._ACTIVE_CHAT.keys()))
    check("A3 the registry gained exactly this session",
          set(EV._ACTIVE_CHAT.keys()) == before | {sid},
          sorted(EV._ACTIVE_CHAT.keys()))

    release.set()
    frames = list(gen)
    check("A4 the stream ends with the done frame",
          any(f.startswith("event: done") for f in frames), len(frames))
    with EV._ACTIVE_CHAT_LOCK:
        still = sid in EV._ACTIVE_CHAT
    check("A5 the running flag is RELEASED when the run ends", not still,
          sorted(EV._ACTIVE_CHAT.keys()))

    # --- 2: the run's outcome is persisted on the session --------------------
    saved = STORES.load_session(sid) or {}
    msgs = saved.get("messages", [])
    roles = [m.get("role") for m in msgs]
    check("A6 the goal and the run's summary are transcripted",
          roles[-2:] == ["user", "assistant"]
          and msgs[-1].get("content") == "agent says hi", roles)

    # --- 3: the feed carries chat.run / chat.done for that session ----------
    kinds = [e.get("kind") for e in EV.events_since(0)
             if e.get("session") == sid]
    check("A7 chat.run and chat.done are published for the run",
          "chat.run" in kinds and "chat.done" in kinds, kinds[-8:])

    # --- 4: a run with NO session touches no registry ------------------------
    before2 = set(EV._ACTIVE_CHAT.keys())
    gen2 = API.agent_stream_gen_v2("pure headless", 1, "local:test-model", "run-v472b")
    next(gen2)
    for _ in gen2:
        pass
    check("A8 a headless run with no session registers nothing",
          set(EV._ACTIVE_CHAT.keys()) == before2,
          sorted(EV._ACTIVE_CHAT.keys()))
finally:
    API.agent_run_v2 = _ORIG_RUN

# --- 5: the rail counts the two REAL signals --------------------------------
check("B1 the Sessions panel has a runs bar",
      'id="runsBar"' in HTML and 'class="runs-bar"' in HTML, "")
check("B2 the bar shows a running count and a finished count",
      'id="runsBarRun"' in HTML and 'id="runsBarDone"' in HTML, "")
check("B3 a SEPARATE panel window exists and is a labelled dialog",
      'id="runsPanel"' in HTML and 'role="dialog"' in HTML
      and 'aria-label="agents in flight and unread sessions"' in HTML, "")
check("B4 the bar toggles the panel and reports its state",
      'function toggleRunsPanel(' in HTML and 'aria-expanded' in HTML
      and 'aria-controls="runsPanel"' in HTML, "")
check("B5 one renderer reads the two live signal maps",
      'function renderRuns(' in HTML and 'runningSessions[s.id]' in HTML
      and 'Object.keys(doneSessions)' in HTML, "")
check("B6 the panel's rows are LINKS to the chat session",
      'a.href = "#session-" + s.id' in HTML and 'selectSession({ id: s.id })' in HTML, "")
check("B7 the panel lists the running and the unread sections explicitly",
      '"⚡ running (' in HTML and 'unread (' in HTML, "")
check("B8 the unread set is PERSISTED (survives a reload)",
      'function _loadUnread(' in HTML and 'function _saveUnread(' in HTML
      and 'localStorage.getItem(UNREAD_KEY)' in HTML
      and 'localStorage.setItem(UNREAD_KEY' in HTML
      and 'let doneSessions = _loadUnread()' in HTML, "")
check("B9 markDone/clearDone keep the persisted set in sync",
      HTML.count("_saveUnread()") >= 3, HTML.count("_saveUnread()"))
check("B10 the bar is refreshed on every signal change",
      HTML.count("renderRuns()") >= 4, HTML.count("renderRuns()"))
check("B11 the panel is styled and positioned from the bar",
      '.runs-bar' in HTML and '.runs-panel' in HTML and '.rp-row' in HTML
      and 'function _placeRunsPanel(' in HTML, "")
check("B12 the panel closes on Escape and on an outside click",
      '"Escape"' in HTML and 'closeRunsPanel(); bar.focus();' in HTML
      and 'document.addEventListener("click", e => {' in HTML, "")
check("B13 stale unread ids are pruned when a session disappears",
      '_IDs.has(id)' in HTML or '_ids.has(id)' in HTML, "")
check("B14 server payload is cached for the panel's titles",
      'let _sessList = []' in HTML and 'let _sessTitle = {}' in HTML, "")

# --- 6: the rail animations are real and motion-safe ------------------------
check("C1 the busy spinner is a real keyframe animation",
      "@keyframes sfspin" in HTML and "animation: sfspin .7s linear infinite" in HTML, "")
check("C2 the finished bell is a real keyframe animation",
      "@keyframes sfpulse" in HTML and '.sess.done' in HTML, "")
check("C3 the rail animations respect prefers-reduced-motion",
      'prefers-reduced-motion: reduce) { .sess.running::before, .sess.done::before' in HTML, "")

# --- 7: server source-lock (the bracket is where it must be) ----------------
check("D1 agent_stream_gen_v2 registers the session as running",
      '_turn_tok = srv.turn_begin(session_obj["id"]) if session_obj is not None else None'
      in API_SRC, "")
check("D2 the running flag is released in the worker's finally",
      'srv.turn_end(session_obj["id"], _turn_tok)' in API_SRC, "")
check("D3 the release happens after the reply is persisted",
      'srv.turn_end(session_obj["id"], _turn_tok)' in API_SRC
      and API_SRC.index('srv.turn_end(session_obj["id"], _turn_tok)')
      > API_SRC.index('_outcome["text"] or "(run produced no summary)"'), "")

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
