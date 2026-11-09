#!/usr/bin/env python3
"""v909 — the approval store never evicts a PENDING request (DR-O).

`create()` bounded the queue with `store["approvals"][-500:]`, which drops the
OLDEST record whatever its state. With 501 open requests the oldest pending one
disappeared: its `threading.Event` was never set, so the run waiting on it hung
until the timeout, and the operator had nothing left to decide.

The rule now: decided records are history and are trimmed oldest-first; a
pending record is a human still being asked and is NEVER dropped — the store
grows instead. The cap is `approvals.max_records` (config, default 500), and a
trim publishes one `approvals.trimmed` event with the number dropped.

Deterministic: isolated approval file, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v909-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "home")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_APPROVALS"] = os.path.join(_tmp, "data", "approvals.json")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events  # noqa: E402
from longrun.tools import approvals, registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def capped(n):
    """Point the store at a small cap without touching the shipped config."""
    return lambda reload=False: {"approvals": {"timeout_secs": 300, "max_records": n}}


# ---- A: 505 pending requests, cap 500 ---------------------------------------
# This is the reported defect: 500 fits, the 501st evicted the FIRST one.
first = approvals.create("shell", {"command": "first"})["id"]
for i in range(505 - 1):
    approvals.create("shell", {"command": "p%d" % i})
_pending = approvals.list_all(status="pending", limit=10000)
check("A1 505 pending requests are all still in the store",
      len(_pending) == 505, len(_pending))
check("A2 the OLDEST pending request is still decidable",
      approvals.get(first) is not None and approvals.get(first)["status"] == "pending",
      approvals.get(first))
check("A3 stats() counts all 505 as pending",
      approvals.stats().get("pending") == 505, approvals.stats().get("pending"))

# ---- B: decided history IS still bounded, oldest first ----------------------
_orig_cfg = registry.load_config
registry.load_config = capped(20)
try:
    _created = [approvals.create("shell", {"command": "d%02d" % i},
                                 decision="auto_approved")["id"] for i in range(40)]
    _all = approvals.list_all(limit=10000)
    _decided = [r for r in _all if r["status"] != "pending"]
    check("B1 decided history is trimmed to the cap",
          len(_decided) == 20, len(_decided))
    check("B2 the trim takes the OLDEST decided records",
          _decided[-1]["summary"] == "d20" and _decided[0]["summary"] == "d39",
          (_decided[0].get("summary"), _decided[-1].get("summary")))
    check("B3 no pending record was touched by the decided trim",
          len([r for r in _all if r["status"] == "pending"]) == 505,
          len([r for r in _all if r["status"] == "pending"]))
    # C: an evicted decided record releases its waiter slot (no leak), a kept one
    # keeps it so a decision can still wake the run.
    check("C1 an evicted decided record leaves no Event behind",
          not any(_i in approvals._events for _i in _created[:20]),
          [i for i in _created[:20] if i in approvals._events])
    check("C2 a kept decided record keeps its Event",
          all(_i in approvals._events for _i in _created[20:]),
          len(approvals._events))
finally:
    registry.load_config = _orig_cfg

# ---- D: the trim is observable -------------------------------------------------
_rows = events.query_events(kind="approvals.trimmed", limit=50)
check("D1 a trim publishes an approvals.trimmed event", len(_rows) >= 1, len(_rows))
_last = (_rows[-1].get("data") if _rows else None)
if isinstance(_last, str):
    _last = json.loads(_last)
check("D2 the event says how many were dropped",
      int((_last or {}).get("dropped") or 0) > 0, _last)

# ---- E: the cap is a config value, not a literal -------------------------------
_ap = registry.load_config().get("approvals") or {}
check("E1 the default config declares approvals.max_records",
      int(registry.DEFAULT_CONFIG["approvals"].get("max_records") or 0) == 500,
      registry.DEFAULT_CONFIG["approvals"])
check("E2 the shipped file can override it",
      "max_records" in (_ap if isinstance(_ap, dict) else {}),
      sorted(_ap) if isinstance(_ap, dict) else _ap)

# ---- F: the queue still works normally under the cap ---------------------------
_orig_cfg = registry.load_config
registry.load_config = capped(5)
try:
    a1 = approvals.create("fs.read", {"path": "/tmp/x"})
    a2 = approvals.create("fs.read", {"path": "/tmp/y"})
    _was_pending = a1["status"] == "pending"
    ok = approvals.decide(a1["id"], "approve", by="test")
    check("F1 a request under the cap is created, decided and readable",
          _was_pending and bool(ok)
          and approvals.get(a1["id"])["status"] == "approved"
          and approvals.get(a2["id"])["status"] == "pending", ok)
finally:
    registry.load_config = _orig_cfg

print("---")
okc = sum(results)
print("v909: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
