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
  B  every family names a test; the round-46/47/48 re-points are the ids that
     closed the catch-alls (`not-found` → v1114, `nonzero-exit`/`tool-error` →
     v523, `no-change` → v748)
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
check("B3 every family names a test that proves its remedy",
      all(chk for (_action, chk) in selfevolve.FAMILY_FIX.values()),
      {fam: chk for fam, (_a, chk) in selfevolve.FAMILY_FIX.items()})
# Round 46 re-point: `not-found` left the catch-alls because v1114 was written to
# prove its remedy (a missing path names what exists near it). The pin moves with
# the map; it is not weakened — every named id is still resolved by A1.
check("B4 `not-found` now names the test that proves its remedy",
      selfevolve.FAMILY_FIX["not-found"][1] == "v1114",
      selfevolve.FAMILY_FIX["not-found"])
# Round 47 re-point: `nonzero-exit` and `tool-error` were uncovered because nobody
# had checked, not because no test proves them — v523 pins that a failed result's
# observation carries stderr, partial stdout and the error text.
check("B5 the two catch-alls name v523, which pins the evidence they read",
      selfevolve.FAMILY_FIX["nonzero-exit"][1] == "v523"
      and selfevolve.FAMILY_FIX["tool-error"][1] == "v523", "")
# Round 48 re-point: `no-change` was the last None — v748 F1/F2 pin that an empty
# step list is refused and that the refusal names `steps`.
check("B6 `no-change` names the test that proves its refusal",
      selfevolve.FAMILY_FIX["no-change"][1] == "v748",
      selfevolve.FAMILY_FIX["no-change"])

# ------------------------------------------------- C: on the issue row -------
SESS = os.environ["LONGRUN_SESSIONS_DIR"]
with open(os.path.join(SESS, "s_a.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_a", "messages": [], "tool_cards": [
        {"tool": "shell.exec", "ok": False,
         "error": "plan mode: session s_a has an unapproved plan"},          # gate
        {"tool": "shell.exec", "ok": False,
         "error": "timeout — the terminal was reset"},                        # timeout
        {"tool": "todo.update", "ok": False, "error": "changed nothing"},     # no-change
    ]}, f)

# Every family now names a check, so a MIXED register is produced explicitly:
# one family is lifted to None for the call and restored after. The coverage
# arithmetic (both sides) is what this section pins, not today's live share.
_fam, _pair = "no-change", selfevolve.FAMILY_FIX["no-change"]
selfevolve.FAMILY_FIX[_fam] = (_pair[0], None)
try:
    rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
finally:
    selfevolve.FAMILY_FIX[_fam] = _pair
by_fam = {i["family"]: i for i in rep["issues"]}
check("C1 the gate issue carries v1093", (by_fam.get("gate") or {}).get("check") == "v1093",
      by_fam.get("gate"))
check("C2 the timeout issue carries v1094",
      (by_fam.get("timeout") or {}).get("check") == "v1094", by_fam.get("timeout"))
check("C3 the coverage counts them as provable",
      (rep.get("checks") or {}).get("with_check") == 2
      and (rep.get("checks") or {}).get("without_check") == 1, rep.get("checks"))
check("C4 the lifted family's issue carries no check",
      (by_fam.get("no-change") or {}).get("check") is None, by_fam.get("no-change"))
_full = selfevolve.failure_candidates(limit=10, include_sessions=True)
check("C5 with the real map every issue of the fixture carries a check",
      (_full.get("checks") or {}).get("with_check") == 3
      and (_full.get("checks") or {}).get("without_check") == 0, _full.get("checks"))
# Round 48: at full coverage the footer says so instead of "0 say no test …".
_foot = (T.execute("self", {"action": "failures", "limit": 10})
         .get("failure_lines") or [])[-1:]
check("C6 at full coverage the footer says ALL issues name a test",
      bool(_foot) and _foot[0] == "(checks: all 3 issue(s) name a proving test)", _foot)

# ------------------------------------------------- D: the line ---------------
lines = (T.execute("self", {"action": "failures", "limit": 10})
         .get("failure_lines") or [])
body = "\n".join(lines[:-1])          # the footer is the last line (round 44)
check("D1 the gate line names its check", "(check: v1093)" in body, body)
check("D2 the timeout line names its check", "(check: v1094)" in body, body)

print("\n---\nv1113: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
