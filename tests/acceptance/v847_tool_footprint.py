#!/usr/bin/env python3
"""v847 — the tool footprint: enabled but never used (HA-5, lot H).

Every enabled connector puts its tool names and descriptions in the model-facing
index on every turn. `tools/diag.tools_report` lists what is enabled but reads no
usage; `registry.policy_report` names never-fired GUARDRAILS, not tools. This joins
the enabled list with the run history the harness already records.

  A) a tool called inside the window is not reported;
  B) a tool only called OUTSIDE the window is reported;
  C) pending/pseudo names never leak into the answer;
  D) the unused index cost is a number, not a promise;
  E) the window is explicit in the answer;
  F) `GET /api/tools` carries the footprint (one surface).

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v847-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402
from longrun.util import selfevolve as SE  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


NOW = 2_000_000_000.0
enabled = [t["name"] for t in R.catalog() if t.get("name") and t.get("enabled", True)]
check("A0 the registry has enabled tools", len(enabled) > 3, len(enabled))
used_recent = enabled[0]
only_old = enabled[1]
unused = enabled[2]

original = SE.history_rows
SE.history_rows = lambda: [
    {"tools": [used_recent], "ts": NOW - 60},
    {"tools": ["batch", "subagent"], "ts": NOW - 120},          # loop pseudo-actions
    {"tools": [only_old], "ts": NOW - 100 * 86400},             # outside the window
]
try:
    rep = R.footprint(days=30, now=NOW)
finally:
    SE.history_rows = original

check("A1 a tool used inside the window is NOT reported",
      used_recent not in rep["never_used"], rep["never_used"])
check("B1 a tool only used outside the window IS reported",
      only_old in rep["never_used"], rep["never_used"])
check("C1 pseudo-actions never appear in the answer",
      not ({"batch", "subagent"} & set(rep["never_used"])), rep["never_used"])
check("D1 the unused index cost is a number",
      isinstance(rep["never_used_index_chars"], int) and rep["never_used_index_chars"] > 0,
      rep["never_used_index_chars"])
check("E1 the window is explicit", rep["days"] == 30, rep["days"])
check("E2 only the in-window runs are counted", rep["runs"] == 2, rep["runs"])
check("E3 an untouched tool is listed", unused in rep["never_used"], unused)

src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
check("F1 GET /api/tools carries the footprint", '"footprint": registry.footprint()' in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
