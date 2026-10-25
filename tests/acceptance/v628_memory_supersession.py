#!/usr/bin/env python3
"""v628 — memory SUPERSESSION lifecycle (P2, N8: validity/supersession).

Deterministic, no model. Mirrors v204's setup style. Proves a wrong memory
can be linked to its correction and re-admitted, without losing history:
  A) source contracts: memory.py has supersede()/restore(), MEMORY_FIELDS
     maps "memory.restore" to the SAME ledger file, the registry enum +
     _SUBTOOL_FIELDS carry the new actions, tools._memory handles them and
     api_v02.py routes them;
  B) functional: supersede() hides the record from governed recall while a
     superseded_by tombstone survives on disk; restore() re-admits it via
     LAST-ENTRY-WINS; a later invalidate wins again; health() reports the
     superseded count; purge_invalidated() removes the record after a final
     invalidate;
  C) tools._memory direct calls reject supersede/restore without a target.

Run:  python tests/acceptance/v628_memory_supersession.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-628-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory as mem  # noqa: E402
from longrun.tools import tools  # noqa: E402

# isolate the store: redirect DATA_DIR/CORE to the temp dir (v204 pattern)
mem.DATA_DIR = os.path.join(tmp, "memory")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
os.makedirs(mem.DATA_DIR, exist_ok=True)
mem._vector_db = {}          # falsy → semantic_query falls back to keyword
mem._writes_since_index = 0  # avoid a rebuild over the empty dir mid-test


def src(rel):
    with open(os.path.join(REPO, rel), "r", encoding="utf-8") as f:
        return f.read()


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: source contracts ----
MEM_SRC = src(os.path.join("src", "longrun", "memory", "memory.py"))
check("A1 memory.py defines supersede() and restore()",
      "def supersede(" in MEM_SRC and "def restore(" in MEM_SRC, "")
check("A2 MEMORY_FIELDS maps memory.restore to the SAME ledger file",
      '"memory.restore": "memory_invalidations.md"' in MEM_SRC, "")
check("A3 invalid_targets() applies last-entry-wins (kind-aware state)",
      'state[t] = ("invalidated" if r.get("kind") == "memory.invalidate"' in MEM_SRC,
      "")
check("A4 purge_invalidated skips the whole tombstone ledger",
      'if kind in ("memory.invalidate", "memory.restore"):' in MEM_SRC, "")

REG_SRC = src(os.path.join("src", "longrun", "tools", "registry.py"))
check("A5 registry enum carries supersede + restore",
      '"clear_core", "invalidate", "supersede", "restore",' in REG_SRC, "")
check("A6 registry _SUBTOOL_FIELDS declares both actions",
      '"supersede": ["target", "superseded_by", "reason"],' in REG_SRC
      and '"restore": ["target", "reason"],' in REG_SRC, "")

TOOLS_SRC = src(os.path.join("src", "longrun", "tools", "tools.py"))
check("A7 tools._memory handles supersede/restore (target required)",
      'if action in ("supersede",):' in TOOLS_SRC
      and 'if action in ("restore",):' in TOOLS_SRC, "")

API_SRC = src(os.path.join("src", "longrun", "core", "api_v02.py"))
check("A8 api_v02 routes action=supersede/restore with target required",
      'if action == "supersede":' in API_SRC and 'if action == "restore":' in API_SRC
      and API_SRC.count('target (or id) required') >= 3, "")

# ---- B: functional lifecycle ----
r_a = tools._memory({"action": "store",
                     "content": "v628 wrong lesson: deploy needs reboot",
                     "source": "unit-test"}, "run-628")
mid_a = r_a.get("mid")
r_b = tools._memory({"action": "store",
                     "content": "v628 corrected lesson: deploy is zero-downtime",
                     "source": "unit-test"}, "run-628")
mid_b = r_b.get("mid")
check("B1 two records stored with stable ids",
      isinstance(mid_a, str) and isinstance(mid_b, str) and mid_a != mid_b,
      "%s/%s" % (mid_a, mid_b))

# supersede: returns the tombstone record (NOT a list of mids — the API is
# record-in/record-out, matching invalidate()).
ts = mem.supersede(mid_a, by=mid_b, reason="contradicted by the deploy audit")
check("B2 supersede() returns the tombstone record",
      isinstance(ts, dict) and ts.get("kind") == "memory.invalidate"
      and ts.get("target") == mid_a, str(ts.get("kind")) if isinstance(ts, dict) else type(ts).__name__)
check("B3 invalid_targets() includes the superseded mid",
      mid_a in mem.invalid_targets(), str(sorted(mem.invalid_targets()))[:80])
gq = mem.governed_query(kind="memory.store", limit=50)
check("B4 superseded dropped from governed_query",
      all(x.get("mid") != mid_a for x in gq), "n=%d" % len(gq))
check("B5 raw record still on disk (append-only)",
      any(x.get("mid") == mid_a for x in mem.query(None, "memory.store", 1000)), "")

# B6: the tombstone carries the superseded_by pointer ON DISK
ts_recs = mem._parse_md_file(mem._path("memory.invalidate"))
link = [t for t in ts_recs if t.get("target") == mid_a and t.get("superseded_by") == mid_b]
check("B6 tombstone on disk carries superseded_by=<replacement>",
      len(link) == 1, "n=%d" % len(link))

# restore: LAST-ENTRY-WINS re-admits the record, history intact
tr = mem.restore(mid_a, reason="audit was wrong, deploy does need a reboot")
check("B7 restore() returns a memory.restore tombstone",
      isinstance(tr, dict) and tr.get("kind") == "memory.restore"
      and tr.get("target") == mid_a, str(tr.get("kind")) if isinstance(tr, dict) else type(tr).__name__)
check("B8 invalid_targets() no longer includes the restored mid",
      mid_a not in mem.invalid_targets(), "")
gq2 = mem.governed_query(kind="memory.store", limit=50)
check("B9 restored record surfaces in governed_query again",
      any(x.get("mid") == mid_a for x in gq2), "n=%d" % len(gq2))
_all_ts = mem._parse_md_file(mem._path("memory.invalidate"))
check("B10 full history kept: invalidate+restore both in the ledger",
      sum(1 for t in _all_ts if t.get("target") == mid_a) == 2,
      "entries=%d" % sum(1 for t in _all_ts if t.get("target") == mid_a))

# B11: a LATER invalidate wins again (last-entry-wins, not one-way)
mem.invalidate(mid_a, reason="second opinion confirms the first")
check("B11 re-invalidate after restore wins again",
      mid_a in mem.invalid_targets()
      and all(x.get("mid") != mid_a for x in mem.governed_query(kind="memory.store", limit=50)),
      "")

# B12: health() reports the superseded count (tombstones with a pointer)
h = mem.health()
check("B12 health() reports superseded >= 1", h.get("superseded", 0) >= 1,
      str(h.get("superseded")))
check("B13 health() still reports invalidated >= 1", h.get("invalidated", 0) >= 1,
      str(h.get("invalidated")))

# B14: purge_invalidated() removes the tombstoned record and clears the ledger
pu = mem.purge_invalidated()
check("B14 purge removes the invalidated record",
      pu.get("ok") and all(x.get("mid") != mid_a for x in mem.query(None, "memory.store", 1000)),
      "removed=%s" % pu.get("removed"))
check("B15 tombstone ledger emptied after purge", mem.invalid_targets() == set(), "")
check("B16 untouched record survives purge",
      any(x.get("mid") == mid_b for x in mem.query(None, "memory.store", 1000)), "")

# ---- C: tools._memory direct calls (target required) ----
rs = tools._memory({"action": "supersede", "reason": "no target"}, "run-628")
check("C1 supersede without target is refused",
      rs.get("ok") is False and "target required" in (rs.get("error") or ""),
      (rs.get("error") or "")[:80])
rr = tools._memory({"action": "restore", "reason": "no target"}, "run-628")
check("C2 restore without target is refused",
      rr.get("ok") is False and "target required" in (rr.get("error") or ""),
      (rr.get("error") or "")[:80])
r3 = tools._memory({"action": "store", "content": "v628 third lesson",
                    "source": "unit-test"}, "run-628")
mid_c = r3.get("mid")
rc = tools._memory({"action": "supersede", "target": mid_c, "superseded_by": mid_b,
                    "reason": "tool-path supersede"}, "run-628")
check("C3 tool-path supersede ok + links the replacement",
      rc.get("ok") and mid_c in mem.invalid_targets()
      and ("-> " + mid_b) in (rc.get("stdout") or ""),
      (rc.get("stdout") or "")[:80])
rr2 = tools._memory({"action": "restore", "target": mid_c}, "run-628")
check("C4 tool-path restore re-admits",
      rr2.get("ok") and mid_c not in mem.invalid_targets(), "")

ok = sum(results)
print("\nv628: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
