#!/usr/bin/env python3
"""v1093 — a GATE refusal is not a fault: the register says so, and ranks it.

Round 24. Measured 2026-11-18 in the live register: 6 of the 24
`shell.exec tool-error` failures were the PLAN GATE refusing ("plan mode: session
… has an unapproved plan") — the policy doing its job, which no repair can fix,
ranked as breakage. The fix has two halves:

  A  the family `gate` for the policy refusals the harness itself writes
  B  its severity is capped at `warning` (a huge gate count never outranks a
     real fault, because the repair drafts follow the severity)
  C  the cap is family-scoped: a real family keeps `error`
  D  generic needles keep reading the CLASS HEAD only — the first cut read the
     whole error and "timeout_secs" in a schema listing pulled 19
     missing-argument failures into `timeout` (the regression this pins)
  E  a plan-gate refusal that begins with the harness prefix is still `gate`

Deterministic: `FAILURE_*` tables and temp fixtures, no model, no network.
Run: python3 tests/acceptance/v1093_gate_family.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1093-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------------------ A: the family --
GATE = ("plan mode: session '774ac9424d2b' has an unapproved plan — 'fs.write' "
        "is not exploration; only read-only tools work until the operator "
        "approves the plan")
for text in (GATE,
             "plan mode: this session is locked and the plan is APPROVED but the "
             "implementation was NOT authorised",
             "the call is waiting for approval from the operator",
             "approval required before this mutation runs"):
    got = selfevolve.failure_family("fs.write", text[:80])
    check("A·gate ← %r" % text[:38], got == "gate", got)
check("A5 a real failure is NOT a gate",
      selfevolve.failure_family("shell.exec", "timeout — the terminal was reset")
      == "timeout", "")
check("A6 `gate` is a real row of the fix table",
      bool(selfevolve.FAMILY_FIX.get("gate", ("", None))[0])
      and "GATE" in selfevolve.FAMILY_FIX["gate"][0], selfevolve.FAMILY_FIX.get("gate"))

# ---------------------------------------------------------- B/C: severity ---
check("B1 a huge gate count is a WARNING, never an error",
      selfevolve.severity_for("gate", 40, 9) == "warning",
      selfevolve.severity_for("gate", 40, 9))
check("B2 a small gate count keeps the normal scale",
      selfevolve.severity_for("gate", 1, 1) == "info"
      and selfevolve.severity_for("gate", 3, 1) == "warning", "")
check("C1 a real family at the same volume stays an ERROR",
      selfevolve.severity_for("timeout", 40, 9) == "error"
      and selfevolve.severity_for("permission", 40, 9) == "error", "")
check("C2 `_severity` itself is unchanged (the cap is a separate rule)",
      selfevolve._severity(40, 9) == "error")

# ---------------------------------------------------- D: no over-matching ---
MISSING = "shell.exec: missing REQUIRED argument(s) 'command'. Required: command."
SCHEMA = ("Arg types: {'command': str, 'timeout_secs': int, 'background': bool}. "
          "Example call: {'action': 'tool', 'tool': 'shell.exec', 'args': {...}}")
check("D1 `timeout_secs` in the schema does NOT make a missing argument a timeout",
      selfevolve.failure_family("shell.exec", MISSING, SCHEMA) == "missing-argument",
      selfevolve.failure_family("shell.exec", MISSING, SCHEMA))
check("D2 `not found` in a long tail does not reclassify a nonzero exit",
      selfevolve.failure_family("shell.exec", "[shell.exec] exit=<n> ok=False",
                                "the script said: file not found later") == "nonzero-exit",
      selfevolve.failure_family("shell.exec", "[shell.exec] exit=<n> ok=False",
                                "the script said: file not found later"))

# ------------------------------- E: a prefixed gate refusal, on live fixtures --
SESS = os.environ["LONGRUN_SESSIONS_DIR"]


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


# 12 refusals behind the harness prefix (the head says nothing about the cause)
PREFIX = "[shell.exec] exit=<n> ok=False backend=None sandboxed=None ERROR: "
session("s1", [{"tool": "shell.exec", "ok": False,
                "error": PREFIX + GATE}] * 12 + [
    # a REAL fault, one occurrence fewer than the gate: severity must decide
    {"tool": "shell.exec", "ok": False,
     "error": "timeout — the terminal was reset"}] * 10 + [
    {"tool": "fs.read", "ok": False, "error": "no such file: /a"},
])
rep = selfevolve.failure_candidates(limit=50, include_sessions=True)
gate = [i for i in rep["issues"] if i["family"] == "gate"]
check("E1 the prefixed refusal is a GATE issue",
      gate and gate[0]["count"] == 12, gate)
check("E2 the gate issue is capped at warning despite 12 occurrences",
      gate and gate[0]["severity"] == "warning", gate[0] if gate else {})
check("E3 the repair draft for it carries the GATE remedy",
      gate and "GATE" in (gate[0].get("action") or ""), gate[0] if gate else {})
check("E4 a bigger gate count does not outrank a real ERROR issue",
      [i["family"] for i in rep["issues"]][:1] != ["gate"], 
      [(i["family"], i["severity"], i["count"]) for i in rep["issues"][:3]])

drafts = selfevolve.issue_drafts(os.path.join(_tmp, "repairs"), limit=10,
                                 min_severity="info")
gd = [w for w in (drafts.get("written") or []) if w["family"] == "gate"]
body = ""
if gd:
    body = open(os.path.join(gd[0]["path"], "REPAIR.md"), encoding="utf-8").read()
check("E5 the written REPAIR.md says it is a gate, not a fault",
      bool(body) and "GATE" in body, body[:160])

print("\n---\nv1093: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
