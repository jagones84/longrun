#!/usr/bin/env python3
"""v485 — a compaction must trim the UI transcript, not only `messages` (JAG-485).

The WebUI transcript is the merge of three stores: `messages`, `tool_cards` and
`injects`. `compact_session` rewrote the first one only, so after a compaction a
reload replayed every card/inject of the compacted-away turns — the whole old chat
came back — and each card carrying a todo `node` re-opened that todo section (the
same 4 todos painted 4 times). This drives the REAL manual compaction and asserts
that the artifacts of the summarized region are dropped and the survivors are
re-anchored onto their message in the NEW list.

It also source-locks the two WebUI halves of the same report:
  * `loadHistory` is generation-guarded and clears the log, so the boot load and
    the `chat.done` feed-backlog replay can no longer paint the transcript twice;
  * a replayed compaction SUMMARY is labelled `compacted history` with NO fake
    "now" timestamp (it is the head of the retained window, not a live event).

Run: python3 tests/acceptance/v485_compaction_transcript.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v485-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores            # noqa: E402
from longrun.core import server as _srv      # noqa: E402,F401  (httpapi<->server import order)
from longrun.core import httpapi             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- 1. a session whose transcript carries cards + injects -------------------
sid = "v485-sess"
stores.save_session({"id": sid, "title": "v485", "created": time.time(), "messages": []})
sess = stores.load_session(sid)
for i in range(10):
    stores.append_message(sess, "user" if i % 2 == 0 else "assistant", "message %d" % i)

# artifacts of the OLD (to-be-summarized) region and of the KEPT tail
stores.persist_tool_card(sess, "shell", True, args={"command": "old-1"}, result="old", after=1)
stores.persist_tool_card(sess, "fs.read", True, result="old", node="n1", after=3)
stores.persist_tool_card(sess, "shell", True, result="keep", node="n3", after=9)
stores.persist_tool_card(sess, "shell", True, result="tail", after=10)
stores.persist_tool_card(sess, "shell", True, result="ghost", after=99)   # anchor past the end
stores.persist_inject(sess, "nudge", "old nudge a", node="n1", after=2)
stores.persist_inject(sess, "observation", "old obs", node="n2", after=4)
stores.persist_inject(sess, "nudge", "kept nudge", node="n3", after=10)
stores.persist_inject(sess, "nudge", "tail nudge", after=10)
stores.persist_inject(sess, "nudge", "no anchor", after=None)
stores.save_session(sess)

before = stores.load_session(sid)
check("1a the fixture has 10 messages and 5 cards + 5 injects",
      len(before["messages"]) == 10 and len(before["tool_cards"]) == 5
      and len(before["injects"]) == 5,
      (len(before["messages"]), len(before["tool_cards"]), len(before["injects"])))

# ---- 2. the REAL manual compaction -------------------------------------------
httpapi._summarize_with_llm = lambda messages, model=None, meta=None: None
stats = httpapi.compact_session(sid)
after = stores.load_session(sid)
n = len(after["messages"])
check("2a the transcript really shrank", stats.get("compacted", 0) > 0 and n < 10,
      (n, stats.get("compacted"), stats.get("kept")))
kept = int(stats.get("kept") or 0)
cut = 10 - kept
check("2b the summary is the head of the retained window",
      after["messages"][0]["role"] == "system"
      and str(after["messages"][0]["content"]).startswith("Earlier conversation (compacted):"),
      str(after["messages"][0]["content"])[:50])

# ---- 3. UI artifacts follow the same horizon ---------------------------------
cards = after.get("tool_cards") or []
injs = after.get("injects") or []
check("3a cards of the summarized region are GONE",
      not any(c.get("result") in ("old", "old") and c.get("args") for c in cards)
      and all(c.get("result") != "old" for c in cards),
      [(c.get("tool"), c.get("after"), c.get("result")) for c in cards])
check("3a2 an anchor past the end of the transcript is dropped as stale",
      not any(c.get("result") == "ghost" for c in cards),
      [(c.get("result"), c.get("after")) for c in cards])
check("3b injects of the summarized region are GONE",
      not any(str(r.get("text")) in ("old nudge a", "old obs") for r in injs),
      [(r.get("kind"), r.get("after")) for r in injs])
check("3c the kept tail artifacts SURVIVE with their todo node",
      any(c.get("result") == "keep" and c.get("node") == "n3" for c in cards)
      and any(c.get("result") == "tail" for c in cards)
      and any(r.get("text") == "kept nudge" and r.get("node") == "n3" for r in injs),
      ([c.get("result") for c in cards], [r.get("text") for r in injs]))
check("3d every survivor is re-anchored inside the NEW transcript (0 < after <= %d)" % n,
      all(isinstance(x.get("after"), int) and 0 <= x.get("after") <= n for x in cards + injs),
      [(x.get("after")) for x in cards + injs])
check("3e the tail compaction marker is present at the end",
      any(r.get("kind") == "compact" and r.get("after") == n for r in injs),
      [(r.get("kind"), r.get("after")) for r in injs])
check("3f an unanchored artifact (after=None) is kept and anchored at the tail",
      any(str(r.get("text")) == "no anchor" and r.get("after") == n for r in injs),
      [(r.get("text"), r.get("after")) for r in injs])
check("3g cut arithmetic is the one loadHistory uses", cut == 8,
      "cut=%d kept=%d" % (cut, kept))

# ---- 4. the WebUI halves ------------------------------------------------------
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("4a loadHistory is generation-guarded and clears the log FIRST",
      "let _historySeq = 0;" in ui
      and "const _gen = ++_historySeq;" in ui
      and "const _stale = () => _gen !== _historySeq" in ui
      and '$("log").innerHTML = ""; curThink = curAns = null; _resetChatTree();\n  _historyReplaySession'
      in ui)
check("4b every await in loadHistory re-checks the generation",
      ui.count("if (_stale()) return;") >= 3)
check("4c a replayed summary is labelled 'compacted history' with no fake timestamp",
      'inject_kind: "compacted history"' in ui and "d.ts === null ? \"\" : _tsSpan(d.ts)" in ui)

print("---")
okc = sum(results)
print("\nv485: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
