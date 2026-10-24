#!/usr/bin/env python3
"""v593 (RED) — canonical permission, Maka `rememberForTurn` direction.

M4a grants are consumable (digest + uses_left + expiry) but NOT bound to the
run that requested them: a grant approved in run A can be consumed from run B.
The slice binds consumption to the requesting run (`turn_scope`, stamped from
`run_id` at create):

- same run + matching call -> consumed (multi-use within the run IS the
  remember-for-this-turn semantic, via uses_left);
- another run -> denied, even with an identical call;
- unscoped legacy records and callers that pass no run keep working (no
  migration; v567 pins the old 3-arg form).

Both production consume sites (`api_v02` run-tool paths) must pass their
`run_id`.

Deterministic: isolated approvals store via env override, no model/network.
Run: python3 tests/acceptance/v593_run_bound_approval.py
"""
import inspect
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
_tmp = tempfile.mkdtemp(prefix="lr-appr-v593-")
os.environ["LONGRUN_APPROVALS"] = os.path.join(_tmp, "approvals.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import approvals  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _approve(tool, args, run, uses=1):
    rec = approvals.create(tool, args, run_id=run, decision="approved",
                           reason="t", uses_left=uses)
    assert rec["status"] == "approved", rec
    return rec


# ---- A: the binding exists ----------------------------------------------------
sig = inspect.signature(approvals.consume)
check("A1 consume() accepts the caller run",
      "run_id" in sig.parameters, str(list(sig.parameters)))
rec0 = _approve("fs.read", {"path": "a.txt"}, "run-A")
check("A2 create() stamps the requesting run as turn_scope",
      rec0.get("turn_scope") == "run-A", repr(rec0.get("turn_scope")))

# ---- B: same run ok, other run denied ------------------------------------------
rec = _approve("fs.read", {"path": "b.txt"}, "run-A")
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "b.txt"},
                            run_id="run-A")
check("B1 same run consumes", ok is True, msg)
rec = _approve("fs.read", {"path": "c.txt"}, "run-A")
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "c.txt"},
                            run_id="run-B")
check("B2 another run is denied even with an identical call",
      ok is False and "another run" in msg, msg)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "c.txt"},
                            run_id="run-A")
check("B3 the grant still works in its own run after a foreign attempt",
      ok is True, msg)

# ---- C: legacy paths keep working ----------------------------------------------
rec = _approve("fs.read", {"path": "d.txt"}, "run-A")
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "d.txt"})
check("C1 a caller that passes no run keeps working", ok is True, msg)
rec = approvals.create("fs.read", {"path": "e.txt"}, decision="approved",
                       reason="t")
rec.pop("turn_scope", None)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "e.txt"},
                            run_id="run-Z")
check("C2 an unscoped record accepts any run", ok is True, msg)

# ---- D: remember-for-turn = multi-use inside the bound run ----------------------
rec = _approve("shell.exec", {"command": "date"}, "run-T", uses=3)
seen = []
for _ in range(3):
    ok, msg = approvals.consume(rec["id"], "shell.exec", {"command": "date"},
                                run_id="run-T")
    seen.append(ok)
ok4, msg4 = approvals.consume(rec["id"], "shell.exec", {"command": "date"},
                              run_id="run-T")
check("D1 three uses inside the run pass, the fourth is spent",
      seen == [True, True, True] and ok4 is False, "%r %r" % (seen, msg4))
rec = _approve("shell.exec", {"command": "date"}, "run-T", uses=3)
ok, msg = approvals.consume(rec["id"], "shell.exec", {"command": "date"},
                            run_id="run-OTHER")
check("D2 foreign run cannot spend the remembered grant",
      ok is False, msg)

# ---- E: production sites pass their run -----------------------------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
              encoding="utf-8") as f:
        _api = f.read()
except OSError as e:
    _api = ""
    print("WARN cannot read api_v02.py: %s" % e)
import re as _re
_flat = _re.sub(r"\s+", " ", _api)
check("E1 run-tool path passes its run on consume",
      "approvals.consume(rec[\"id\"], tool, args, run_id=run_id)" in _flat)
check("E2 both consume sites are run-bound",
      _flat.count("approvals.consume(rec[\"id\"], tool, args, run_id=run_id)") >= 2,
      _flat.count("approvals.consume(rec[\"id\"], tool, args, run_id=run_id)"))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
