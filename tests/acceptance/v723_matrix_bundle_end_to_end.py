#!/usr/bin/env python3
"""v723 — the recursive loop closes end to end (EV-17).

Operator's words: "forzare un evolve con un pattern che produca un bundle,
approvarlo, e verificare che il tool nuovo sia callable a caldo. Questo è il test
definitivo della ricorsività."

Before this item the ring was open: `evolve` forged code in place (no proposal),
and only the Harness² lane could produce a `scope="matrix"` proposal. Now the
background pass opens a PENDING matrix proposal carrying the exact bundle, and the
approval runs `matrix.apply_learning` + hotload. This battery walks the whole ring:

  A  a green mined pattern becomes a pending `matrix` proposal, no code written
  B  approving it writes the module, hash-bound, and installs it
  C  the new tool is LIVE in the same dispatch the agent uses (fail-closed)
  D  the approval is the boundary: denying leaves the zone untouched
  E  a tampered bundle is refused (the bytes approved are the bytes written)
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v723-")
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
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def configure(**kw):
    cfg = registry.load_config()
    sec = cfg.setdefault("selfevolve", {})
    sec.update(kw)
    registry.save_config(cfg)
    registry.load_config(reload=True)


def policy(value):
    cfg = registry.load_config()
    kinds = cfg.setdefault("approvals", {}).setdefault("kinds", {})
    if value:
        kinds["matrix"] = value
    else:
        kinds.pop("matrix", None)
    registry.save_config(cfg)
    registry.load_config(reload=True)


def modules():
    """The tool modules a forge/approval can create (the package marker excluded)."""
    root = os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools")
    return sorted(f[:-3] for f in os.listdir(root)
                  if f.endswith(".py") and f != "__init__.py") \
        if os.path.isdir(root) else []


PATTERN = ["fs.read", "fs.edit", "shell.exec"]
_old_mine, _old_pipe = SE.mine, SE.pipeline
SE.mine = lambda hist, c: [{"pattern": list(PATTERN), "support": 4}]


def _pipe(pattern, out, support=0, **kw):
    return {"ok": True, "dir": SE.draft(pattern, support, out) or "",
            "verify": {"green": True}, "archived": None}


SE.pipeline = _pipe
# EV-22: the abstraction step is a model call; this test is about the APPROVAL
# ring, so the naming step is off here (v727 covers it end to end).
configure(forge_on_evolve=True, forge_per_run=1, abstract_on_evolve=False)
policy("required")

# ------------------------------------- A: proposal, no code -------------
reports = improve.evolve_once()
row = (reports[0].get("matrix") or {})
pid = str(row.get("proposed") or "")
check("A1 a green pattern opens a matrix proposal", bool(pid), reports)
check("A2 no module was written before the approval", modules() == [], modules())
prop = improve.get_proposal(pid) or {}
arts = prop.get("artifacts") or []
check("A3 the proposal is pending and bound to one bundle",
      prop.get("status") == "pending" and prop.get("scope") == "matrix"
      and len(arts) == 1, prop)
body = str((arts[0] if arts else {}).get("content") or "")
check("A4 the bundle is the real generated module, hash-bound",
      "STEPS = " in body and arts[0].get("sha256")
      == hashlib.sha256(body.encode("utf-8")).hexdigest(), arts)

# ------------------------------------- B: approve -> written ------------
res = improve.decide(pid, "approve")
ns = str((arts[0] if arts else {}).get("name") or "")
installed = res.get("installed_to") or ""
check("B1 the approval applied the bundle", res.get("ok") is True, res)
check("B2 the module is on disk at the approved name", ns in modules(), modules())
path = os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools", ns + ".py")
disk = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
check("B3 the bytes written are the bytes approved",
      hashlib.sha256(disk.encode("utf-8")).hexdigest() == arts[0].get("sha256"), "")
check("B4 the proposal is recorded as approved", (improve.get_proposal(pid) or {})
      .get("status") == "approved", improve.get_proposal(pid))
check("B5 the install path is reported", ns + ".py" in installed, installed)

# ------------------------------------- C: live in the agent's dispatch --
discovered = MTX.discover_tools() or {}
check("C1 Matrix discovers the tool after hotload", ns + ".run" in discovered,
      sorted(discovered)[:6])
try:
    call = T.execute(ns + ".run", {}, run_id="v723")
except Exception as e:  # noqa: BLE001 — the point of the test
    call = {"ok": None, "error": "raised: %s" % e}
check("C2 the new tool is callable through the SAME dispatch",
      call.get("tool") == ns + ".run" or call.get("ok") is False, call)
check("C3 and it is fail-closed without its inputs",
      call.get("ok") is False and "inputs" in str(call.get("error")), call)
steps = MTX.execute_tool(ns + ".run", {"inputs": [{}, {}, {}]}, run_id="v723") or {}
check("C4 a real call reaches every step (each keeps its own policy)",
      steps.get("step_count") == 3 and steps.get("ok_count") is not None, steps)
MTX.remove("tool", ns)
check("C5 the loop can be undone (no leftover)", modules() == [], modules())

# ------------------------------------- D: deny writes nothing -----------
prop2 = improve.propose("matrix", "second mined sequence", origin="mining",
                        artifacts=[{"kind": "matrix_tool", "name": "learned_v723_deny",
                                    "content": "STEPS = ['fs.read']\nTOOL_SCHEMAS = {}\n"
                                               "TOOL_SCHEMA = {}\n"
                                               "def execute(args, run_id=None, subtool=None):\n"
                                               "    return {'ok': False}\n",
                                    "sha256": ""}])
deny = improve.decide(prop2["id"], "deny")
check("D1 a denied proposal writes no module", deny.get("ok") is True
      and "learned_v723_deny" not in modules(), (deny, modules()))
check("D2 and it is recorded as denied", (improve.get_proposal(prop2["id"]) or {})
      .get("status") == "denied", "")

# ------------------------------------- E: tampered bytes are refused ----
bad_body = "STEPS = ['fs.read']\nTOOL_SCHEMAS = {}\nTOOL_SCHEMA = {}\n" \
           "def execute(args, run_id=None, subtool=None):\n    return {'ok': True}\n"
prop3 = improve.propose("matrix", "tampered bundle", origin="mining",
                        artifacts=[{"kind": "matrix_tool", "name": "learned_v723_tamper",
                                    "content": bad_body,
                                    "sha256": "0" * 64}])
tamper = improve.decide(prop3["id"], "approve")
check("E1 a hash mismatch refuses the write", tamper.get("ok") is False
      and "hash" in str(tamper.get("error")).lower(), tamper)
check("E2 nothing landed", "learned_v723_tamper" not in modules(), modules())

SE.mine, SE.pipeline = _old_mine, _old_pipe
policy("")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
