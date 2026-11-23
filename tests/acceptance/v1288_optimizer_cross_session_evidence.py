#!/usr/bin/env python3
"""v1288 — the optimizer weighs cross-session evidence (I-3).

Bug-hunt/RSI pass 2026-11-23. `optimizer.run(sid)` read ONE session's trace, so a
friction that only shows across many sessions was invisible. The prompt now also
carries the outcome / exit-code counts of the last N run records (`RUNS_DIR`),
and the evidence dict names how many sessions were summarised. No run store ->
no section, and the prompt is byte-identical to before.

Contract:
  A `_read_recent_traces(n)` returns the n NEWEST run records
  B `_cross_summary` counts outcomes and non-zero exit codes
  C `_build_analysis_prompt` adds the cross-session section only when `cross` is
    given (absent -> no section)
  D `run()` records `cross_sessions` in its evidence

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1288_optimizer_cross_session_evidence.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1288-")
os.environ["LONGRUN_OFFLINE"] = "1"
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "RUNS_DIR", "MATRIX_DOT", "MATRIX_SRC", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(tmp, _k)
runs_dir = os.environ["LONGRUN_RUNS_DIR"]
os.makedirs(runs_dir, exist_ok=True)
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)

from longrun.evolve import optimizer as O       # noqa: E402
from longrun.tools import registry              # noqa: E402

registry._external_tools = lambda: {}

now = time.time()
for name, rec, age in (("a.json", {"outcome": "done", "tokens": 10, "steps": 1}, 30),
                       ("b.json", {"outcome": "error", "code": 1, "tokens": 9, "steps": 2}, 20),
                       ("c.json", {"outcome": "done", "tokens": 8, "steps": 1}, 10)):
    p = os.path.join(runs_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.utime(p, (now - age, now - age))

# ---- A: newest-first selection ---------------------------------------------
rows = O._read_recent_traces(2)
check("A1 the two newest run records come back (c, b)",
      [r.get("outcome") for r in rows] == ["done", "error"], rows)
check("A2 the limit is honoured", len(rows) == 2, len(rows))

# ---- B: the summary --------------------------------------------------------
cross = O._cross_summary(O._read_recent_traces(9))
check("B1 the session count is exact", cross.get("sessions") == 3, cross)
check("B2 outcomes are counted", cross.get("outcomes") == {"done": 2, "error": 1},
      cross.get("outcomes"))
check("B3 non-zero exit codes are counted", cross.get("exit_codes") == {"1": 1},
      cross.get("exit_codes"))

# ---- C: the prompt section appears only with cross -------------------------
_trace = {"tokens": 5, "steps": 2, "outcome": "done"}
p_with = O._build_analysis_prompt(_trace, {}, {}, {}, cross=cross)
p_without = O._build_analysis_prompt(_trace, {}, {}, {})
check("C1 the cross-session section is present with the summary",
      "Across the last 3 run record(s)" in p_with and "done=2" in p_with, p_with[:300])
check("C2 and absent without it (no over-block)",
      "Across the last" not in p_without, p_without[:200])

# ---- D: run() records how many sessions it weighed -------------------------
O._read_trace = lambda sid: {"tokens": 5, "steps": 2, "outcome": "done"}
O._read_policy_hits = lambda: {}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._read_refusals = lambda sid: {}
O._call_model = lambda prompt: ""                     # unparseable -> skip, evidence kept
res = O.run("v1288")
check("D1 run() evidence names the cross-session count",
      (res.get("evidence") or {}).get("cross_sessions") == 3, res.get("evidence"))
check("D2 run() still skips on an empty reply (unchanged shape)",
      res.get("skip") is True, res.get("reason"))

print("---")
ok_n = sum(RESULTS)
print("v1288: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
