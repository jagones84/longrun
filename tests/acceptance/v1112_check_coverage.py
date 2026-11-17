#!/usr/bin/env python3
"""v1112 — the register states how much of itself is provable.

Round 44. `FAMILY_FIX` names a test id only for four of the nine families, so a
draft can say "re-read `self.failures` … to prove the issue is gone" for a family
no test covers. Measured 2026-11-18 over the live store: **22 of 37** issues name
no check, including **5 of the top 8**. The register now reports its own coverage.

  A  the answer carries the coverage of the WHOLE register, not of the shown rows
  B  a family with a check counts as provable, one without does not
  C  the line the model reads states both numbers, and they match the payload
  D  the API carries it, and an empty store answers with the key
  E  the panel's count names the provable share

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1112_check_coverage.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1112-")
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
from longrun.core import httpapi  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------- A: nothing yet --------------
empty = httpapi.improvement_failures()
check("A1 an empty store still carries the key, with zeros",
      empty.get("checks") == {"with_check": 0, "without_check": 0, "total": 0}, empty)

# ------------------------------------------------- B: a mixed register ---------
SESS = os.environ["LONGRUN_SESSIONS_DIR"]
with open(os.path.join(SESS, "s_a.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_a", "messages": [], "tool_cards": [
        {"tool": "shell.exec", "ok": False,
         "error": "shell.exec: missing REQUIRED argument 'cmd'"},       # → v510
        {"tool": "fs.read", "ok": False, "error": "boom"},              # → no check
    ]}, f)

rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
ch = rep.get("checks") or {}
fams = {(i["family"], bool(i.get("check"))) for i in rep["issues"]}
check("B1 one family with a check, one without",
      fams == {("missing-argument", True), ("tool-error", False)}, fams)
check("B2 the coverage counts the whole register",
      ch.get("with_check") == 1 and ch.get("without_check") == 1
      and ch.get("total") == 2, ch)

# ------------------------------------------------- C: the line the model reads -
lines = (T.execute("self", {"action": "failures", "limit": 1})
         .get("failure_lines") or [])
tail = lines[-1] if lines else ""
check("C1 the answer ends with its own coverage, matching the payload",
      tail == "(checks: 1 of 2 issue(s) name a proving test; 1 say no test "
              "covers the family yet)", tail)
check("C2 even though only one issue was shown", len(lines) == 2, lines)

# ------------------------------------------------- D: the API -----------------
api = httpapi.improvement_failures(limit=10)
check("D1 the API carries the same numbers", api.get("checks") == ch, api.get("checks"))
check("D2 and the rows keep their own check",
      {i["family"]: i.get("check") for i in api["issues"]} ==
      {"missing-argument": "v510", "tool-error": None}, api["issues"])

# ------------------------------------------------- E: the panel ---------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the count names the provable share",
      "chk.total" in UI and "chk.with_check" in UI and "/" in UI
      and "checked" in UI, "")
check("E2 and the legend says a fix is provable only where a check exists",
      "provable only where a" in UI and "check exists" in UI, "")

print("\n---\nv1112: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
