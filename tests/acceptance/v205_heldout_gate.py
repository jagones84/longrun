#!/usr/bin/env python3
"""v205 — sealed held-out promotion gate (RDD punto 2 / JAG-205).

Deterministic, no model, no sandbox (runner injected). Proves that
`selfevolve.promote` is FAIL-CLOSED behind an external, hash-pinned judge suite
that the agent cannot read or tamper with:

  A) integrity: a manifest matches its files; corrupting a file breaks it;
  B) gate = integrity AND suite run (green only if both);
  C) promote REFUSES when the external suite is red, even if the proposal is
     locally `verified` (and even if the proposal's own check.py passes) -> F;
  D) promote archives only when local-verified AND the gate is green;
  E) a missing held-out dir -> fail-closed (no_manifest).

Run:  python3 tests/v205_heldout_gate.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

tmp = tempfile.mkdtemp(prefix="sf-205-")
os.environ["LONGRUN_HELDOUT_DIR"] = os.path.join(tmp, "heldout")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "1"
suite = os.path.join(os.environ["LONGRUN_HELDOUT_DIR"], "suite")
os.makedirs(suite, exist_ok=True)
check_all = os.path.join(suite, "check_all.py")
with open(check_all, "w", encoding="utf-8") as f:
    f.write("print('judge: invariants ok')\n")

from longrun.plan import heldout  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fake_run(**k):
    return (FAKE_GREEN, "judge output", 1)


def make_proposal(name):
    d = os.path.join(tmp, "prop_" + name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "verified", "name": name}, f)
    return d


# ---- A: integrity ----
heldout.pin()
check("A1 manifest matches files", heldout.integrity()["ok"], str(heldout.integrity()["reason"]))
with open(check_all, "a", encoding="utf-8") as f:
    f.write("# tampered\n")
bad = heldout.integrity()
check("A2 corrupted file breaks integrity", not bad["ok"] and bad["reason"] == "integrity",
      str(bad["files"])[:100])
heldout.pin()
check("A3 re-pin restores integrity", heldout.integrity()["ok"], "")

# ---- B: gate = integrity AND run ----
check("B1 gate green when suite passes",
      heldout.gate(runner=lambda s, c: (True, "ok"))["green"], "")
red = heldout.gate(runner=lambda s, c: (False, "boom"))
check("B2 gate red when suite fails",
      (not red["green"]) and red["reason"] == "run_failed", str(red["reason"]))

# ---- C: promote refuses at red gate ----
FAKE_GREEN = False
heldout.run = _fake_run
p_refuse = make_proposal("candx")
res = selfevolve.promote(p_refuse, skills_dir=os.path.join(tmp, "skills"))
check("C1 promote refused at red gate", not res.get("ok"), str(res.get("error"))[:80])
check("C2 refusal carries the gate report", "gate" in res and not res["gate"]["green"], "")
check("C3 nothing archived", not os.path.exists(
    os.path.join(tmp, "skills", "auto", "candx")), "")

# ---- D: promote archives at green gate ----
FAKE_GREEN = True
p_ok = make_proposal("candy")
res2 = selfevolve.promote(p_ok, skills_dir=os.path.join(tmp, "skills"))
check("D1 promote ok at green gate", res2.get("ok"), str(res2)[:100])
check("D2 archived to skills/created/<name>",
      os.path.isdir(os.path.join(tmp, "skills", "created", "candy")), "")

# ---- F: gate ignores a manipulated LOCAL check.py ----
p_fake = make_proposal("candz")
with open(os.path.join(p_fake, "check.py"), "w", encoding="utf-8") as f:
    f.write("import sys\nsys.exit(0)  # always green locally\n")
FAKE_GREEN = False  # external judge still red
res_f = selfevolve.promote(p_fake, skills_dir=os.path.join(tmp, "skills"))
check("F1 external judge governs (local check.py ignored)", not res_f.get("ok"),
      str(res_f.get("error"))[:80])

# ---- E: missing held-out dir -> fail-closed ----
good_dir = os.environ["LONGRUN_HELDOUT_DIR"]
os.environ["LONGRUN_HELDOUT_DIR"] = os.path.join(tmp, "nope")
g = heldout.gate(runner=lambda s, c: (True, "ok"))
check("E1 missing dir -> gate not green", not g["green"] and g["reason"] == "no_manifest",
      str(g["reason"]))
res_e = selfevolve.promote(make_proposal("candw"), skills_dir=os.path.join(tmp, "skills"))
check("E2 promote fail-closed on missing dir", not res_e.get("ok"), str(res_e.get("error"))[:80])
os.environ["LONGRUN_HELDOUT_DIR"] = good_dir

shutil.rmtree(tmp, ignore_errors=True)
ok = sum(results)
print("\nv205: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

