#!/usr/bin/env python3
"""v1300 — one context snapshot per session: the rail cannot disagree with the chat.

Measured live (2026-11-24): the LH rail showed 23% for a session whose selected
chat meter showed 2%. The rail was serving `sess["ctx"]` — the real
`prompt_tokens` of the LAST provider request, written before a later compaction —
while `/api/context` recomputed the CURRENT transcript. Selecting the session
therefore appeared to change its count.

Contract:
  A) a fresh computed snapshot (same file stamp) is the row's number, even when a
     stale `sess["ctx"]` says something else;
  B) a stale computed snapshot is not served; the row falls back until refreshed;
  C) the live router number only overrides a row while that session's turn runs;
  D) focus (`context_usage`) never changes a rail row.

Deterministic: temp stores, no model, no network.
Run: python3 tests/acceptance/v1300_rail_ctx_one_snapshot.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1300-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401 — import order (agent cycle)
from longrun.memory import stores  # noqa: E402

results = []
SID = "ctxsnap00001"
requested = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


def seed():
    stores.save_session({"id": SID, "title": "snapshot", "created": 1.0,
                         "messages": [{"role": "user", "content": "hi"}]})


def stamp(sid=SID):
    st = os.stat(os.path.join(stores.SESSIONS_DIR, sid + ".json"))
    return (st.st_mtime_ns, st.st_size)


def row():
    return next((r for r in stores.list_sessions() if r.get("id") == SID), {})


seed()
# the stale snapshot a turn recorded BEFORE a later compaction
doc = stores.load_session(SID)
doc["ctx"] = {"tokens_used": 2340, "budget_tokens": 10000, "pct": 23.4,
              "model": "fake:m", "at": 1.0}
stores.save_session(doc)

stores._ctx_backfill_request = lambda sid, st=None: requested.append((sid, st))

# A — the computed snapshot for THIS file wins, not the stale persisted one
stores._CTX_BACKFILL[SID] = {"pct": 2.0, "tokens_used": 200,
                             "budget_tokens": 10000, "stamp": stamp()}
r = row()
check("A1 a fresh computed snapshot is the row's number",
      (r.get("ctx_pct"), r.get("ctx_tokens"), r.get("ctx_budget")) == (2.0, 200, 10000),
      r)

# B — a snapshot for an older transcript is not served
doc["messages"].append({"role": "assistant", "content": "ok"})
stores.save_session(doc)
old = stamp()
stores._CTX_BACKFILL[SID] = {"pct": 2.0, "tokens_used": 200,
                             "budget_tokens": 10000, "stamp": (old[0] - 1, old[1])}
r2 = row()
check("B1 a stale computed snapshot falls back instead of lying",
      r2.get("ctx_pct") == 23.4, r2)
check("B2 the row asks for a refresh with the CURRENT stamp",
      (SID, stamp()) in requested, requested)

# C — the live router number belongs to a RUNNING turn only
stores._REAL_PROMPT_TOKENS[SID] = 500
r3 = row()
check("C1 a finished turn's live number does not rewrite the row",
      r3.get("ctx_pct") == 23.4, r3)
with stores._ACTIVE_CHAT_LOCK:
    stores._ACTIVE_CHAT[SID] = {"id": SID}
r4 = row()
check("C2 a running turn's live number drives the row",
      r4.get("ctx_pct") == 5.0 and r4.get("ctx_tokens") == 500, r4)
with stores._ACTIVE_CHAT_LOCK:
    stores._ACTIVE_CHAT.pop(SID, None)
stores._REAL_PROMPT_TOKENS.pop(SID, None)

# D — focus (the chat meter's read) does not touch the rail row
before = row()
from longrun.core import httpapi  # noqa: E402
try:
    httpapi.context_usage(SID)
except Exception:  # noqa: BLE001 — the meter's own work is not this test's subject
    pass
after = row()
check("D1 reading the focused chat's meter leaves every row value untouched",
      (before.get("ctx_pct"), before.get("ctx_tokens"), before.get("ctx_budget"))
      == (after.get("ctx_pct"), after.get("ctx_tokens"), after.get("ctx_budget")),
      (before, after))

print("---")
ok = sum(results)
print("v1300: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
