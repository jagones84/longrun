#!/usr/bin/env python3
"""v719 — a mined sequence becomes a REAL, tested Matrix tool (EV-11).

The mining lane stopped at `ledger.jsonl`: a repeated green pattern became a skill
or nothing. `improve{action:"forge"}` now gives it an executive arm in Matrix —
the live, revisable code zone — and keeps the artifact only when the tool proves
itself (`matrix.run_test` + `matrix.verify_target`).

  A  a replayable pattern forges a real module, tested and verified
  B  the tool is DISCOVERED and refuses a malformed call (fail-closed)
  C  the draft records the outcome and the ledger keeps the audit entry
  D  a 1-step pattern and a non-replayable step are refused
  E  an existing namespace file is never clobbered
  F  a failing proof removes the file (nothing half-verified stays)
  G  forging is approval-gated and `path` is required
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v719-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.core import matrix as MTX  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


PATTERN = ["fs.read", "fs.edit", "shell.exec"]

# ------------------------------------- A: forge + prove -------------------
r = SE.forge_matrix(PATTERN, support=4, draft="draft-abc", name="learned_test_a")
check("A1 the forge succeeded", r.get("ok") is True, r)
check("A2 it names the tool it created", r.get("matrix_tool") == "learned_test_a.run", r)
path = r.get("path") or ""
check("A3 the module exists on disk", bool(path) and os.path.isfile(path), path)
body = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
check("A4 the body is REAL code, not the scaffold placeholder",
      "REPLACE THIS DESCRIPTION" not in body and "STEPS = %r" not in body
      and PATTERN[0] in body, body[:200])
check("A5 the generated test ran green", (r.get("test") or {}).get("ok") is True, r.get("test"))
check("A6 the contract gate accepted it", (r.get("verify") or {}).get("ok") is True,
      r.get("verify"))
check("A7 the sha is the one that was verified",
      (r.get("verify") or {}).get("sha256") == r.get("sha256"), r.get("verify"))

# ------------------------------------- B: discovered + fail-closed --------
tools = MTX.discover_tools()
check("B1 the forged tool is discovered by Matrix", "learned_test_a.run" in tools, sorted(tools))
call = MTX.execute_tool("learned_test_a.run", {}, run_id="v719")
check("B2 a call with no `inputs` is refused, not executed",
      call.get("ok") is False and "inputs" in str(call), call)

# ------------------------------------- C: draft + ledger ------------------
draft_dir = os.path.join(improve.DRAFT_DIR, "fs.read-fs.edit-shell.exec")
os.makedirs(draft_dir, exist_ok=True)
with open(os.path.join(draft_dir, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "fs.read-fs.edit-shell.exec", "pattern": PATTERN,
               "support": 3, "status": "proposed"}, f)
r2 = SE.forge_from_draft(draft_dir, name="learned_test_b")
check("C1 the draft forge reports its tool",
      r2.get("ok") and r2.get("matrix_tool") == "learned_test_b.run", r2)
prop = json.load(open(os.path.join(draft_dir, "proposal.json"), encoding="utf-8"))
mt = prop.get("matrix_tool") or {}
check("C2 the draft records the outcome", mt.get("ok") is True
      and mt.get("matrix_tool") == "learned_test_b.run", mt)
led = improve.ledger_tail(20)
check("C3 the ledger keeps a forge entry", any(e.get("kind") == "forge" for e in led), led[:2])

# ------------------------------------- D: refusals ------------------------
one = SE.forge_matrix(["fs.read"], name="learned_one")
check("D1 a single-tool pattern is refused", one.get("ok") is False
      and "at least 2 steps" in str(one.get("error")), one)
check("D2 nothing was written for it",
      not os.path.exists(os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools",
                                      "learned_one.py")))
bad = SE.forge_matrix(["fs.read", "batch"], name="learned_bad")
check("D3 a pseudo-action is refused as not replayable",
      bad.get("ok") is False and "not replayable" in str(bad.get("error")), bad)

# ------------------------------------- E: never clobber -------------------
again = SE.forge_matrix(PATTERN, support=4, name="learned_test_a")
check("E1 forging over an existing namespace is refused",
      again.get("ok") is False and "refusing to clobber" in str(again.get("error")), again)
check("E2 the original file is untouched", os.path.isfile(path)
      and open(path, encoding="utf-8").read() == body)

# ------------------------------------- F: fail closed ---------------------
real_verify = MTX.verify_target
MTX.verify_target = lambda *a, **k: {"ok": False, "error": "forced red"}
try:
    red = SE.forge_matrix(PATTERN, support=2, name="learned_test_red")
finally:
    MTX.verify_target = real_verify
check("F1 a failing proof is reported", red.get("ok") is False, red)
check("F2 the unverified file is removed",
      not os.path.exists(os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools",
                                      "learned_test_red.py")))
check("F3 it says it was removed", red.get("removed") is True, red)

# ------------------------------------- G: surface -------------------------
gate = registry.subtool_gate("improve", {"action": "forge", "path": "x"})
check("G1 forging is approval-gated", bool(gate), gate)
check("G2 the schema lists the action",
      "forge" in ((registry._LEGACY_SCHEMAS["improve"]["properties"]["action"]
                   .get("enum")) or []))
check("G3 `name` is a declared argument",
      "name" in (registry._LEGACY_SCHEMAS["improve"]["properties"] or {}))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
