#!/usr/bin/env python3
"""v977 — the finish summary is stored VERBATIM, never cut at 600 chars (H1).

A live run (2026-11-14, `run_44ea468b`) ended with `agent.finish.data.summary`
exactly 600 chars long and cut mid-word ("…baseline-v66-su"): both run loops
truncated the ONLY closure artefact the harness keeps, with no ellipsis, so the
record of what the agent claimed to have done could not be read back.

Contract:
  A) the ONE owner (`api_v02.finish_summary`) keeps a long summary whole;
  B) the real run loop (`agent_run_v2`) stores and emits that whole text;
  C) the legacy loop (`agent.agent_run`) goes through the same owner — no
     second truncation site.

Deterministic: scripted actions, no model, no server, isolated temp dirs.

Run: python3 tests/acceptance/v977_finish_summary_verbatim.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v977-")
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


# --- A: the owner never cuts ------------------------------------------------
LONG = "".join("step %02d: checked the artefact.\n" % i for i in range(120))
check("A1 a long summary is returned whole",
      API.finish_summary({"summary": LONG}) == LONG,
      len(API.finish_summary({"summary": LONG})))
check("A2 an empty summary still says 'done'",
      API.finish_summary({"action": "finish"}) == "done")
check("A3 a non-string summary is stringified",
      API.finish_summary({"summary": 42}) == "42")

# --- B: the live run loop keeps it -----------------------------------------
EVENTS = []
res = API.agent_run_v2("goal H1", max_steps=2,
                       script=[{"action": "finish", "summary": LONG}],
                       on_event=lambda kind, **d: EVENTS.append((kind, d)))
finish = [d for k, d in EVENTS if k == "agent.finish"]
check("B1 the run result carries the whole summary",
      res.get("summary") == LONG, len(res.get("summary") or ""))
check("B2 agent.finish carries the whole summary",
      bool(finish) and finish[-1].get("summary") == LONG,
      len((finish[-1].get("summary") if finish else "") or ""))
check("B3 it is the agent's text, not a cut fragment",
      res.get("summary", "").rstrip().endswith("artefact."),
      res.get("summary", "")[-30:])

# --- C: one owner for both loops -------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as fh:
    _agent_src = fh.read()
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as fh:
    _api_src = fh.read()
check("C1 the legacy loop calls the shared owner",
      "api_v02.finish_summary(act)" in _agent_src)
check("C2 no finish summary is cut at 600 chars any more",
      'act.get("summary", ""))[:600]' not in _api_src
      and 'act.get("summary", ""))[:600]' not in _agent_src)

ok = sum(RESULTS)
print("\nv977: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
