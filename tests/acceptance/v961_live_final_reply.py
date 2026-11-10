#!/usr/bin/env python3
"""v961 — the session shows EVERYTHING that happens, live (not only after a reload).

Operator, 2026-11-11: *"in sessione devo vedere tutto quello che succede, non è che le
cose compaiono"*. The transcript was faithful; the LIVE chat was not. The streamed
`chat.delta`s carry the model's own words, while the reply that gets PERSISTED is
sometimes synthesised after the stream ends: a `human.ask` stop, a goal stopped
incomplete, a JSON action replaced by a summary, an empty turn. The WebUI does not
reload the chat on `done`, so those texts existed only in the session, and appeared
in the chat only after a manual reload.

Now `chat.final` carries the stored reply; the client replaces the open answer's text
with it (or appends a bubble when the turn produced no answer at all), and the HITL
card stays the one owner of its stop.

Locks:
  A  the canonical reply is announced from ONE place, after the message is stored;
  B  the event carries the session, the text and the HITL flag (so the card is not
     duplicated), and a failing sink never breaks the turn;
  C  a re-attached stream replays it (`_ATTACH_KINDS`);
  D  the client applies it once: in place, deduped, and only one stream owns the
     bubble; the feed handles a turn this tab does not stream.

Deterministic: a collector sink, source pins, no server, no model, no network.
Run: python3 tests/acceptance/v961_live_final_reply.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v961-")
for _k in ("DATA_DIR", "SESSIONS_DIR", "GRAPH_DIR", "CONFIG_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order: agent needs it)
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=None):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


AGENT = read("src/longrun/agent/agent.py")
HTTP = read("src/longrun/core/httpapi.py")
GUI = read("webui/index.html")

# --- A: one owner, after the store -------------------------------------------
check("A1 the canonical reply has one announcer", hasattr(A, "_emit_final_reply"))
_call = AGENT.index("_emit_final_reply(on_event, sess, content, _hitl")
_append = AGENT.index('reply = append_message(sess, "assistant", content')
check("A2 ... called ONCE, right after the reply is stored", AGENT.count("_emit_final_reply(") == 2
      and _call > _append)
check("A3 it names the event `chat.final`", 'on_event("chat.final"' in AGENT)

# --- B: the payload ---------------------------------------------------------
seen = []
A._emit_final_reply(lambda kind, **d: seen.append((kind, d)),
                    {"id": "s1"}, "the stored reply", {"reason": "asked"},
                    node="n7", ts=12.5)
kind, payload = (seen or [("", {})])[0]
check("B1 the event is `chat.final` for THIS session", kind == "chat.final"
      and payload.get("session") == "s1")
check("B2 it carries the exact stored text", payload.get("text") == "the stored reply")
check("B3 it flags a HITL stop and its reason",
      payload.get("hitl") is True and payload.get("reason") == "asked")
check("B4 a normal turn is not flagged as HITL",
      (seen.clear() or A._emit_final_reply(lambda k, **d: seen.append((k, d)),
                                           {"id": "s1"}, "plain", None) is None)
      and bool(seen) and seen[0][1].get("hitl") is False)
seen.clear()
try:
    A._emit_final_reply(lambda kind, **d: (_ for _ in ()).throw(RuntimeError("sink down")),
                        {"id": "s1"}, "x", None)
    _survived = True
except Exception:  # noqa: BLE001
    _survived = False
check("B5 a failing sink never breaks the turn", _survived)

# --- C: a re-attached stream replays it --------------------------------------
check("C1 chat.final is in the re-attach kinds",
      '"chat.run", "chat.delta", "chat.done", "chat.user", "chat.final",' in HTTP)

# --- D: the client applies it once ------------------------------------------
_apply = GUI[GUI.index("function _applyFinalReply(d)"):GUI.index("function _resetChatTree()")]
check("D1 it filters by session", "d.session !== sessionId" in _apply)
check("D2 a HITL stop is left to the card", "if (d.hitl) return;" in _apply)
check("D3 the open answer is replaced IN PLACE",
      "curAns.querySelector(\".bubble\")" in _apply and "renderAnswerBubble(b)" in _apply)
check("D4 a turn with no answer still shows one", 'who("ai", t, d.ts || null)' in _apply)
check("D5 the feed's echo never doubles the bubble",
      "=== t.trim()) return;" in _apply)
_turn = GUI[GUI.index('es.addEventListener("chat.final"'):GUI.index('es.addEventListener("chat.final"') + 300]
check("D6 the turn stream applies it under `live()`", "if (!live()) return;" in _turn)
_feed = GUI[GUI.index('// 2026-11-11: the canonical reply of a turn this tab does not stream'):
            GUI.index('// 2026-11-11: the canonical reply of a turn this tab does not stream') + 500]
check("D7 the feed applies it only when no turn stream owns the session",
      "if (turnSSE[sessionId]) return;" in _feed)

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
