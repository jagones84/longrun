#!/usr/bin/env python3
"""v1231 — effect semantics: append, read-clear, state order, coverage, ranks.

Source: an external review of the round-119/121/129 declaration layer. Six of its
claims were real defects and are flipped here:

  * `coverage()` folded an invalid declaration into `untyped` and never let an
    invalid row drive the verdict;
  * `verify_trace()` never cleared a prior write on a read, so write -> read ->
    write was reported as a duplicate, and it treated an append as one;
  * it applied reads AFTER writes, so `fs.edit` left the edited file looking
    freshly read and the next read looked redundant;
  * `reversibility.classify()` stopped at the first matching rule, so rule order
    could silently lower an irreversible action;
  * `capture_override()` accepted any class (R0 included) and lowered the class
    even when the capture contract was incomplete;
  * `tool_graph.rank()` recommended an edge whose only observations failed.

Two claims are REFUTED by the live code and pinned here: the declarations are
consulted at the live tool gate (both doors call `_effect_escalation`), and
`delete-without-read` is measured at the agent's trace level by design — a
tool's own declared read is its precondition, not the agent's observation (see
v1188 §3).

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1231_effect_semantics_defects.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1231-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import effect_types as ET  # noqa: E402
from longrun.harness.checks import reversibility as RV  # noqa: E402
from longrun.harness.checks import tool_graph as TG  # noqa: E402
from longrun.core import api_v02 as API               # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


def found(out, kind):
    return any(f["kind"] == kind for f in (out.get("findings") or []))


# ---- A. coverage: an invalid row is its own state ---------------------------
CAT = {"r": {"effect": "read", "idempotent": True, "reads": ["res"]},
       "w": {"effect": "write", "idempotent": False, "writes": ["res"]}}
cov = ET.coverage(CAT)
check("a fully typed catalog is typed", cov["verdict"] == "typed" and cov["untyped"] == 0, cov)
bad = ET.coverage({"x": {"effect": "sideways"}, "y": {}})
check("one invalid row is invalid, and untyped is not double-counted",
      bad["verdict"] == "invalid" and bad["untyped"] == 1
      and len(bad["invalid"]) == 1, bad)
only = ET.coverage({"y": {}})
check("an absent declaration is the only untyped row",
      only["verdict"] == "untyped" and only["untyped"] == 1, only)
mixed = ET.coverage({"ok": {"effect": "read", "reads": ["res"]},
                     "bad": {"effect": "sideways"}})
check("a typed catalog carrying one bad row is invalid, never partial",
      mixed["verdict"] == "invalid" and mixed["typed"] == 1, mixed)

# ---- B. repeat-write: a read clears it, an append is not a repeat -----------
R = {"r": {"effect": "read", "idempotent": True, "reads": ["file"]},
     "w": {"effect": "write", "idempotent": False, "writes": ["file"]},
     "a": {"effect": "append", "idempotent": False, "writes": ["file"]}}
informed = ET.verify_trace([{"tool": "w"}, {"tool": "r"}, {"tool": "w"}], R)
check("a write after an intervening read is not a duplicate effect",
      not found(informed, "repeat-write"), informed)
repeat = ET.verify_trace([{"tool": "w"}, {"tool": "w"}], R)
check("two writes with no read in between are still a repeat",
      found(repeat, "repeat-write"), repeat)
appends = ET.verify_trace([{"tool": "a"}, {"tool": "a"}], R)
check("appending twice is the normal operation, not a repeat",
      not found(appends, "repeat-write"), appends)

# ---- C. state order: an edit is not left looking freshly read ---------------
E = {"e": {"effect": "write", "idempotent": False,
           "reads": ["file"], "writes": ["file"]},
     "r": {"effect": "read", "idempotent": True, "reads": ["file"]}}
after_edit = ET.verify_trace([{"tool": "e"}, {"tool": "r"}], E)
check("a read after an edit sees changed content, not a redundant read",
      not found(after_edit, "redundant-read"), after_edit)
no_change = ET.verify_trace([{"tool": "r"}, {"tool": "r"}], E)
check("a read with nothing written in between is still redundant",
      found(no_change, "redundant-read"), no_change)

# ---- D. program-opportunity is consumption, not a writer pair ---------------
W = {"w1": {"effect": "write", "idempotent": False, "writes": ["file"]},
     "w2": {"effect": "write", "idempotent": False, "writes": ["file"]},
     "r": {"effect": "read", "idempotent": True, "reads": ["file"]}}
writers = ET.verify_trace([{"tool": "w1"}, {"tool": "w2"}], W)
check("writer->writer is a repeat-write, not a consumption claim",
      found(writers, "repeat-write") and not found(writers, "program-opportunity"),
      writers)
consumes = ET.verify_trace([{"tool": "w1"}, {"tool": "r"}], W)
check("a reader of the previous write is still a program opportunity",
      found(consumes, "program-opportunity"), consumes)

# ---- E. classify: the highest matching rule decides ------------------------
CALL = {"tool": "fs.edit",
        "arguments": {"mode": "write", "path": "/etc/passwd"}}
RULES = [
    {"id": "broad", "when": {"argument": "mode", "equals": "write"}, "class": "R1"},
    {"id": "narrow", "when": {"all": [{"argument": "mode", "equals": "write"},
                                      {"argument": "path", "prefix": "/etc"}]},
     "class": "R3"},
]
top = RV.classify(CALL, {"class": "R1", "rules": RULES})
check("a narrow R3 rule wins over a broad R1 rule listed first",
      top["class"] == "R3" and top["rule"] == "narrow", top)
flipped = RV.classify(CALL, {"class": "R1", "rules": list(reversed(RULES))})
check("reordering the rule list cannot lower the classification",
      flipped["class"] == "R3", flipped)

# ---- F. capture_override: R1 only, incomplete contract reverts -------------
GOOD_CAP = {"state": "bytes", "restore": "cp", "retention": "7d", "confirmed": True}
base_ok = RV.capture_override("R4", {"class": "R1", "capture": dict(GOOD_CAP),
                                     "scope": ["private-file"], "capture_ref": "cap-1"})
check("a complete R1 capture still lowers the class", base_ok["class"] == "R1", base_ok)
r0 = RV.capture_override("R4", {"class": "R0", "capture": dict(GOOD_CAP),
                                "scope": ["private-file"], "capture_ref": "cap-1"})
check("a capture cannot claim no-effect (R0): it reverts to the base",
      r0["class"] == "R4" and "capture-override-not-r1" in kinds(r0), r0)
half = {k: v for k, v in GOOD_CAP.items() if k != "retention"}
inc = RV.capture_override("R4", {"class": "R1", "capture": half,
                                 "scope": ["private-file"], "capture_ref": "cap-1"})
check("a half-specified capture reverts instead of justifying autonomy",
      inc["class"] == "R4" and "capture-contract-incomplete" in kinds(inc), inc)

# ---- G. rank never recommends a chain that only ever failed ----------------
GCAT = [{"name": "a", "inputs": [], "outputs": [{"name": "x", "type": "t"}]},
        {"name": "b", "inputs": [{"name": "x", "type": "t"}], "outputs": []}]
failed = TG.build(GCAT, transitions=[{"from": "a", "to": "b", "ok": False},
                                     {"from": "a", "to": "b", "ok": False}])
fe = next(e for e in failed["edges"] if e["from"] == "a" and e["to"] == "b")
check("a failure-only edge is clamped to zero confidence",
      fe["confidence"] == 0.0 and fe["observations"] == 0 and fe["failures"] == 2, fe)
check("a failure-only chain is not ranked back to the model",
      not any(r["tool"] == "b" and r["from"] == "a" for r in TG.rank(failed)),
      TG.rank(failed))
check("feedback does not list a failure-only predecessor",
      not any(p["from"] == "a" for p in TG.feedback(failed, "goal", "b")["predecessors"]),
      TG.feedback(failed, "goal", "b"))
worked = TG.build(GCAT, transitions=[{"from": "a", "to": "b", "ok": True}])
check("a chain with a success is still ranked",
      any(r["tool"] == "b" and r["from"] == "a" for r in TG.rank(worked)),
      TG.rank(worked))

# ---- H. the live gate consults the declarations (refutes "inert metadata") --
_ran = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
         "tool_result": {"ok": True}}]
live = API._effect_escalation("fs.write", {"path": "a"}, _ran)
check("the live tool gate escalates an exact repeat through TOOL_EFFECTS",
      live[0] == "effect-repeat", live)
check("a different object is not escalated",
      API._effect_escalation("fs.write", {"path": "b"}, _ran) == (None, None))
_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
            encoding="utf-8").read()
check("both live doors call the effect escalation",
      _src.count("_effect_escalation(") == 3
      and _src.count("_recovery_escalation(") == 3,
      (_src.count("_effect_escalation("), _src.count("_recovery_escalation(")))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
