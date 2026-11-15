#!/usr/bin/env python3
"""v1045 — a reset survives the turn that issued it.

Measured 2026-11-15 18:28:50: the model ran `sessions.reset` on its own session.
`session.cleared` fired and the file was wiped — then the aborted turn flushed the
transcript it held in memory and the file came back with 130 messages / 47 cards /
66 injects, so the chat still showed 129 messages and 4% context.

The store now stamps every snapshot it hands out (`_loaded_at`, never persisted) and
records when a session was cleared (`_CLEARED_AT`). A snapshot read BEFORE the clear
is STALE: its messages, tool cards and injects are discarded on EVERY later save
until a new turn reloads the session.

  A1 clear_session empties messages, cards and injects
  A2 the pre-clear snapshot cannot write its transcript back
  A3 the stale flag is sticky (the interrupt note does not come back either)
  A4 a tool card persisted from the stale snapshot is dropped
  A5 a snapshot loaded AFTER the clear appends and saves normally
  A6 a second session is cleared the same way
  A7 the bookkeeping keys never reach the document on disk
  A8 the WebUI reacts to `session.cleared` (log cleared + history reloaded)

Deterministic: temp stores, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1045-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


SID = "aaaaaaaaaaaa"
SID2 = "bbbbbbbbbbbb"


def seed(sid):
    stores.save_session({
        "id": sid, "title": "reset me",
        "messages": [{"role": "user", "content": "one * 40"},
                     {"role": "assistant", "content": "ok"}],
        "tool_cards": [{"tool": "shell.exec"}],
        "injects": [{"kind": "nudge"}],
    }, truncate=True)


def disk(sid):
    try:
        with open(os.path.join(stores.SESSIONS_DIR, sid + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


seed(SID)
before = disk(SID)
check("A0 the fixture has a transcript", len(before.get("messages") or []) == 2, before)

turn_snapshot = stores.load_session(SID)          # what the running turn holds
stores.clear_session(SID)                          # the tool wipes while it runs
after_clear = disk(SID)
check("A1 clear_session empties messages, cards and injects",
      not after_clear.get("messages") and not after_clear.get("tool_cards")
      and not after_clear.get("injects"), after_clear)

# The turn keeps working, then flushes what it holds (the old 130 messages).
turn_snapshot["messages"].append({"role": "assistant",
                                  "content": '{"tool":"sessions.reset"}'})
stores.save_session(turn_snapshot)
after_stale = disk(SID)
check("A2 the pre-clear snapshot cannot write its transcript back",
      not after_stale.get("messages"), after_stale.get("messages"))

turn_snapshot["messages"].append({"role": "assistant", "content": "⏹ Interrupted by the user."})
stores.save_session(turn_snapshot)
check("A3 the stale flag is sticky (the interrupt note does not come back)",
      not disk(SID).get("messages"), disk(SID).get("messages"))

stores.persist_tool_card(turn_snapshot, "shell.exec", True,
                         args={"command": "true"}, result="ok")
check("A4 a tool card persisted from the stale snapshot is dropped",
      not disk(SID).get("tool_cards"), disk(SID).get("tool_cards"))

fresh = stores.load_session(SID)                   # a NEW turn reads after the clear
fresh["messages"].append({"role": "user", "content": "nuova conversazione"})
stores.save_session(fresh)
saved = disk(SID)
check("A5 a snapshot loaded AFTER the clear appends and saves normally",
      [m.get("content") for m in saved.get("messages") or []] == ["nuova conversazione"],
      saved.get("messages"))

seed(SID2)
stores.clear_session(SID2)
check("A6 a second session is cleared the same way",
      not disk(SID2).get("messages") and not disk(SID2).get("tool_cards"),
      disk(SID2))

raw = open(os.path.join(stores.SESSIONS_DIR, SID + ".json"), encoding="utf-8").read()
check("A7 the bookkeeping keys never reach the document on disk",
      "_loaded_at" not in raw and "_stale_after_clear" not in raw, raw[:120])

_web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
check("A8 the WebUI reacts to session.cleared (log cleared + history reloaded)",
      'es.addEventListener("session.cleared"' in _web
      and '$("log").innerHTML = ""; loadHistory(); loadPlan();' in _web
      and '"session.cleared": () => { loadSessions(); if (sessionId) loadHistory(); }' in _web)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
