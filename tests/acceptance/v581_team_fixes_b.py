#!/usr/bin/env python3
"""v581 — team fixes batch B: busy dispatch, knowledge race, forget guard, remove.

Fix2: dispatch to a busy session must fail fast with a retry/steer signal,
  never silently drop. `events.turn_active` probes without raising; the
  orchestrator records a `busy` job; the agent dispatch and sessions.wait
  surface it.
Fix3: `knowledge.add_text` race ("constraint failed") becomes idempotent
  create + clean retryable error.
Fix4: query-mode `memory.forget` refuses broad matches without kind; empty
  core tells the model how to fill it.
Fix5: `matrix.remove` verdict reads the post-hotload cache under lock and
  publishes `tools.changed`, so repeated removes are deterministic.

Deterministic, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v581-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- Fix2: busy probe -------------------------------------------------------
from longrun.core import events as _events  # noqa: E402

check("F2a turn_active exists and is callable", callable(getattr(_events, "turn_active", None)))
try:
    r = _events.turn_active("no-such-session-xyz")
    check("F2b unknown session is idle, never raises", r is False, r)
except Exception as e:  # noqa: BLE001
    check("F2b unknown session is idle, never raises", False, e)
try:
    r = _events.turn_active("")
    check("F2c empty sid is idle", r is False, r)
except Exception as e:  # noqa: BLE001
    check("F2c empty sid is idle", False, e)
ORCH = _read("src", "longrun", "orbit", "orchestrator.py")
check("F2d orchestrator records busy jobs with retry/steer",
      '"state": "busy"' in ORCH or "'state': 'busy'" in ORCH or '"busy"' in ORCH
      and "retry later" in ORCH and "sessions.send" in ORCH, "busy+retry+steer")
AG = _read("src", "longrun", "agent", "agent.py")
check("F2e agent dispatch fails fast on busy teammate",
      "turn_active" in AG and "is busy" in AG and "sessions.send" in AG)
TOOLS_SRC = _read("src", "longrun", "tools", "tools.py")
check("F2f sessions.wait surfaces busy without blocking",
      'job_info.get("state") == "busy"' in TOOLS_SRC)

# ---- Fix3: knowledge idempotent ---------------------------------------------
from longrun.memory import knowledge as kb  # noqa: E402

SID = "v581-sess-1"
try:
    _db = kb._connect()
    try:
        kb._init(_db)
        n1 = kb._session_notebook(_db, SID)
        n2 = kb._session_notebook(_db, SID)
    finally:
        _db.close()
    check("F3a session notebook create is idempotent",
          n1 == n2 and n1 is not None, (n1, n2))
except Exception as e:  # noqa: BLE001
    check("F3a session notebook create is idempotent", False, e)
KB_SRC = _read("src", "longrun", "memory", "knowledge.py")
check("F3b notebook create uses INSERT OR IGNORE",
      "INSERT OR IGNORE INTO notebooks" in KB_SRC)
check("F3c storage conflicts map to a retryable error",
      "storage conflict, retry once" in KB_SRC)
try:
    r = kb.add_text(None, "v581 title", "v581 body text hello", session_id=SID)
    check("F3d add_text into session notebook works",
          r.get("ok") is True and (r.get("chunks") or 0) >= 1, r)
except Exception as e:  # noqa: BLE001
    check("F3d add_text into session notebook works", False, e)

# ---- Fix4: forget guard + core message --------------------------------------
from longrun.tools import tools as tools_mod  # noqa: E402

TOKEN = "v581forgettoken"
for i in range(6):
    tools_mod._memory({"action": "store", "content": "note %d %s" % (i, TOKEN)}, "v581")
r = tools_mod._memory({"action": "forget", "query": TOKEN}, "v581")
check("F4a broad query forget without kind is refused",
      r.get("ok") is False and "bulk delete" in str(r.get("error") or ""), r.get("error"))
r2 = tools_mod._memory({"action": "forget", "query": TOKEN, "kind": "memory.store"}, "v581")
check("F4b scoped forget with kind proceeds",
      r2.get("ok") is True and (r2.get("count") or 0) >= 1, r2)
from longrun.memory import memory as mem  # noqa: E402

mem.core_write("")
r3 = tools_mod._memory({"action": "core"}, "v581")
check("F4c empty core tells the model how to fill it",
      "set_core" in (r3.get("stdout") or ""), (r3.get("stdout") or "")[:120])

# ---- Fix5: remove deterministic ----------------------------------------------
from longrun.core import matrix as _mx  # noqa: E402

MX_SRC = _read("src", "longrun", "core", "matrix.py")
check("F5a remove publishes tools.changed",
      "_publish_tools_changed" in MX_SRC and 'matrix.remove' in MX_SRC)
check("F5b hotload scan holds the lock",
      "def _hotload_locked" in MX_SRC and "with _LOCK" in MX_SRC)
NS = "v581f5ns"
sc = _mx.scaffold("tool", NS, description="v581 deterministic remove probe")
check("F5c scaffold ok", sc.get("ok") is True, sc.get("error") or sc.get("path"))
fp = sc.get("path") or ""
check("F5d scaffold file exists", bool(fp) and os.path.isfile(fp), fp)
rm1 = _mx.remove("tool", NS)
check("F5e remove reports complete, nothing still live",
      rm1.get("ok") is True and rm1.get("complete") is True
      and not (rm1.get("still_live") or []), rm1)
check("F5f file and pyc gone from disk",
      bool(fp) and (not os.path.exists(fp))
      and not os.path.exists(os.path.join(os.path.dirname(fp),
                                          "__pycache__", NS + ".cpython-312.pyc")),
      fp)
rm2 = _mx.remove("tool", NS)
check("F5g second remove is deterministic (no crash, same shape)",
      isinstance(rm2, dict) and "complete" in rm2 and "still_live" in rm2, rm2)
live = _mx.discover_tools()
check("F5h removed namespace absent after hotload",
      all(not (k == NS or k.startswith(NS + ".")) for k in live), len(live))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
