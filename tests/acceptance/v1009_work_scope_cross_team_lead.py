#!/usr/bin/env python3
"""v1009 — work-scope rule B: a job may go to ANOTHER team's lead (R7).

The work-scope page records the operator's rule: a coordinator may hand a job
to another team's LEAD as long as every worker is inside that lead's subtree; a
bare member stays refused. The code used to refuse any coordinator outside the
caller's subtree, so the page and the product disagreed.

This pin also covers the half that makes the hand-off usable: the creator keeps
the job it created (`assigned_by`), so it can read, dispatch and delete it —
without that, `job.create` produced an id with no next verb.

Deterministic: temp stores, no server, no model, no network.
Run: python3 tests/acceptance/v1009_work_scope_cross_team_lead.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1009-")
for key, value in (
        ("LONGRUN_DATA_DIR", TMP),
        ("LONGRUN_AGENTS_FILE", os.path.join(TMP, "agents.json")),
        ("LONGRUN_JOBS_FILE", os.path.join(TMP, "jobs.json")),
        ("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions")),
        ("LONGRUN_GRAPH_DIR", os.path.join(TMP, "graphs")),
        ("LONGRUN_DB", os.path.join(TMP, "events.db"))):
    os.environ[key] = value
os.makedirs(os.path.join(TMP, "sessions"), exist_ok=True)
os.makedirs(os.path.join(TMP, "graphs"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG          # noqa: E402
from longrun.agent import architect as LRA     # noqa: E402
from longrun.memory import stores as STORES    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


reg = AG.REGISTRY
LEAD1 = reg.designate("s-lead", name="Lead One")["agent"]["id"]
SUB1 = reg.designate("s-sub", name="Sub One", reports_to="s-lead")["agent"]["id"]
LEAD2 = reg.designate("s-lead2", name="Lead Two")["agent"]["id"]
SUB2 = reg.designate("s-sub2", name="Sub Two", reports_to="s-lead2")["agent"]["id"]
BARE = reg.designate("s-bare", name="Bare Member")["agent"]["id"]
for sid in ("s-lead", "s-lead2", "s-bare"):
    STORES.get_or_create_session(sid)

# ---- A) the hand-off: another team's LEAD is allowed -----------------------
_hand = LRA.execute("job.create", {"goal": "cross-team hand-off",
                                   "coordinator": "s-lead2", "agents": ["s-sub2"]},
                    run_id="s-lead")
_job = _hand.get("job") or {}
check("A1 a coordinator may name another team's LEAD as coordinator",
      _hand.get("ok") is True and _job.get("coordinator") == LEAD2,
      _hand.get("error") or _job)
check("A2 the creator is recorded as the assigner",
      str(_job.get("assigned_by") or "") == LEAD1, _job.get("assigned_by"))

# ---- B) the boundaries that stay closed -----------------------------------
_bare = LRA.execute("job.create", {"goal": "bare hand-off",
                                   "coordinator": "s-bare", "agents": ["s-bare"]},
                    run_id="s-lead")
check("B1 a BARE member outside the subtree is still refused (exit 126)",
      _bare.get("permission_denied") is True and _bare.get("exit_code") == 126,
      _bare.get("error") or _bare)
_outworker = LRA.execute("job.create", {"goal": "wrong team",
                                        "coordinator": "s-lead2", "agents": ["s-bare"]},
                         run_id="s-lead")
check("B2 a worker outside the new lead's subtree is refused (exit 126)",
      _outworker.get("permission_denied") is True and _outworker.get("exit_code") == 126,
      _outworker.get("error") or _outworker)
_own = LRA.execute("job.create", {"goal": "own team", "agents": ["s-sub"]},
                   run_id="s-lead")
check("B3 the plain own-subtree job is unchanged",
      _own.get("ok") is True and (_own.get("job") or {}).get("coordinator") == LEAD1,
      _own.get("error") or _own)

# ---- C) the creator keeps the job, the receiving lead owns it --------------
_scope1 = LRA.coordinator_scope("s-lead")
_scope2 = LRA.coordinator_scope("s-lead2")
check("C1 the ASSIGNER may read, dispatch and delete its own cross-team job",
      LRA._job_in_scope(_job, _scope1, mutate=True, caller="s-lead") is True)
check("C2 the receiving lead still owns the job by coordinator scope",
      LRA._job_in_scope(_job, _scope2, mutate=True, caller="s-lead2") is True)
check("C3 an unrelated coordinator gets neither",
      LRA._job_in_scope(_job, _scope1, mutate=True, caller=None) is False)

# ---- D) the read surface carries the job cost aggregate (R6) ---------------
_got = LRA.execute("job.get", {"job": _job.get("id")}, run_id="s-lead")
_cost = (_got.get("job") or {}).get("cost") or {}
check("D1 job.get exposes the per-job cost aggregate",
      _got.get("ok") is True and _cost.get("job") == _job.get("id")
      and {"tokens", "usd", "seconds", "turns"} <= set(_cost),
      _cost)

# ---- E) the prompt says what the gate does --------------------------------
_text = LRA.delegation_section(STORES.load_session("s-lead") or {"id": "s-lead"})
check("E1 the coordinator prompt names the one allowed hand-off",
      "another team's LEAD" in _text, _text[:600])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
