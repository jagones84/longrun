#!/usr/bin/env python3
"""v958 — the retired session identity is gone, and the data follows it.

Operator, 2026-11-11: *"longrunagent deve sparire dalla faccia della terra"*.

Locks:
  A  the CODE names it in exactly ONE place — the migration constants in
     `agent/architect.py`; no module, config file or WebUI file spells it;
  B  the MIGRATION renames and rewrites the data home: session file, graphs,
     agent registry key, tombstones, workspaces dir and event rows;
  C  message PROSE is never rewritten — only identifier fields;
  D  the migration is idempotent (a second call is a no-op).

Deterministic: temp data home, no server, no model, no network.
Run: python3 tests/acceptance/v958_identity_migration.py
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v958-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "workspaces")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in (os.path.join(TMP, "sessions"), os.path.join(TMP, "graphs"),
          os.path.join(TMP, "workspaces")):
    os.makedirs(d, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import architect as LRA        # noqa: E402
from longrun.core import events as EV             # noqa: E402

OLD = LRA._LEGACY_SESSION_ID
NEW = LRA.ARCHITECT_SESSION_ID
results = []


def check(name, ok, detail=None):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- fixture: a data home written by the retired identity --------------------
_sess = {"id": OLD, "title": LRA._LEGACY_TITLE, LRA._LEGACY_FIELD: True,
         "messages": [{"role": "user", "content": "the note says " + OLD + " in prose"}]}
with open(os.path.join(TMP, "sessions", OLD + ".json"), "w", encoding="utf-8") as f:
    json.dump(_sess, f)
with open(os.path.join(TMP, "sessions", OLD + ".json.bak-1"), "w", encoding="utf-8") as f:
    json.dump({"id": OLD}, f)
with open(os.path.join(TMP, "graphs", OLD + "_run_abc.json"), "w", encoding="utf-8") as f:
    json.dump({"session": OLD + "_run_abc", "nodes": []}, f)
with open(os.path.join(TMP, "agents.json"), "w", encoding="utf-8") as f:
    json.dump({"seq": 1, "agents": {OLD: {"id": "A1", "n": 1, "session": OLD,
                                          "kind": "session", "name": "Architect"}}}, f)
with open(os.path.join(TMP, "sessions", ".deleted"), "w", encoding="utf-8") as f:
    f.write("other-session\n" + OLD + "\n")
os.makedirs(os.path.join(TMP, "workspaces", OLD), exist_ok=True)

conn = sqlite3.connect(EV.DB_PATH)
conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)")
conn.execute("INSERT INTO events (ts, kind, data) VALUES (?,?,?)",
             (1.0, LRA._LEGACY_KIND + "done",
              json.dumps({"session": OLD, "by": OLD + "_1"})))
conn.execute("INSERT INTO events (ts, kind, data) VALUES (?,?,?)",
             (2.0, "chat.user", json.dumps({"session": "s-1",
                                            "text": "quote about " + OLD + " kept"})))
conn.commit()
conn.close()

# --- A: the code spells it once ---------------------------------------------
_hits = []
for root in ("src", "webui", "config"):
    for dirpath, _dirs, files in os.walk(os.path.join(REPO, root)):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith((".py", ".yaml", ".yml", ".html", ".js", ".css", ".json")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if OLD in text or "longrun_agent" in text or "longrun-agent" in text:
                _hits.append(os.path.relpath(p, REPO))
check("A1 exactly ONE file still names the retired identity (the migration)",
      _hits == [os.path.join("src", "longrun", "agent", "architect.py")], _hits)

# --- B: the migration moves the data ----------------------------------------
res = LRA.migrate_legacy_identity()
check("B1 the migration reported work", res.get("moved", 0) >= 4 and res.get("events", 0) >= 1, res)
_names = []
for dirpath, _dirs, files in os.walk(TMP):
    for n in list(_dirs) + files:
        if n.startswith(OLD):
            _names.append(os.path.relpath(os.path.join(dirpath, n), TMP))
check("B2 no file or directory keeps the retired name", _names == [], _names)

_sess2 = json.load(open(os.path.join(TMP, "sessions", NEW + ".json"), encoding="utf-8"))
check("B3 the session id and the access flag are renamed",
      _sess2.get("id") == NEW and _sess2.get("allow_architect") is True
      and LRA._LEGACY_FIELD not in _sess2, _sess2.get("id"))
check("B4 the title is the Architect's", _sess2.get("title") == LRA._LEGACY_TITLE)
check("B5 message PROSE is never rewritten",
      _sess2["messages"][0]["content"] == "the note says " + OLD + " in prose",
      _sess2["messages"][0]["content"])
check("B6 the stale backup copy is renamed too, not lost",
      os.path.exists(os.path.join(TMP, "sessions", NEW + ".json.bak-1")))

_graph = json.load(open(os.path.join(TMP, "graphs", NEW + "_run_abc.json"), encoding="utf-8"))
check("B7 a stateless run graph follows its run id",
      _graph.get("session") == NEW + "_run_abc", _graph.get("session"))

_store = json.load(open(os.environ["LONGRUN_AGENTS_FILE"], encoding="utf-8"))
check("B8 the agent registry key is renamed and pinned",
      list(_store.get("agents") or {}) == [NEW]
      and _store["agents"][NEW].get("session") == NEW, _store.get("agents"))

check("B9 the tombstone list follows the id",
      (NEW + "\n") in open(os.path.join(TMP, "sessions", ".deleted"), encoding="utf-8").read())
check("B10 the workspaces folder is renamed",
      os.path.isdir(os.path.join(TMP, "workspaces", NEW))
      and not os.path.exists(os.path.join(TMP, "workspaces", OLD)))

conn = sqlite3.connect(EV.DB_PATH)
_rows = conn.execute("SELECT kind, data FROM events ORDER BY id").fetchall()
conn.close()
_e0 = json.loads(_rows[0][1])
check("B11 the event kind and its identifiers are renamed",
      _rows[0][0] == NEW + ".done" and _e0.get("session") == NEW
      and _e0.get("by") == NEW + "_1", _rows[0])
check("B12 an event's prose is never rewritten",
      json.loads(_rows[1][1]).get("text") == "quote about " + OLD + " kept",
      json.loads(_rows[1][1]))

# --- D: idempotent ----------------------------------------------------------
LRA._MIGRATED = False
res2 = LRA.migrate_legacy_identity()
check("D1 a second run rewrites nothing",
      res2.get("moved") == 0 and res2.get("events") == 0
      and res2.get("rewritten") is False, res2)
LRA._MIGRATED = False
res3 = LRA.migrate_legacy_identity()
check("D2 ... and is stable a third time", res3.get("moved") == 0, res3)

shutil.rmtree(TMP, ignore_errors=True)
ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
