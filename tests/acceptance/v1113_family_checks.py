#!/usr/bin/env python3
"""v1113 — a check id is only named when a test already proves the family.

Round 45. Round 44 measured that 22 of 37 issues named no proving test. Two of the
five uncovered families already HAD a test that proves their answer, so the
register was under-reporting its own coverage:

  · `timeout` — v1094 A–C/F pin the `background: true` + `action=status` hint and
    the remedy that says the same thing (one truth).
  · `gate`    — v1093 pins that a plan-gate refusal is classified `gate`, capped at
    `warning`, and never ranked as a real fault: the register's own answer.

  A  every `check` id in `FAMILY_FIX` resolves to a test file (a check cannot rot)
  B  the two families now name their test; the catch-alls still say None
  C  a gate and a timeout failure carry the check on the issue row
  D  and the line the model reads prints it

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1113_family_checks.py
"""
import glob
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1113-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------- A: no rotting id -----------
ids = {fam: chk for fam, (_a, chk) in selfevolve.FAMILY_FIX.items() if chk}
missing = [chk for chk in ids.values()
           if not glob.glob(os.path.join(REPO, "tests", "acceptance", chk + "_*.py"))]
check("A1 every named check resolves to a test file", not missing, missing)
check("A2 and the map is not empty", len(ids) >= 5, ids)

# ------------------------------------------------- B: the two families --------
check("B1 `timeout` names the test that pins its hint and its remedy",
      selfevolve.FAMILY_FIX["timeout"][1] == "v1094", selfevolve.FAMILY_FIX["timeout"])
check("B2 `gate` names the test that pins the family's answer",
      selfevolve.FAMILY_FIX["gate"][1] == "v1093", selfevolve.FAMILY_FIX["gate"])
check("B3 the catch-alls still say no test covers them",
      selfevolve.FAMILY_FIX["tool-error"][1] is None
      and selfevolve.FAMILY_FIX["nonzero-exit"][1] is None
      and selfevolve.FAMILY_FIX["not-found"][1] is None, "")

# ------------------------------------------------- C: on the issue row -------
SESS = os.environ["LONGRUN_SESSIONS_DIR"]
with open(os.path.join(SESS, "s_a.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_a", "messages": [], "tool_cards": [
        {"tool": "shell.exec", "ok": False,
         "error": "plan mode: session s_a has an unapproved plan"},          # gate
        {"tool": "shell.exec", "ok": False,
         "error": "timeout — the terminal was reset"},                        # timeout
        {"tool": "fs.read", "ok": False, "error": "boom"},                    # tool-error
    ]}, f)

rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
by_fam = {i["family"]: i for i in rep["issues"]}
check("C1 the gate issue carries v1093", (by_fam.get("gate") or {}).get("check") == "v1093",
      by_fam.get("gate"))
check("C2 the timeout issue carries v1094",
      (by_fam.get("timeout") or {}).get("check") == "v1094", by_fam.get("timeout"))
check("C3 the coverage counts them as provable",
      (rep.get("checks") or {}).get("with_check") == 2
      and (rep.get("checks") or {}).get("without_check") == 1, rep.get("checks"))

# ------------------------------------------------- D: the line ---------------
lines = (T.execute("self", {"action": "failures", "limit": 10})
         .get("failure_lines") or [])
body = "\n".join(lines[:-1])          # the footer is the last line (round 44)
check("D1 the gate line names its check", "(check: v1093)" in body, body)
check("D2 the timeout line names its check", "(check: v1094)" in body, body)

print("\n---\nv1113: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
