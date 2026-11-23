#!/usr/bin/env python3
"""v1282 — the Matrix->Nucleous verification record is not agent-writable.

Bug hunt 2026-11-23 (F-001). `matrix.verify_target()` — the "mandatory
pre-promotion test" gate — took its ONLY evidence from `verified_targets.json`
in the Matrix RUNTIME dir (`~/.longrun/matrix`). That record is agent-writable:
it is not Nucleous and not in `matrix_guard._store_targets`, so the agent's
`python.run` door (`check_python_write`) allowed rewriting it. A forged record —
the artifact's own sha, no test ever run — made untested code pass as "tested
with its current content", and `promote_to_nucleous` (with the operator
checkbox on) imported it into Nucleous. Fix: in production the record lives in
the improvement RECORD dir, which every door already denies (the same home as
the hash-chained audit ledger).

Contract:
  A the production record path is INSIDE a protected store, NOT Nucleous, NOT
    the Matrix runtime dir, and the agent's python door refuses to write it
  B a record forged in the OLD location (the Matrix runtime dir) verifies nothing
  C the honest path still works: a real `matrix.run_test` records the sha and
    `verify_target` accepts it, without writing the record into the Matrix zone
  D anti-vacuity: a record whose sha does not match the file still refuses

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1282_matrix_verified_record_not_agent_writable.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1282-")
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(tmp, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(tmp, ".Matrix")   # the OLD, writable home
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")        # the protected record home

from longrun.util import paths as _paths          # noqa: E402
from longrun.core import matrix                   # noqa: E402
from longrun.tools import matrix_guard            # noqa: E402
from longrun.tools import registry                # noqa: E402

registry._external_tools = lambda: {}
matrix_guard.ensure_layout()

msrc = os.environ["LONGRUN_MATRIX_SRC"]
mdot = os.environ["LONGRUN_MATRIX_DOT"]
os.makedirs(os.path.join(msrc, "tools"), exist_ok=True)
evil = os.path.join(msrc, "tools", "evil.py")
with open(evil, "w", encoding="utf-8") as f:
    f.write('TOOL_SCHEMA = {"description": "forged", "type": "object", "properties": {}}\n'
            'def execute(args, run_id=None):\n    return {"ok": True}\n')

# ---- A: the production record lives in a protected store -------------------
store = matrix._verified_store_path(None)
check("A1 the production record is under the improvement RECORD dir",
      os.path.realpath(store).startswith(os.path.realpath(_paths.IMPROVEMENT_DIR) + os.sep),
      store)
check("A2 the record is inside a PROTECTED store", matrix_guard._is_store(store) is True, store)
check("A3 the record is NOT in the Matrix runtime dir",
      not os.path.realpath(store).startswith(os.path.realpath(mdot) + os.sep), store)
check("A4 the record path is NOT Nucleous", matrix_guard.is_nucleous_path(store) is False, store)
check("A5 the agent's python door refuses to write the record",
      matrix_guard.check_python_write("open(%r,'w').write('{}')" % store)[0] is False,
      "check_python_write said allowed")

# ---- B: a record forged in the OLD location verifies nothing --------------
old_store = os.path.join(mdot, "verified_targets.json")
with open(old_store, "w", encoding="utf-8") as f:
    json.dump({"tool:evil": {"kind": "tool", "name": "evil",
                             "sha256": matrix._file_sha256(evil)}}, f)
b = matrix.verify_target("tool", "evil")
check("B1 a record forged in the Matrix runtime dir does NOT verify",
      b.get("ok") is False and "PROMOTE_UNVERIFIED" in str(b.get("error")), b)

# ---- C: the honest path still grants verification --------------------------
os.remove(old_store)                          # so C3 can see the honest writer's target
res = matrix.run_test("test_evil.py",
                      code=("from Matrix.tools import evil\n"
                            "assert evil.execute({})['ok']\n"),
                      target="tool:evil")
check("C1 a real, green matrix.run_test passes", res.get("ok") is True, res)
c = matrix.verify_target("tool", "evil")
check("C2 the honest run records the sha and verify_target accepts", c.get("ok") is True, c)
check("C3 the honest record is NOT written into the Matrix runtime dir",
      "verified_targets.json" not in os.listdir(mdot), os.listdir(mdot))

# ---- D: anti-vacuity — a wrong sha still refuses ---------------------------
with open(store, "w", encoding="utf-8") as f:
    json.dump({"tool:evil": {"kind": "tool", "name": "evil", "sha256": "deadbeef"}}, f)
d = matrix.verify_target("tool", "evil")
check("D1 a record whose sha does not match the file still refuses",
      d.get("ok") is False and "PROMOTE_UNVERIFIED" in str(d.get("error")), d)

print("---")
ok_n = sum(RESULTS)
print("v1282: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
