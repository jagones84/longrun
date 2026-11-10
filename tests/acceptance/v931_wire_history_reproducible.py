#!/usr/bin/env python3
"""v931 — the sent history is reproducible, so the provider can reuse its prefix.

Measured 2026-11-10 on session `b7329cccf94c` (733 calls): the FIRST model call of
every turn came back **100% uncached** (median; 27 of 42 turns above 30%), while the
calls after it inside the same turn were 2.2%. The cause was structural, not the
provider: the turn is SENT augmented (memory index + live task list + retrieved
memories) but the transcript STORES the raw user text, so turn N's history never
matched what turn N-1 sent — and the whole transcript was re-prefilled every turn.

Modern harnesses keep the conversation append-only and put volatile text LAST in the
turn, precisely so the cached prefix keeps growing instead of being rewritten
(Anthropic/OpenAI caching docs; Leyline, arXiv:2606.01065 — identical content moving
position between turns invalidates exact-prefix caches).

  A) `wire_content` is the ONE accessor: sent text when recorded, raw text otherwise;
  B) the user turn records the EXACT text it was sent with (`wire`), nothing else;
  C) the next turn rebuilds that message from `wire` — byte-identical to what the
     provider already holds;
  D) the retrieved-memory block rides the user turn, never between the system prompt
     and the transcript (it changes with the query, so there it broke everything);
  E) the context meter counts what is carried (`wire`), not the display text.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v931-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402
from longrun.model import context_engine       # noqa: E402

results = []
SID = "931c7d1d0e66"
STATE_MARK = "Harness state (your persistent task list):"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. the accessor -------------------------------------------------------
check("A1 the SENT text wins when it was recorded",
      context_engine.wire_content({"content": "raw", "wire": "sent"}) == "sent")
check("A2 no wire -> the raw text (old sessions keep working)",
      context_engine.wire_content({"content": "raw"}) == "raw"
      and context_engine.wire_content({"content": "raw", "wire": ""}) == "raw")
check("A3 a non-dict message passes through untouched",
      context_engine.wire_content("plain") == "plain"
      and context_engine.wire_content(None) is None)

# ---- B/C. one turn records the wire, the next turn re-sends it -------------
sess = {"id": SID, "messages": [{"role": "user", "content": "first ask"}],
        "created": 1.0, "workspace": os.path.join(TMP, "ws")}
os.makedirs(sess["workspace"], exist_ok=True)

_cap = {}
_orig_build = context_engine.build


def _fake_build(system_prompt, messages, message=None, **kw):
    _cap["msgs"] = ([{"role": "system", "content": system_prompt}] + list(messages)
                    + ([{"role": "user", "content": message}] if message else []))
    return list(_cap["msgs"]), {}


context_engine.build = _fake_build
try:
    msgs1, _ = agent.assemble_turn(sess, "first ask", tool_ctx={})
finally:
    context_engine.build = _orig_build

stored = sess["messages"][-1]
check("B1 the user turn records the EXACT text it was sent with",
      isinstance(stored.get("wire"), str) and stored["wire"] == msgs1[-1]["content"],
      repr(stored.get("wire"))[:80])
check("B2 that text is the augmented one (the state block rode with it)",
      STATE_MARK in (stored.get("wire") or "") and stored.get("content") == "first ask")
check("B3 the DISPLAY text is untouched (the chat still shows the operator's words)",
      stored["content"] == "first ask")

sess["messages"].append({"role": "assistant", "content": "answer 1"})
sess["messages"].append({"role": "user", "content": "second ask"})
context_engine.build = _fake_build
try:
    msgs2, _ = agent.assemble_turn(sess, "second ask", tool_ctx={})
finally:
    context_engine.build = _orig_build

check("C1 turn 2 re-sends turn 1's user message BYTE FOR BYTE (the cacheable prefix)",
      {"role": msgs2[1].get("role"), "content": msgs2[1].get("content")}
      == {"role": msgs1[1].get("role"), "content": msgs1[1].get("content")},
      [msgs2[1].get("role"), len(str(msgs2[1].get("content"))),
       len(str(msgs1[1].get("content")))])
check("C2 the system prompt is unchanged between the two turns",
      msgs2[0] == msgs1[0])
check("C3 the NEW turn is still the operator's text plus the volatile blocks",
      (msgs2[-1].get("content") or "").startswith("second ask")
      and STATE_MARK in (msgs2[-1].get("content") or ""))
check("C4 only USER turns carry a wire — an assistant turn is never rewritten",
      all("wire" not in m for m in sess["messages"] if m.get("role") == "assistant")
      and "wire" in sess["messages"][0])

# ---- D. the retrieved-memory block rides the USER turn --------------------
_orig_retrieve = context_engine.retrieve
context_engine.retrieve = lambda query, workspace=None: [
    {"mid": "m1", "kind": "memory.store", "score": 0.9,
     "content": "the operator prefers terse answers"}]
try:
    _m, _st = context_engine.build("SYS", [{"role": "user", "content": "old"},
                                           {"role": "assistant", "content": "a"}],
                                   "what now?", retrieve_memory=True)
finally:
    context_engine.retrieve = _orig_retrieve
_sys = [m for m in _m if m.get("role") == "system"]
check("D1 no retrieved block is inserted between the prompt and the transcript",
      len(_sys) == 1 and "Relevant memories" not in (_sys[0].get("content") or ""),
      [m.get("role") for m in _m])
check("D2 the LAST user turn carries it",
      "Relevant memories" in (_m[-1].get("content") or "")
      and _m[-1]["role"] == "user" and _st.get("retrieved_memories") == 1)

# ---- E. the meter counts what is carried ----------------------------------
server.save_session(sess)
from longrun.core import httpapi               # noqa: E402
_u = httpapi.context_usage(SID, "third ask", model=None)
_wire_tokens = sum(context_engine.count_tokens(context_engine.wire_content(m))
                   for m in sess["messages"])
_raw_tokens = sum(context_engine.count_tokens(m.get("content", ""))
                  for m in sess["messages"])
check("E1 the meter reports the transcript the provider holds (wire), not the display text",
      int(_u.get("transcript_tokens") or 0) == _wire_tokens and _wire_tokens > _raw_tokens,
      "%s vs wire=%s raw=%s" % (_u.get("transcript_tokens"), _wire_tokens, _raw_tokens))
_items = httpapi.context_items(SID)
check("E2 the panel attributes the same transcript it counts",
      int((_items or {}).get("tokens_total") or 0) > 0)

# ---- F. no wire, no change -------------------------------------------------
sess2 = {"id": "931c7d1d0e67", "messages": [{"role": "user", "content": "plain"}],
         "created": 1.0}
server.save_session(sess2)
_u2 = httpapi.context_usage("931c7d1d0e67", "next", model=None)
check("F1 a session without wire keeps the previous behaviour",
      int(_u2.get("transcript_tokens") or 0)
      == context_engine.count_tokens("plain"), _u2.get("transcript_tokens"))

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
