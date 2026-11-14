#!/usr/bin/env python3
"""v1007 — the memory report tells the truth about live vs stored records.

Live evidence (session `fd98ee64e89f`, 2026-11-15): an agent read the memory
store and reported two problems. One was real, one was created by the harness:

  * `agent_notes.md` "313 records against `memory_max_records: 300`" — the store
    actually held exactly 300 live records. `stats()` counted the raw file, so
    the 13 lessons hygiene had correctly retired (each with a tombstone) were
    counted as memory. The caller concluded the budget was broken and lessons
    were being silently dropped.
  * `memory.recent` was "full of `(memory.invalidate) hygiene: over budget 300`"
    — the lifecycle ledger was listed like knowledge.
  * 13 `user_memories` records had no `mid`; every lifecycle action is keyed by
    `mid`, so nothing could ever invalidate or forget them.

Contract locked here:
  A) `stats().kinds`/`total` are LIVE; `stored`/`tombstoned` keep the history;
     `bounded[kind].over` is computed from live records, so a store held AT its
     budget never reads as over;
  B) `health()` keeps `total` = every record (repair sees the dead ones) and adds
     `live`/`stores_live`/`unaddressable`/`core_chars`;
  C) a record with no `mid` cannot be retired by any action, and
     `backfill_mids()` gives it one (idempotent) so it can be;
  D) `memory{action:'recent'}` skips the invalidate/restore ledger unless the
     caller names that kind;
  E) `memory{action:'health'}`'s stdout says LIVE vs stored and names the budget.

Deterministic, no model, no network, no server.

Run: python3 tests/acceptance/v1007_memory_inventory_truth.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1007-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_MEMORY_DIR"] = os.path.join(TMP, "memory")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
# A tiny budget makes the live false alarm reproducible in three records.
os.environ["LONGRUN_MEMORY_MAX_RECORDS"] = "3"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory as mem          # noqa: E402
from longrun.tools import tools                   # noqa: E402

mem._vector_db = {}           # falsy -> keyword path; no embedder, no downloads
mem._writes_since_index = 0

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


LESSONS = [
    "alpha lesson: take the median of three repetitions",
    "beta lesson: poll the endpoint until the model reports loaded",
    "gamma lesson: anchors must be deterministic across runs",
    "delta lesson: shell exec needs a named command argument",
    "epsilon lesson: never restart the service with a live turn",
]

# ---- A. the live false alarm: 5 stored, 3 live, budget 3 -------------------
for text in LESSONS:
    mem.store("agent.note", text, origin="reflect", source="reflect")
st = mem.stats()
check("A1 kinds count LIVE records only", st["kinds"]["agent.note"] == 3,
      str(st["kinds"]))
check("A2 total is the sum of the LIVE counts (ledger entries are records too)",
      st["total"] == 5, str(st["total"]))
check("A3 stored keeps the append-only history", st["stored"]["agent.note"] == 5,
      str(st["stored"]))
check("A4 the ledger is attributed per record, not per file",
      st["kinds"]["memory.invalidate"] == 2 and st["kinds"]["memory.restore"] == 0,
      str(st["kinds"]))
check("A5 tombstoned names the retired difference", st["tombstoned"] == 2,
      str(st["tombstoned"]))
_b = st["bounded"].get("agent.note") or {}
check("A6 a store AT its budget is not reported over",
      _b.get("budget") == 3 and _b.get("live") == 3 and _b.get("over") == 0,
      str(_b))

# ---- B. health keeps the repair view and adds the live one -----------------
h = mem.health()
check("B1 health.total still counts every record (5 notes + 2 tombstones)",
      h["total"] == 7, str(h["total"]))
check("B2 health.live is what recall can return", h["live"] == 5, str(h["live"]))
check("B3 health.invalidated matches the retired ones", h["invalidated"] == 2,
      str(h["invalidated"]))
check("B4 health reports the CORE block size (empty here)", h["core_chars"] == 0,
      str(h["core_chars"]))
check("B5 no unaddressable record yet", h["unaddressable"] == 0,
      str(h["unaddressable"]))

# ---- C. a record with no mid can never be retired --------------------------
_ORPHAN = "legacy marker: written before records had ids"
with open(mem._path("memory.store"), "a", encoding="utf-8") as f:
    f.write(mem._render_md({"ts": 1.0, "kind": "memory.store",
                            "content": _ORPHAN}) + "\n")
st2 = mem.stats()
check("C1 stats counts the id-less record", st2["unaddressable"] == 1,
      str(st2["unaddressable"]))
check("C2 health counts it too", mem.health()["unaddressable"] == 1, "")
_gone = tools._memory({"action": "forget", "query": "legacy marker"}, "run-a")
check("C3 no action can forget it (it has no id to match)",
      not _gone.get("ok") and _gone.get("count") == 0, str(_gone)[:120])
_n = mem.backfill_mids()
check("C4 backfill_mids gives it an id", _n == 1, "repaired=%s" % _n)
check("C5 backfill is idempotent", mem.backfill_mids() == 0, "")
_orph = [r for r in mem.query("", "memory.store", 100000)
         if r.get("content") == _ORPHAN]
check("C6 the record now carries a mid",
      bool(_orph) and bool(str(_orph[0].get("mid") or "").strip()),
      repr(_orph[0].get("mid") if _orph else None))
check("C7 nothing is unaddressable any more", mem.stats()["unaddressable"] == 0, "")
if _orph:
    mem.invalidate(_orph[0]["mid"], reason="legacy test artifact")
    check("C8 the backfilled record is now retirable",
          mem.stats()["kinds"]["memory.store"] == 0,
          str(mem.stats()["kinds"]["memory.store"]))

# ---- D. `recent` does not list the lifecycle ledger ------------------------
rec = tools._memory({"action": "recent", "limit": 50}, "run-a")
check("D1 recent shows memories, not tombstones",
      "gamma lesson" in (rec.get("stdout") or "")
      and "hygiene: over budget" not in (rec.get("stdout") or ""),
      (rec.get("stdout") or "")[:160])
rec_led = tools._memory({"action": "recent", "kind": "memory.invalidate",
                         "limit": 50}, "run-a")
check("D2 the ledger is still reachable when named",
      "hygiene: over budget" in (rec_led.get("stdout") or ""),
      (rec_led.get("stdout") or "")[:160])

# ---- E. the health tool says LIVE vs stored -------------------------------
hp = tools._memory({"action": "health"}, "run-a")
out = hp.get("stdout") or ""
check("E1 stdout is LIVE vs stored", "live /" in out and "stored" in out, out[:160])
check("E2 stdout carries the budget row", "agent.note: 3 live / budget 3" in out,
      out[:200])
check("E3 stdout says the CORE block is empty", "core: 0 chars" in out, out[-120:])

ok = sum(results)
print("\nv1007: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
