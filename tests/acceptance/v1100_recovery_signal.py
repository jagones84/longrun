#!/usr/bin/env python3
"""v1100 — a failure the agent recovers from is a stumble, not a break.

Round 31 (AgentDebugX, arXiv:2607.18754 — Detect/Attribute/**Recover**/Rerun).
The register counted every failed card as breakage; measured 2026-11-18, **111
of 158 (70 %)** are followed by a success of the same tool in the same stage.
The rule is the trace tree's own (`runtree.onset`): same tool, same node, LATER.

  A  the class carries `recovered` / `recovery_rate` from the session corpus
  B  a later success of ANOTHER tool, or in ANOTHER stage, is not a recovery;
     a success BEFORE the failure is not one either
  C  the issue sums it; a runs-only class says `None` (no order, no claim)
  D  the draft and the `self.failures` line state it

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1100_recovery_signal.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1100-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
OKC = {"tool": "fs.read", "ok": True, "exit_code": 0, "error": ""}


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def record(name, steps):
    with open(os.path.join(RUNS, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)


NOTFOUND = "no such file: <path>"
TIMEOUT = "timeout — the terminal was reset"
BOOM = "boom"
MISS = "missing REQUIRED argument(s) 'path'"
session("s1", [
    {"tool": "shell.exec", "ok": True, "exit_code": 0, "error": "", "node": "n3"},
    {"tool": "shell.exec", "ok": False, "error": BOOM, "node": "n3"},          # no later ok
    {"tool": "shell.exec", "ok": False, "error": NOTFOUND, "node": "n1"},
    {"tool": "fs.read", "ok": True, "exit_code": 0, "error": "", "node": "n1"},
    {"tool": "shell.exec", "ok": True, "exit_code": 0, "error": "", "node": "n1"},  # recovers
    {"tool": "shell.exec", "ok": False, "error": TIMEOUT, "node": "n2"},
    {"tool": "shell.exec", "ok": True, "exit_code": 0, "error": "", "node": "n1"},  # other node
    {"tool": "fs.read", "ok": False, "error": MISS, "node": "n1"},             # never recovered
])
record("r1", [{"tool": "fs.write", "ok": False, "error": NOTFOUND}])

live = selfevolve.session_failures(limit=200)
rows = {(r["tool"], r["error"]): r for r in live["classes"]}
nf = rows.get(("shell.exec", NOTFOUND)) or {}
to = rows.get(("shell.exec", TIMEOUT)) or {}
ms = rows.get(("fs.read", MISS)) or {}
bo = rows.get(("shell.exec", BOOM)) or {}
check("A1 a later success of the same tool in the same stage recovers",
      nf.get("recovered") == 1 and nf.get("count") == 1, nf)
check("A2 a success in ANOTHER stage does not",
      to.get("recovered") == 0 and to.get("count") == 1, to)
check("A3 a success BEFORE the failure does not",
      bo.get("recovered") == 0 and bo.get("count") == 1, bo)
check("A4 no later success is a measured 0, not a missing field",
      ms.get("recovered") == 0 and ms.get("count") == 1, ms)

merged = selfevolve.failure_candidates(limit=200, include_sessions=True)
cls = {(r["tool"], r["error"]): r for r in merged["classes"]}
c = cls.get(("shell.exec", NOTFOUND)) or {}
check("B1 the class row carries the rate", c.get("recovery_rate") == 1.0, c)
run_only = cls.get(("fs.write", NOTFOUND)) or {}
check("B2 a runs-only class makes no claim (rate is None)",
      run_only.get("recovery_rate") is None and run_only.get("source") == "runs", run_only)

iss = {(i["tool"], i["family"]): i for i in merged["issues"]}
nf_i = iss.get(("shell.exec", "not-found")) or {}
to_i = iss.get(("shell.exec", "timeout")) or {}
check("C1 the issue sums recovered and its rate",
      nf_i.get("recovered") == 1 and nf_i.get("recovery_rate") == 1.0, nf_i)
check("C2 an unresolved issue reports 0.0, never None",
      to_i.get("recovered") == 0 and to_i.get("recovery_rate") == 0.0, to_i)
check("C3 the runs-only issue is None",
      (iss.get(("fs.write", "not-found")) or {}).get("recovery_rate") is None,
      iss.get(("fs.write", "not-found")))

# --------------------------------------------------------- D: the surfaces --
OUT = os.path.join(_tmp, "repairs")
drafts = selfevolve.issue_drafts(OUT, limit=10, min_severity="info")
by = {w["issue"]: w for w in drafts.get("written") or []}
nf_d = by.get("fail-shell-exec-not-found") or {}
to_d = by.get("fail-shell-exec-timeout") or {}
b1 = (open(os.path.join(nf_d["path"], "REPAIR.md"), encoding="utf-8").read()
      if nf_d else "")
b2 = (open(os.path.join(to_d["path"], "REPAIR.md"), encoding="utf-8").read()
      if to_d else "")
check("D1 the recovered draft says it is a stumble",
      "**Recovered:** 1 of 1 — a later call of the same tool succeeded" in b1, b1[:500])
check("D2 the unresolved draft says no later success",
      "**Recovered:** 0 of 1 — no later success of the same tool" in b2, b2[:500])
res = T.execute("self", {"action": "failures", "limit": 10})
lines = " ".join(res.get("failure_lines") or [])
check("D3 the `self.failures` line states N/M recovered",
      "1/1 recovered" in lines and "0/1 recovered" in lines, lines[:400])
check("D4 and a runs-only issue has no recovery claim in the line",
      lines.count("recovered") >= 2 and "fs.write" in lines, lines[:400])

print("\n---\nv1100: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
