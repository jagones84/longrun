#!/usr/bin/env python3
"""v438 — the session THREAD ledger + the `chapters` tool (JAG-431j).

A long session's chat is a stream of GROUPS: TASK groups (todo nodes) and FREE
groups ("Free.N" — chat with no todo behind them). Compaction rewrites the stored
transcript IN PLACE, so the prose of an old free thread is destroyed and the agent
can no longer read it — even though the operator still sees it in the WebUI.

This pins the fix: `memory/threads.py` keeps a durable per-session ledger, written by
`stores` BEFORE compaction can touch the transcript, and the `chapters` tool reads it
(list / read / title). Deterministic, no live server.

Run: python3 tests/acceptance/v438_threads_chapters.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v438-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores            # noqa: E402
from longrun.memory import threads as th     # noqa: E402
from longrun.plan import taskgraph           # noqa: E402
from longrun.tools import registry           # noqa: E402
from longrun.tools import tools as T         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(path):
    with open(os.path.join(REPO, path), "r", encoding="utf-8") as f:
        return f.read()


# ---- 1. the ledger is derived from the persisted stream ----------------------
sid = "v438-sess-1"
stores.save_session({"id": sid, "title": "t", "created": time.time(), "messages": []})
sess = stores.load_session(sid)
g = taskgraph.ensure(sid)
n1 = taskgraph.add_node(g, "search the docs", status="done",
                        evidence="ran the search; 3 hits recorded")
taskgraph.save(g)

stores.append_message(sess, "user", "free chat one opener")
stores.append_message(sess, "assistant", "sure, answering")
stores.append_message(sess, "assistant", "working on it", meta={"node": n1["id"]})
stores.persist_tool_card(sess, "shell", True, args={"command": "ls"}, result="x", node=n1["id"])
stores.append_message(sess, "user", "second free thread")
stores.append_message(sess, "assistant", "ok second")

groups = th.outline(sid)
kinds = [x["kind"] for x in groups]
check("1a groups derived from the stream", len(groups) == 3, kinds)
check("1b order is chronological free/task/free", kinds == ["free", "task", "free"], kinds)
check("1c a free group opens on a user turn", groups[0]["kind"] == "free" and groups[0]["items"] >= 2)
check("1d a task group carries its node", any(x["kind"] == "task" and x["node"] == n1["id"] for x in groups))
check("1e free groups captured a digest", all(x["digest"] for x in groups if x["kind"] == "free"),
      [x["digest"][:24] for x in groups])
check("1f a free group records the user REQUEST + its rewind index (JAG-431m)",
      (groups[0].get("req") or "").startswith("free chat one opener")
      and groups[0].get("req_from") == 0,
      (groups[0].get("req"), groups[0].get("req_from")))

# ---- 2. the ledger is INDEPENDENT of the (compactable) transcript ------------
sess = stores.load_session(sid)
sess["messages"] = []           # simulate compaction destroying the prose
sess["tool_cards"] = []
sess["injects"] = []
stores.save_session(sess)
survivors = th.outline(sid)
check("2a groups survive a transcript wipe (compaction-proof)",
      len(survivors) == len(groups) and [x["kind"] for x in survivors] == kinds,
      (len(survivors), len(groups)))

# ---- 3. backfill for a session that predates the ledger ----------------------
sid2 = "v438-sess-old"
stores.save_session({"id": sid2, "title": "old", "created": time.time(), "messages": [
    {"role": "user", "content": "backfilled free one", "ts": time.time()},
    {"role": "assistant", "content": "reply", "ts": time.time() + 0.01},
]})
bf = th.outline(sid2)
check("3a backfill derives groups from the transcript",
      len(bf) == 1 and bf[0]["kind"] == "free" and "backfilled free one" in bf[0]["digest"], bf)

# ---- 4. the `chapters` tool: list / read / title -----------------------------
free = [x for x in groups if x["kind"] == "free"]
fid = free[0]["id"]
task = [x for x in groups if x["kind"] == "task"][0]
r = T.execute("chapters", {"session": sid, "action": "list"}, run_id=sid)
check("4a list -> the whole thread with ids", r.get("ok") is True and ("id=%s" % fid) in r.get("stdout", ""),
      (r.get("stdout") or "")[:80])
r = T.execute("chapters", {"session": sid, "action": "read", "id": fid}, run_id=sid)
check("4b read -> a group's preserved content", r.get("ok") is True and "free chat one opener" in r.get("stdout", ""),
      (r.get("stdout") or "")[:80])
r = T.execute("chapters", {"session": sid, "action": "title", "id": fid, "title": "Opener"}, run_id=sid)
check("4c title -> sets a FREE group's title", r.get("ok") is True and th.get(sid, fid)["title"] == "Opener")
r = T.execute("chapters", {"session": sid, "action": "title", "id": task["id"], "title": "nope"}, run_id=sid)
check("4d a TASK group refuses a title (todos keep their node label)", r.get("ok") is False)
check("4e read of an unknown id is refused",
      T.execute("chapters", {"session": sid, "action": "read", "id": "gZZ"}, run_id=sid).get("ok") is False)
check("4f the title survives a transcript wipe", th.get(sid, fid)["title"] == "Opener")
r = T.execute("chapters", {"session": sid, "action": "read", "id": fid}, run_id=sid)
check("4g read surfaces the request line", "request: free chat one opener" in (r.get("stdout") or ""),
      (r.get("stdout") or "")[:70])
r = T.execute("chapters", {"session": sid, "action": "title", "id": fid,
                           "title": "Opener", "summary": "asked for a free chat; answered"},
              run_id=sid)
check("4h title + summary (justification) are stored",
      r.get("ok") is True and (th.get(sid, fid).get("summary") or "").startswith("asked for a free chat"))
r = T.execute("chapters", {"session": sid, "action": "read", "id": fid}, run_id=sid)
check("4i read returns the title + summary",
      "summary: asked for a free chat" in (r.get("stdout") or "")
      and "title: Opener" in (r.get("stdout") or ""), (r.get("stdout") or "")[:80])
r = T.execute("chapters", {"session": sid, "action": "list"}, run_id=sid)
check("4j list carries a TODO's justification (its evidence)",
      "why: \u201cran the search" in (r.get("stdout") or ""), (r.get("stdout") or "")[:0])
r = T.execute("chapters", {"session": sid, "action": "read", "id": task["id"]}, run_id=sid)
check("4k read shows a todo's evidence as its justification",
      "justification (evidence)" in (r.get("stdout") or "")
      and "ran the search; 3 hits recorded" in (r.get("stdout") or ""))

# ---- 5. tool registration + policy -------------------------------------------
names = {t["name"] for t in registry.catalog() if t.get("name")}
check("5a chapters is a registered base tool", "chapters" in names)
check("5b chapters declares the 3 actions",
      (registry.TOOL_SCHEMAS.get("chapters") or {}).get("properties", {}).get("action", {}).get("enum")
      == ["list", "read", "title"])
check("5c chapters is approval=auto (read-only + its own ledger)",
      (registry.tool_spec("chapters") or {}).get("approval") == "auto")
check("5d the schema exposes a summary for a free group's justification",
      "summary" in ((registry.TOOL_SCHEMAS.get("chapters") or {}).get("properties") or {}))

# ---- 6. WebUI + API wiring ---------------------------------------------------
idx = _read("webui/index.html")
check("6a the 🏷 button exists next to the group controls", 'data-call="nameThreads"' in idx)
check("6b the button asks the agent for a REAL turn via send()",
      "function nameThreads(" in idx and "chapters` tool" in idx)
check("6c Free groups carry a stable chapter slot", 'det.dataset.chapter = "free#"' in idx)
check("6d titles are read from the ledger", "loadThreadTitles" in idx and "/api/threads?session=" in idx)
http = _read("src/longrun/core/httpapi.py")
check("6e GET /api/threads is routed", '"/api/threads"' in http and "threads_mod.outline" in http)

# ---- 7. naming style + per-free-thread rewind (JAG-431m) ---------------------
_desc = (registry.TOOL_SCHEMAS.get("chapters") or {}).get("description", "")
check("7a the tool teaches the 'request to …' title style", "request to <short ask>" in _desc, _desc[-60:])
check("7b the 🏷 prompt asks for 'request to <ask>' titles",
      "request to <summary of the user's ask>" in idx)
check("7c free groups carry a rewind control",
      'class="fgroup-rw"' in idx and "function rewindFreeGroup(" in idx)
check("7d the free rewind reuses the per-turn rewind API",
      "doRewind(sessionId, rf)" in idx)
check("7e the ledger render says every group carries its justification",
      "carries its justification" in _read("src/longrun/memory/threads.py"))

# ---- 8. an older-schema ledger is rebuilt on read (version upgrade) -----------
import json as _json   # noqa: E402
with open(th.path_for(sid2), "w", encoding="utf-8") as f:
    _json.dump({"session": sid2, "seq": 1, "groups": [
        {"id": "g1", "kind": "free", "node": None, "from": 0, "to": 1,
         "items": 2, "title": "stale", "digest": "stale"}]}, f)
up = th.outline(sid2)
check("8a a pre-version ledger is rebuilt with the new fields",
      bool(up) and up[0].get("req_from") == 0 and "backfilled free one" in (up[0].get("req") or ""),
      up)
check("8b a schema rebuild PRESERVES an agent-set title (no silent loss)",
      bool(up) and up[0].get("title") == "stale", (up[0].get("title") if up else None))

# ---- 9. titles/summaries RIDE the message (JAG-431p) -------------------------
# The WebUI labels a free group from the CHAPTER metadata carried by the message that
# STARTS it, so the label travels with the transcript and survives compaction — it must
# never depend on an ordinal (the rendered and ledger free-group sequences diverged).
sid3 = "v438-sess-chapter"
stores.save_session({"id": sid3, "title": "c", "created": time.time(), "messages": []})
s3 = stores.load_session(sid3)
stores.append_message(s3, "user", "please chapter me")   # opens a free group, req_from=0
stores.append_message(s3, "assistant", "done")
g3 = th.outline(sid3)[0]
T.execute("chapters", {"session": sid3, "action": "title", "id": g3["id"],
                       "title": "request to chapter me", "summary": "asked to be chaptered"},
          run_id=sid3)
stores.save_session(s3)          # the single choke point mirrors the ledger -> transcript
s3b = stores.load_session(sid3)
ch = (s3b["messages"][0] or {}).get("chapter") or {}
check("9a a titled free group's chapter lands on its START message",
      ch.get("title") == "request to chapter me" and ch.get("gid") == g3["id"], ch)
check("9b the chapter carries the summary (the free-tier justification)",
      (ch.get("summary") or "").startswith("asked to be chaptered"), ch)
check("9c the chapter carries the rewind anchor", ch.get("req_from") == 0, ch)

# A STALE anchor (the message at that index no longer matches the group's request) must
# NEVER label an unrelated message: sync re-finds the group by content, or skips.
s3b["messages"][0]["content"] = "completely different text"
s3b["messages"][0].pop("chapter", None)
th.sync_chapters(s3b)
check("9d a stale anchor never labels an unrelated message",
      not (s3b["messages"][0].get("chapter")), s3b["messages"][0].get("chapter"))
check("9e sync_chapters is idempotent (0 changes when nothing moved)",
      th.sync_chapters(s3b) == 0)

# ---- 10. the WebUI labels by chapter, not by ordinal -------------------------
check("10a a TASK item closes the free group (render sequence == ledger)",
      "a TASK item CLOSES the current free group" in idx)
check("10b free groups are labelled from chapter metadata (ledger fallback kept)",
      "function _freeMeta(" in idx and "chapter.title || lg.title" in idx)
check("10c the ordinal-only label helper is gone", "function _freeLabel(" not in idx)
check("10d loadHistory hands the chapter to the renderer",
      "who(\"user\", m.content, m.ts, m.sender, m.subjob, m.chapter)" in idx
      and "who(\"ai\", reply, m.ts, null, null, m.chapter)" in idx)
check("10e the free-group summary is shown on the group header",
      'class="fgsum"' in idx and ".fgroup .fgsum" in idx)
check("10f the per-free rewind uses the chapter's anchor (with a ledger fallback)",
      "function rewindFreeGroup(" in idx and "st.req_from" in idx)

print("---")
okc = sum(results)
print("\nv438: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
