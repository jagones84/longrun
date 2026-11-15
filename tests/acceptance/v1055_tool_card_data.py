#!/usr/bin/env python3
"""v1055 — a tool card can carry a structured `data` payload.

`persist_tool_card(data=...)` stores it INSIDE the card (never in `messages`, so
it cannot reach the model prompt), capped at 6 000 serialised chars; the live
`tool.result` event carries the same object, so the live card and the reloaded
card render through one function.

  A1 a small payload is stored and survives a reload
  A2 the payload never appears in `messages` (no prompt cost)
  A3 an oversized payload is dropped, the card still persists
  A4 a non-dict payload is ignored
  A5 `_tool_event` forwards `data` verbatim
  A6 the second card keeps its own payload (no shared mutable state)
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1055-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores as S  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


SID = "dddddddddddd"
sess = S.get_or_create_session(SID, title="v1055")
small = {"action": "search", "engine": "tavily", "duration_ms": 12,
         "groups": [{"query": "q", "engine": "tavily",
                     "results": [{"id": "w1", "title": "t", "url": "https://x/y",
                                  "host": "x", "snippet": "s"}]}]}
card = S.persist_tool_card(sess, "web.search", True, args={"query": "q"},
                           result="1. t", data=small)
check("A1a card carries data", card is not None and card.get("data") == small)
on_disk = (S.load_session(SID) or {}).get("tool_cards") or []
check("A1b data survives a reload",
      bool(on_disk) and on_disk[-1].get("data", {}).get("groups", [{}])[0].get("query") == "q")

check("A2 messages untouched", sess.get("messages") == []
      and "action" not in json.dumps(sess.get("messages") or []))

big = {"action": "search", "blob": "x" * 7000}
card2 = S.persist_tool_card(sess, "web.search", True, args={}, result="r", data=big)
check("A3a oversized data dropped", card2 is not None and "data" not in card2)
check("A3b card still persisted", (S.load_session(SID) or {}).get("tool_cards")[-1]["tool"] == "web.search")

card3 = S.persist_tool_card(sess, "web.fetch", True, args={}, result="r", data="not-a-dict")
check("A4 non-dict ignored", card3 is not None and "data" not in card3)

ev = S._tool_event("web.search", True, args={"query": "q"}, output="1. t", data=small)
check("A5 event forwards data", ev.get("data") == small and ev.get("tool") == "web.search")

third = {"action": "fetch", "pages": [{"url": "https://a", "ok": True}]}
S.persist_tool_card(sess, "web.fetch", True, args={}, result="r", data=third)
cards = (S.load_session(SID) or {}).get("tool_cards") or []
check("A6 per-card payloads stay separate",
      cards[-1].get("data") == third and cards[-2].get("data") is None)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
