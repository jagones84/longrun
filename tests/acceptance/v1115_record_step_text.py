#!/usr/bin/env python3
"""v1115 — a run-record step keeps the text that names its failure.

Round 49. The register classes a session card with `error or result`, so a failed
`shell` card whose text lives in stdout still gets a class. Run-record steps only
copied `error`, so the same failure reached the register as `(no error text)`:
measured 2026-11-18 on the 4 live records — 11 failed steps, 6 of them with an
empty `error` and a non-empty observation (`obs_chars` 74–1246).

  A  an empty `error` falls back to `result` (the text the model actually read)
  B  a real `error` is kept as-is (no second truth)
  C  the 200-char cap still holds
  D  `obs_chars` keeps describing `result`, never the fallback
  E  end to end: the register classes that step instead of `(no error text)`
  F  a card with nothing at all is still recorded without a crash

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1115_record_step_text.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="v1115-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
_RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"], _RUNS):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.harness import record  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------- A: the fallback ------------
steps = record._steps([
    {"tool": "shell", "ok": False, "exit_code": 1, "error": "",
     "result": "fatal: not a git repository (or any parent up to mount point /)",
     "backend": "none(host)"},
    {"tool": "fs.read", "ok": False, "error": "no such file: /a",
     "result": "content the model read", "backend": "harness"},
    {"tool": "shell.exec", "ok": False, "exit_code": 2, "error": "boom" * 200},
    {"tool": "shell", "ok": False},
])
check("A1 an empty error falls back to result", steps[0]["error"].startswith(
    "fatal: not a git repository"), steps[0]["error"])
check("B1 a real error is kept, result is not preferred",
      steps[1]["error"] == "no such file: /a", steps[1]["error"])
check("C1 the recorded text is still capped at ERROR_MAX",
      len(steps[2]["error"]) == record.ERROR_MAX, len(steps[2]["error"]))
check("D1 obs_chars still describes result, not the fallback",
      record._steps([{"tool": "shell", "ok": False, "error": "",
                      "result": "12345"}])[0]["obs_chars"] == 5, "")
check("F1 a card with nothing at all is recorded as empty",
      steps[3]["error"] == "" and steps[3]["obs_chars"] == 0, steps[3])

# ------------------------------------------------- E: the register -----------
with open(os.path.join(_RUNS, "r_one.json"), "w", encoding="utf-8") as f:
    json.dump({"run_id": "r_one", "steps": steps[:1]}, f)
rep = selfevolve.failure_candidates(limit=10, path=os.environ["LONGRUN_HARNESS_DIR"])
classes = [i.get("class") for i in rep.get("issues") or []] + \
          [c.get("error") for i in rep.get("issues") or []
           for c in (i.get("classes") or [])]
check("E1 the register classes the step from its text",
      any("fatal" in str(c) for c in classes), classes)
check("E2 and does NOT call it `(no error text)`",
      not any("(no error text)" in str(c) for c in classes), classes)

print("\n---\nv1115: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
