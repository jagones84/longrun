#!/usr/bin/env python3
"""v982 — a run can carry its OWN acceptance command, and "completed" means it passed (A1).

`run_44ea468b` (2026-11-14) closed `termination: completed` while its summary
said "checker green": the goal named `python3 scripts/check_proposal.py`, the
agent ran the target snapshot's older checker instead, and the named one FAILED
on three counts. The harness had no way to say what "done" means.

Contract:
  A) the request's spec is normalised (string or {command, expect_exit, timeout_secs})
     and bad input is refused with a reason;
  B) a passing check leaves `termination: completed` and records the verdict;
  C) a failing check changes the run's classification to `acceptance_failed` —
     a dependent that reads `termination` can no longer call it a success;
  D) the verdict is visible in the closure summary, labelled `[harness]`;
  E) a run with NO acceptance is unchanged.

Deterministic: scripted actions, local commands, no model, no server.

Run: python3 tests/acceptance/v982_run_acceptance.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v982-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SCRIPT = [{"action": "finish", "summary": "everything is green"}]

# --- A: the spec ------------------------------------------------------------
spec, err = API.acceptance_spec("python3 x.py")
check("A1 a command string is accepted", err == "" and spec["command"] == "python3 x.py", spec)
check("A2 it defaults to expect_exit=0 and a timeout",
      spec.get("expect_exit") == 0 and spec.get("timeout_secs", 0) >= 1, spec)
spec2, err2 = API.acceptance_spec({"command": "pytest -q", "expect_exit": 2,
                                   "timeout_secs": 30})
check("A3 the object form keeps its fields",
      err2 == "" and spec2 == {"command": "pytest -q", "expect_exit": 2,
                               "timeout_secs": 30}, spec2)
check("A4 an empty value means no check", API.acceptance_spec(None) == (None, ""))
for bad in ({"command": ""}, {"command": "x", "expect_exit": "a"},
            {"command": "x", "timeout_secs": 0}, 42):
    _s, _e = API.acceptance_spec(bad)
    check("A5 bad spec refused: %r" % (bad,), _s is None and bool(_e), _e)

# --- B: a passing check -----------------------------------------------------
EVENTS = []
res = API.agent_run_v2("goal A1 pass", max_steps=2, script=SCRIPT,
                       acceptance="true",
                       on_event=lambda kind, **d: EVENTS.append((kind, d)))
acc = res.get("acceptance") or {}
check("B1 termination stays completed", res.get("termination") == "completed",
      res.get("termination"))
check("B2 the verdict is recorded as a pass",
      acc.get("ok") is True and acc.get("exit_code") == 0, acc)
check("B3 the summary names the check and the pass",
      "[harness] acceptance PASS" in str(res.get("summary")), res.get("summary"))

# --- C/D: a failing check ---------------------------------------------------
res2 = API.agent_run_v2("goal A1 fail", max_steps=2, script=SCRIPT,
                        acceptance={"command": "exit 3"})
acc2 = res2.get("acceptance") or {}
check("C1 termination is no longer a success",
      res2.get("termination") == "acceptance_failed", res2.get("termination"))
check("C2 the exit code is the authority",
      acc2.get("ok") is False and acc2.get("exit_code") == 3, acc2)
check("D1 the summary states the failure with its code",
      "[harness] acceptance FAIL exit=3" in str(res2.get("summary")), res2.get("summary"))
check("D2 the model's own words are still there",
      str(res2.get("summary")).startswith("everything is green"), res2.get("summary")[:40])

# --- E: no acceptance -> unchanged -----------------------------------------
res3 = API.agent_run_v2("goal plain", max_steps=2, script=SCRIPT)
check("E1 a run without a check is completed", res3.get("termination") == "completed")
check("E2 and records no verdict", res3.get("acceptance") is None, res3.get("acceptance"))
check("E3 and adds no acceptance line", "acceptance" not in str(res3.get("summary")),
      res3.get("summary"))

ok = sum(RESULTS)
print("\nv982: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
