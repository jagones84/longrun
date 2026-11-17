#!/usr/bin/env python3
"""v1081 — a verifier that passes everything verifies nothing.

Measured 2026-11-18: 115 of 134 auto-skill proposals stored ONE case
(`verify.cases == {"default": true}`) — a structural boolean — so the promotion
gate could not distinguish a real check from a vacuous one. `verify` now runs
the artifact's OWN check against three mutations of the artifact; each mutation
must be CAUGHT (non-zero exit), and the stored case table names them
(`catches:corrupt-json`, `catches:no-steps`, `catches:unknown-tool`).

Contract:
  M1 a vacuous check is rejected: nothing is caught
  M2 a discriminating check is verified: every mutation is caught
  M3 a non-skill artifact keeps today's single case (no mutations)
  M4 a skill without steps only owes the corrupt-JSON catch
  M5 an injected runner is a harness check: mutations are skipped
  M6 the artifact is never touched (same bytes before and after)
  M7 a sandbox error is NOT a catch (fail closed)

Deterministic: temp dirs, real python3, no model, no network.
Run: python3 tests/acceptance/v1081_verifier_mutations.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1081-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
for d in ("data", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


VACUOUS = '#!/usr/bin/env python3\nimport sys\nprint("ok")\nsys.exit(0)\n'
DISCRIMINATING = '''#!/usr/bin/env python3
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    art = json.load(open(os.path.join(HERE, "skill.json"), encoding="utf-8"))
except (OSError, ValueError) as e:
    print("unreadable:", e); sys.exit(1)
steps = art.get("steps")
if not isinstance(steps, list) or not steps:
    print("no steps"); sys.exit(1)
if any(not isinstance(s, dict) or s.get("tool") != "fs.read" for s in steps):
    print("bad step"); sys.exit(1)
print("ok")
sys.exit(0)
'''


def mk(name, check_src, skill=None):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
        f.write(check_src)
    if skill is not None:
        with open(os.path.join(d, "skill.json"), "w", encoding="utf-8") as f:
            json.dump(skill, f)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "proposed", "name": name}, f)
    return d


SKILL = {"name": "s", "steps": [{"tool": "fs.read", "args": {"path": "a"}},
                                {"tool": "fs.read", "args": {"path": "b"}}]}

# ---- M1: a check that always exits 0 catches nothing -------------------------
d1 = mk("vacuous", VACUOUS, SKILL)
cases, runs, applied = SE.mutation_report(d1)
check("M1a every mutation is offered", sorted(applied) == [
    "catches:corrupt-json", "catches:no-steps", "catches:unknown-tool"], applied)
check("M1b a vacuous check catches none",
      cases and not any(cases.values()), cases)
rep = SE.verify(d1)
prop = json.load(open(os.path.join(d1, "proposal.json"), encoding="utf-8"))
check("M1c the verify is RED", rep.get("green") is False, rep)
check("M1d the proposal is rejected",
      prop.get("status") == "rejected" and prop.get("green_streak") == 0,
      (prop.get("status"), prop.get("green_streak")))
check("M1e the case table names what was not caught",
      all(k in (rep.get("cases") or {}) for k in applied)
      and not any(rep["cases"][k] for k in applied), rep.get("cases"))
check("M1f the report lists the mutations it ran",
      sorted(rep.get("mutations") or []) == sorted(applied), rep.get("mutations"))

# ---- M2: a discriminating check catches every mutation -----------------------
d2 = mk("real", DISCRIMINATING, SKILL)
rep2 = SE.verify(d2)
prop2 = json.load(open(os.path.join(d2, "proposal.json"), encoding="utf-8"))
check("M2a the verify is GREEN", rep2.get("green") is True, rep2)
check("M2b every mutation was caught", all(rep2["cases"][k] for k in applied),
      rep2.get("cases"))
check("M2c the proposal is verified", prop2.get("status") == "verified", prop2.get("status"))
check("M2d the evidence now spans more than one case",
      len(rep2.get("cases") or {}) >= 4, rep2.get("cases"))

# ---- M3: a non-skill artifact keeps the single case -------------------------
d3 = mk("project", VACUOUS)
check("M3a no mutations are derived", SE._artifact_mutations(d3) == [])
c3, r3, a3 = SE.mutation_report(d3)
rep3 = SE.verify(d3)
check("M3b verify stays single-case and green",
      rep3.get("green") is True and rep3.get("cases") == {"default": True}
      and rep3.get("mutations") == [], (rep3.get("cases"), rep3.get("mutations")))

# ---- M4: a skill without steps owes only the corrupt-JSON catch --------------
PARSE_ONLY = '''#!/usr/bin/env python3
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    json.load(open(os.path.join(HERE, "skill.json"), encoding="utf-8"))
except (OSError, ValueError) as e:
    print("unreadable:", e); sys.exit(1)
sys.exit(0)
'''
d4 = mk("nosteps", PARSE_ONLY, {"name": "s", "steps": []})
ids = [k for k, _ in SE._artifact_mutations(d4)]
check("M4 only the corrupt-JSON mutation applies", ids == ["catches:corrupt-json"], ids)
rep4 = SE.verify(d4)
check("M4b it is caught and the verify is green",
      rep4.get("green") is True and rep4["cases"]["catches:corrupt-json"] is True,
      rep4.get("cases"))

# ---- M5: an injected runner skips mutations ---------------------------------
d5 = mk("harness", VACUOUS, SKILL)
rep5 = SE.verify(d5, runner=lambda _d, _c: (True, "ok"))
check("M5 an injected runner is not mutation-tested",
      rep5.get("green") is True and rep5.get("cases") == {"default": True}
      and rep5.get("mutations") == [], rep5.get("cases"))

# ---- M6: the artifact is untouched ------------------------------------------
raw = open(os.path.join(d2, "skill.json"), "rb").read()
check("M6 the artifact bytes are identical after the mutations",
      hashlib.sha256(raw).hexdigest() == hashlib.sha256(
          open(os.path.join(d2, "skill.json"), "rb").read()).hexdigest()
      and json.loads(raw.decode()) == SKILL)

# ---- M7: a sandbox error is not a catch -------------------------------------
d7 = mk("sanderr", VACUOUS, SKILL)
old = SE._run_check
SE._run_check = lambda _d, _c, _cfg: (False, "sandbox error: no backend")
try:
    c7, _r7, _a7 = SE.mutation_report(d7)
finally:
    SE._run_check = old
check("M7 a broken sandbox fails the mutation cases (no fabricated evidence)",
      c7 and not any(c7.values()), c7)

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1081: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
