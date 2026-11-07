#!/usr/bin/env python3
"""v846 — approval fatigue is measurable (HA-4, lot H).

The gate stored `status` and nothing else was asked of it: `approvals.stats()`
returned five counters, so "people accept 93% of requests and stop reading them"
was unobservable here. This adds the signal from the SAME records, additively.

  A) accept rate, per tool, on a crafted ledger;
  B) median time-to-decision;
  C) a tool that is approved almost always is named (rubber-stamped);
  D) an empty ledger answers `None`, not a fake zero;
  E) `stats()` keeps its five old keys and adds the signal end-to-end;
  F) a record without `decided_ts` is skipped, never a crash.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v846-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import approvals as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def rec(tool, status, ts=1000.0, decided=None):
    return {"id": "x", "tool": tool, "status": status, "ts": ts,
            "decided_ts": decided}


ledger = [rec("fs.edit", "approved", decided=1002.0) for _ in range(10)]
ledger += [rec("shell", "approved", decided=1010.0) for _ in range(5)]
ledger += [rec("shell", "denied", decided=1010.0) for _ in range(5)]
ledger += [{"id": "p", "tool": "fs.read", "status": "pending", "ts": 1.0}]

f = A._fatigue(ledger)
check("A1 decisions count only approved+denied", f["decisions"] == 20, f["decisions"])
check("A2 the overall accept rate", f["accept_rate"] == 0.75, f["accept_rate"])
check("A3 per-tool split is present and ordered",
      [t["tool"] for t in f["by_tool"]] == ["fs.edit", "shell"], f["by_tool"])
check("A4 fs.edit reads 10/10", f["by_tool"][0]["accept_rate"] == 1.0,
      f["by_tool"][0])
check("B1 median time-to-decision", f["median_decision_secs"] == 6.0,
      f["median_decision_secs"])
check("C1 only the always-approved tool is named",
      [t["tool"] for t in f["rubber_stamped"]] == ["fs.edit"], f["rubber_stamped"])

empty = A._fatigue([])
check("D1 no decisions -> accept rate is None", empty["accept_rate"] is None, empty)
check("D2 no waits -> median is None", empty["median_decision_secs"] is None)
check("D3 nothing is rubber-stamped", empty["rubber_stamped"] == [])

# end-to-end: the real gate writes the records `stats()` now reads
one = A.create("git", {"args": "status"}, run_id="r1")
A.decide(one["id"], "approve", by="test")
st = A.stats()
for key in ("total", "pending", "approved", "denied", "auto_approved", "expired"):
    check("E1 the old counter %r survives" % key, key in st, sorted(st))
check("E2 the new signal is in the same answer",
      st["decisions"] == 1 and st["accept_rate"] == 1.0, st.get("accept_rate"))
check("E3 it names the tool that was approved", st["by_tool"][0]["tool"] == "git",
      st["by_tool"])

check("F1 a record without decided_ts is skipped, never a crash",
      A._fatigue([rec("shell", "approved", decided=None)])["median_decision_secs"] is None)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
