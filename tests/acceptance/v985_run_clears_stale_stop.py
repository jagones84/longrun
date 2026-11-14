#!/usr/bin/env python3
"""v985 — a Stop on one turn must not condemn the NEXT run of that session.

`agent_run_v2` honours the session-level abort flag (`checkpoint`/`cancel_of`),
but only a CHAT turn clears it at its start (`httpapi.py` + `api_v02.py` chat
path). A session-bound run therefore inherited a flag set by a Stop pressed on
previous work and died on its FIRST checkpoint with
`termination="aborted"`, `summary="aborted by operator"` — the record blaming the
operator for a Stop they pressed on something else. Only an intervening chat
turn healed it.

Contract:
  A) a run on a session whose flag is set still runs to its own end;
  B) the flag is cleared by the run itself (a run is a NEW turn);
  C) the run's record is its real outcome, not "aborted by operator";
  D) a Stop that arrives DURING the run still aborts it (the fix does not disarm
     the operator).

Deterministic: scripted actions, no model, no server, isolated temp dirs.

Run: python3 tests/acceptance/v985_run_clears_stale_stop.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v985-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.util import steering  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SESS = stores.get_or_create_session(None, "v985 session")
SID = SESS["id"]
steering.push_abort(SID)
check("A0 the session really carries a stale Stop", steering._is_aborted(SID))

res = API.agent_run_v2("goal after a stop", max_steps=2,
                       script=[{"action": "finish", "summary": "ran anyway"}],
                       session=SID)
check("A1 the run reached its own finish",
      res.get("termination") == "completed", res.get("termination"))
check("B1 the stale flag is cleared by the run", not steering._is_aborted(SID))
check("C1 the record is the real outcome, not a phantom abort",
      res.get("summary") == "ran anyway", res.get("summary"))

# --- D: a Stop DURING the run still aborts it -----------------------------
SID2 = stores.get_or_create_session(None, "v985 live stop")["id"]


def _stop_then_finish(kind, **d):
    # The SCRIPTED path emits `agent.thought`, not `agent.iteration`; the flag
    # set at step 1 must be honoured by the checkpoint at step 2.
    if kind == "agent.thought":
        steering.push_abort(SID2)


res2 = API.agent_run_v2("goal stopped mid-run", max_steps=3,
                        script=[{"action": "note", "detail": "one"},
                                {"action": "finish", "summary": "should not finish"}],
                        session=SID2, on_event=_stop_then_finish)
check("D1 a live Stop still aborts the run",
      res2.get("termination") == "aborted", res2.get("termination"))

ok = sum(RESULTS)
print("\nv985: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
