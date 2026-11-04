#!/usr/bin/env python3
"""v795 — a mid-run STEER is a real user message: visible, durable, never dropped.

Live 2026-11-04 (session `b7329cccf94c`). The operator typed a message while a turn
was running and pushed it as a STEER. The harness answered "it is working", the
message DISAPPEARED from the chat, and the turn then stayed silent for 17 minutes
(a `dispatch` blocks its caller for up to `runtime.dispatch_wait_secs` = 3600 s).

Measured cause — the steer existed in exactly two places, neither of them the
transcript:

  * the in-memory inbox (`steering.STEER_INBOX`), drained ONLY at a loop boundary
    ([agent.py] `drain_steer` in the loop top) — so a blocked loop left the message
    unactioned for 151 s and then for the rest of the turn;
  * the running turn's own context, folded into the session at the END of the turn
    with `internal=True` — and the WebUI SKIPS every internal message
    (`if (m.internal) return;`), so the operator's own words were never rendered.

Proof on disk: message 72 of `b7329cccf94c` is
`[user steering — take it into account now] no e un dispatch parallelo qeusto scemo`
with `role=user`, `internal=True` — present in the file, invisible in the chat, and
absent from the API history until the turn happened to end 7 minutes later.

Locked here:
  * every accepted steer is RECORDED durably, with its own id (two identical
    steers stay two messages);
  * whichever writer saves the session first folds it in as a REAL user message
    (`steer: True`, never `internal`), idempotently — so a stale in-memory copy of
    the session can never drop it (same contract as `adopt_live_choices`);
  * the MODEL-facing copy (`_steer_ctx`) is NOT persisted — one source, no duplicate;
  * `/api/chat/steer` writes it immediately and announces it;
  * a pending steer releases a blocked dispatch instead of waiting it out;
  * the chat renderer draws a `steer` message (it used to skip it).

Deterministic, no model, no network.
Run: python3 tests/acceptance/v795_steer_durable_visible.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v795-")
SESSIONS = os.path.join(TMP, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = SESSIONS
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s            # noqa: E402,F401  (bootstraps)
from longrun.memory import stores as st          # noqa: E402
from longrun.util import steering as steer       # noqa: E402

SID = "v795steer01"

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


# --- A: the durable steer record --------------------------------------------
steer.forget_steers(SID)
check("A1 push_steer still queues for the loop",
      steer.push_steer(SID, "hello steer") == 1 and steer.has_steer(SID) is True)
check("A2 push_steer ALSO records it durably",
      [x.get("text") for x in steer.live_steers(SID)] == ["hello steer"],
      steer.live_steers(SID))
check("A3 draining the inbox does not touch the durable record",
      steer.drain_steer(SID) == ["hello steer"]
      and [x.get("text") for x in steer.live_steers(SID)] == ["hello steer"])
check("A4 an empty steer records nothing", steer.record_steer(SID, "   ") == "")

_id1 = steer.record_steer(SID, "same")
_id2 = steer.record_steer(SID, "same")
check("A5 two IDENTICAL steers stay two messages (own ids)",
      _id1 and _id2 and _id1 != _id2, (_id1, _id2))

# The endpoint mints the id and hands it to push_steer: it must be recorded ONCE.
# (Measured live BEFORE this guard: the endpoint recorded AND push_steer recorded,
# so every steer landed TWICE in the transcript.)
_SID2 = "v795steer02"
steer.forget_steers(_SID2)
steer.push_steer(_SID2, "one", steer_id="abc123")
check("A6 an explicit steer_id is recorded exactly ONCE",
      [x.get("id") for x in steer.live_steers(_SID2)] == ["abc123"],
      steer.live_steers(_SID2))

# --- B: whichever writer saves first folds it in, exactly once --------------
sess = st.get_or_create_session(SID)
st.save_session(sess)
st.save_session(sess)   # idempotent: a second write must not duplicate
_folded = [m for m in sess["messages"] if m.get("steer")]
check("B1 every steer is in the transcript", len(_folded) == 3, len(_folded))
check("B2 they are REAL user messages, never `internal`",
      all(m.get("role") == "user" and not m.get("internal") for m in _folded),
      [(m.get("role"), m.get("internal")) for m in _folded])
check("B3 each carries its own steer_id", len({m.get("steer_id") for m in _folded}) == 3)
check("B4 a second save does not duplicate any of them", len(_folded) == 3)

_persisted = st.load_session(SID)
check("B5 it is on DISK immediately (survives a reload / restart)",
      len([m for m in (_persisted or {}).get("messages", []) if m.get("steer")]) == 3)

# The stale-writer case that made the old fix insufficient: the running turn holds
# its OWN copy of the session and saves LAST. That copy must not be able to drop
# the operator's message.
stale = {"id": SID, "title": "stale", "created": 0, "messages": []}
st.save_session(stale)
check("B6 a STALE in-memory copy cannot drop the steer",
      len([m for m in stale["messages"] if m.get("steer")]) == 3,
      len(stale["messages"]))
check("B7 the stale copy did not resurrect a second transcript",
      len([m for m in st.load_session(SID)["messages"] if m.get("content") == "hello steer"]) == 1)

# --- C: the MODEL-facing copy is tagged and never persisted -----------------
AGENT = src("src", "longrun", "agent", "agent.py")
check("C1 both drains tag the model-facing copy",
      AGENT.count('"_steer_ctx": True') == 2, AGENT.count('"_steer_ctx": True'))
check("C2 the end-of-turn fold SKIPS it",
      'and not _m.get("_steer_ctx")' in AGENT)

_fold_in = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "_steer_ctx": True, "content": "[user steering — now] x"}]
_fold_out = [dict(m, internal=True) for m in _fold_in[2:]
             if isinstance(m, dict) and m.get("role") in ("user", "assistant")
             and not m.get("_steer_ctx")]
check("C3 the fold drops the prefixed copy (no duplicate of the operator's words)",
      _fold_out == [], _fold_out)

# --- D: the endpoint persists and announces --------------------------------
HTTP = src("src", "longrun", "core", "httpapi.py")
check("D1 /api/chat/steer mints the id and queues the steer with it",
      "steer_id = _new_steer_id()" in HTTP
      and "push_steer(sid, text, steer_id=steer_id)" in HTTP)
check("D2 ... and saves the session NOW (not at turn end)", "save_session(_sess)" in HTTP)
check("D3 ... and announces it as a real user message",
      'publish("chat.user", session=sid, text=text, steer=True' in HTTP)
check("D4 ... and answers its id", '"id": steer_id' in HTTP)
check("D5 ... and does NOT also record it (one steer == one message)",
      "_record_steer(sid, text)" not in HTTP)

# --- E: a pending steer releases a blocked dispatch -------------------------
check("E1 the dispatch wait is sliced, not one long join",
      "_t.join(_dispatch_wait())" not in AGENT and "while _waited < _wait:" in AGENT)
check("E2 it breaks on a pending steer", 'if _ddone.is_set() or has_steer(sess["id"]):' in AGENT)

# --- F: the renderer draws a steer message ----------------------------------
HTML = src("webui", "index.html")
check("F1 a steer message is rendered with its label",
      'm.steer ? "🎯 steer: " + _sp.rest' in HTML)
check("F2 internal messages are still skipped for everything else",
      "if (m.internal) return;" in HTML)

# --- G: no runtime leak (v302 stays true) -----------------------------------
steer.forget_steers(SID)
check("G1 forget_steers drops the record (delete path)",
      steer.live_steers(SID) == [] and SID not in steer.STEER_LOG)
check("G2 the delete path forgets the steer log",
      "forget_steers(sid)" in src("src", "longrun", "memory", "stores.py"))

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
