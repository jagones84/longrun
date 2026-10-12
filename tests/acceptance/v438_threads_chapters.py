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
n1 = taskgraph.add_node(g, "search the docs", status="todo")
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

# ---- 5. tool registration + policy -------------------------------------------
names = {t["name"] for t in registry.catalog() if t.get("name")}
check("5a chapters is a registered base tool", "chapters" in names)
check("5b chapters declares the 3 actions",
      (registry.TOOL_SCHEMAS.get("chapters") or {}).get("properties", {}).get("action", {}).get("enum")
      == ["list", "read", "title"])
check("5c chapters is approval=auto (read-only + its own ledger)",
      (registry.tool_spec("chapters") or {}).get("approval") == "auto")

# ---- 6. WebUI + API wiring ---------------------------------------------------
idx = _read("webui/index.html")
check("6a the 🏷 button exists next to the group controls", 'data-call="nameThreads"' in idx)
check("6b the button asks the agent for a REAL turn via send()",
      "function nameThreads(" in idx and "chapters` tool" in idx)
check("6c Free groups carry a stable chapter slot", 'det.dataset.chapter = "free#"' in idx)
check("6d titles are read from the ledger", "loadThreadTitles" in idx and "/api/threads?session=" in idx)
http = _read("src/longrun/core/httpapi.py")
check("6e GET /api/threads is routed", '"/api/threads"' in http and "threads_mod.outline" in http)

print("---")
okc = sum(results)
print("\nv438: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
