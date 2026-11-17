#!/usr/bin/env python3
"""v1095 — a failure the agent RETRIES is a reliability signal, not noise.

Round 26 (Trial by Trace, arXiv:2610.32285). The register ranked classes by
count; a class the agent re-hit in the same shape within the next three tool
calls says something the count does not: the hint beside it did not land.
Measured 2026-11-18: 19 of 155 failed cards (12.3 %) were followed by the SAME
class within three tool calls.

  A  `retry_signal` is the share, and it is total on bad input
  B  the window is the next THREE tool calls — a repeat four cards later is not
     one, and a class nobody retried reports 0
  C  the count travels: class row → issue row → repair draft (`proposal.json`,
     `REPAIR.md`) → `self.failures` lines
  D  a high retry share lifts the severity ONE step, never past the gate cap
  E  the run-record corpus (no ordering) reports repeats 0 — no invented signal

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1095_retry_signal.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1095-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs"), exist_ok=True)

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


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def record(name, steps):
    with open(os.path.join(RUNS, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)


MISS = "missing REQUIRED argument(s) 'command'"
PERM = "permission denied by policy: <path>"
GATE = "plan mode: only read-only tools run — the plan needs approval"
OKC = {"tool": "fs.read", "ok": True, "exit_code": 0, "error": ""}

# ------------------------------------------------------------ A: the share --
check("A1 no repeats is 0.0", selfevolve.retry_signal(0, 10) == 0.0)
check("A2 three of ten is 0.3", selfevolve.retry_signal(3, 10) == 0.3)
check("A3 a zero denominator is 0.0, not a crash",
      selfevolve.retry_signal(5, 0) == 0.0)
check("A4 junk input is 0.0, not a crash",
      selfevolve.retry_signal("x", 3) == 0.0 and selfevolve.retry_signal(None, None) == 0.0)

# ------------------------------------- B: the window is the NEXT three calls --
# s1: four MISS failures in a row — three of them are followed by the same class
# within three tool calls.
session("s1", [
    {"tool": "shell.exec", "ok": False, "error": MISS},
    {"tool": "shell.exec", "ok": False, "error": MISS},
    {"tool": "shell.exec", "ok": False, "error": MISS},
    {"tool": "shell.exec", "ok": False, "error": MISS},
    OKC,
])
# s2: the same class, four cards apart — outside the window.
session("s2", [
    {"tool": "fs.read", "ok": False, "error": "no such file: <path>"},
    OKC, OKC, OKC,
    {"tool": "fs.read", "ok": False, "error": "no such file: <path>"},
])
# s3: two consecutive PERM failures — a retry, but not enough of one to lift.
session("s3", [
    {"tool": "shell.exec", "ok": False, "error": PERM},
    {"tool": "shell.exec", "ok": False, "error": PERM},
])
# s4: four GATE refusals — retried, and still never an error.
session("s4", [
    {"tool": "shell.exec", "ok": False, "error": GATE},
    {"tool": "shell.exec", "ok": False, "error": GATE},
    {"tool": "shell.exec", "ok": False, "error": GATE},
    {"tool": "shell.exec", "ok": False, "error": GATE},
])
record("r1", [{"tool": "shell.exec", "ok": False, "error": MISS}])

live = selfevolve.session_failures(limit=200)
rows = {(r["tool"], r["error"]): r for r in live["classes"]}
miss = rows.get(("shell.exec", MISS)) or {}
far = rows.get(("fs.read", "no such file: <path>")) or {}
perm = rows.get(("shell.exec", PERM)) or {}
check("B1 the four-card run retries three times", miss.get("repeats") == 3, miss)
check("B2 a repeat four cards later is outside the window",
      far.get("count") == 2 and far.get("repeats") == 0, far)
check("B3 a class nobody retried reports 0 repeats",
      perm.get("count") == 2 and perm.get("repeats") == 1, perm)

merged = selfevolve.failure_candidates(limit=200, include_sessions=True)
cls = {(r["tool"], r["error"]): r for r in merged["classes"]}
m = cls.get(("shell.exec", MISS)) or {}
check("C1 the merged class row carries repeats and its rate (the run record adds "
      "one to the count, never to the repeats)",
      m.get("repeats") == 3 and abs(float(m.get("retry_rate") or 0) - 0.6) < 1e-9, m)

iss = {(i["tool"], i["family"]): i for i in merged["issues"]}
mi = iss.get(("shell.exec", "missing-argument")) or {}
check("C2 the issue row sums its classes' repeats",
      mi.get("repeats") == 3 and mi.get("count") == 5, mi)
check("C3 the run-record-only class reports 0 repeats",
      all(int(i.get("repeats") or 0) == 0
          for i in merged["issues"] if i.get("source") == "runs"), "")

# ------------------------------------------------------- D: the severity ----
check("D1 a retried warning lifts to error",
      selfevolve.severity_for("timeout", 4, 1, 3) == "error",
      selfevolve.severity_for("timeout", 4, 1, 3))
check("D2 the same volume with no retries stays a warning",
      selfevolve.severity_for("timeout", 4, 1, 0) == "warning",
      selfevolve.severity_for("timeout", 4, 1, 0))
check("D3 two retries out of two is not enough volume to lift",
      selfevolve.severity_for("permission", 2, 1, 1) == "info",
      selfevolve.severity_for("permission", 2, 1, 1))
check("D4 a retried GATE never becomes an error",
      selfevolve.severity_for("gate", 4, 1, 3) == "warning",
      selfevolve.severity_for("gate", 4, 1, 3))
check("D5 an existing error cannot be lifted further",
      selfevolve.severity_for("timeout", 40, 9, 30) == "error")

# --------------------------------------------------- E: the draft carries it --
drafts = selfevolve.issue_drafts(os.path.join(_tmp, "repairs"), limit=10,
                                 min_severity="info")
md = [w for w in (drafts.get("written") or [])
      if w.get("issue") == "fail-shell-exec-missing-argument"]
check("E1 one draft is written for the retried issue", bool(md), drafts.get("written"))
body = ""
prop = {}
if md:
    body = open(os.path.join(md[0]["path"], "REPAIR.md"), encoding="utf-8").read()
    prop = json.load(open(os.path.join(md[0]["path"], "proposal.json"), encoding="utf-8"))
check("E2 proposal.json keeps repeats and the rate",
      int(prop.get("repeats") or 0) == 3 and float(prop.get("retry_rate") or 0) > 0, prop)
check("E3 REPAIR.md states the retry count once, in the header",
      "**Retried:** 3 of 5" in body, body[:300])
check("E4 the class line names how many were retried",
      "(3 retried in the same shape)" in body, body[:400])
noret = [w for w in (drafts.get("written") or []) if not w.get("repeats")]
check("E5 an issue with no retries writes no retry claim",
      all("**Retried:**" not in open(os.path.join(w["path"], "REPAIR.md"),
                                     encoding="utf-8").read()
          for w in noret), "")

res = T.execute("self", {"action": "failures", "limit": 10})
lines = " ".join(res.get("failure_lines") or [])
issues = ((res.get("failures") or {}).get("issues") or [])
check("E6 the `self.failures` payload carries repeats per issue",
      all("repeats" in i for i in issues), issues[:1])
check("E7 its lines name the retry count",
      "retried" in lines and "missing-argument" in lines, lines[:300])

print("\n---\nv1095: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
