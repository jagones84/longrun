#!/usr/bin/env python3
"""v1240 — an approval in the inbox NAMES the session it belongs to.

Operator: *"approvals open permission instead of the specific session where
approval = full is placed! fix"*. The chip now opens the approval inbox, and a
row must point at the SESSION waiting on the decision. The chat loop records a
tool gate with `run_id = session id` (`agent.py` -> `gated_call`), so the unified
inbox resolves that id to a real session ONCE, in `approvals.list_unified` — the
WebUI/CLI/`harness.status` just read the field and never re-derive it.

Deterministic: isolated stores, no server, no network, no model.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1240-")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PROPOSALS_DIR"] = os.path.join(TMP, "proposals")
os.environ["LONGRUN_IMPROVEMENT_DIR"] = os.path.join(TMP, "improvement")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import approvals  # noqa: E402
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _row(aid):
    for r in approvals.list_unified(status=None, limit=1000):
        if r.get("id") == aid:
            return r
    return None


# a live session the inbox can resolve to (a `ctx` keeps `list_sessions` from
# starting its background backfill worker — this test stays offline and quiet)
stores.save_session({"id": "sAlpha", "title": "Alpha session", "messages": [],
                     "ctx": {"pct": 12.5, "tokens_used": 1000, "budget_tokens": 8000}})

# ── A: run_id naming a live session becomes a resolvable session ──────────────
rec = approvals.create("shell.exec", {"command": "ls"}, run_id="sAlpha",
                       decision="pending", reason="test")
row = _row(rec["id"]) or {}
check("A1 a tool-gate row resolves run_id -> session when run_id IS a session",
      row.get("session") == "sAlpha", row.get("session"))
check("A2 the row carries the session TITLE too (what the jump button shows)",
      row.get("session_title") == "Alpha session", row.get("session_title"))
check("A3 resolving the session never disturbs the tool identity",
      row.get("tool") == "shell.exec" and row.get("run_id") == "sAlpha"
      and row.get("status") == "pending", {k: row.get(k) for k in ("tool", "run_id", "status")})

# ── B: a run_xxx run (agent_run_v2) matches NO session: no false jump ─────────
rec2 = approvals.create("fs.write", {"path": "x"}, run_id="run_deadbeef",
                        decision="pending", reason="test")
row2 = _row(rec2["id"]) or {}
check("B1 a run_xxx run stays session-less (no invented jump target)",
      not row2.get("session"), row2.get("session"))

# ── C: an explicit `session` on the record is never overwritten ───────────────
rec3 = approvals.create("fs.read", {"path": "y"}, run_id="sAlpha",
                        decision="pending", reason="test")
_store = approvals._load()
for _r in _store.get("approvals", []):
    if _r.get("id") == rec3["id"]:
        _r["session"] = "sExplicit"
        _r["session_title"] = "Explicit"
approvals._persist()
row3 = _row(rec3["id"]) or {}
check("C1 an explicit session wins over the run_id derivation",
      row3.get("session") == "sExplicit" and row3.get("session_title") == "Explicit",
      {k: row3.get(k) for k in ("session", "session_title")})

# ── D: the resolver is fault-tolerant (a broken store cannot empty the inbox) ─
_orig = stores.list_sessions
try:
    stores.list_sessions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    rows = approvals.list_unified(status=None, limit=1000)
    check("D1 a broken session store yields no session, never an exception",
          isinstance(rows, list) and len(rows) >= 3, len(rows))
finally:
    stores.list_sessions = _orig

# ── E: the UI reads the resolved field (one owner, no second derivation) ──────
_UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the jump button is built from the resolved a.session (not a.run_id)",
      'const _asid = String(a.session || "");' in _UI)

print("\n---\nv1240: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
