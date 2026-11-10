#!/usr/bin/env python3
"""v953 — a Teamorg grant unlocks CONFIG tools, never work across teams.

Operator case `J38` (2026-11-10): a lead (A54) whose session carries
`allow_longrun_agent` created `job.create {agents:[A1]}` for the Architect,
exit 0 — while its prompt said "only your subtree, anything outside is refused
(exit 126)". The handler's subtree check was there; the scope VALUE was wrong:
`coordinator_scope` returned None (the whole org) for any granted session.

The rule this pin fixes, in three words: **all · subtree · nothing**.
  all      — the Architect session (`longrunAgent*`) and an operator call with
             no caller (CLI / REST hand).
  subtree  — a coordinator (an agent with at least one direct report), all levels.
  nothing  — everyone else: a leaf delegates nothing, even with the grant.
A grant (`allow_longrun_agent`) unlocks the config tools (`agent.*`, `team.*`,
`provider.*` …). It does NOT widen the work scope.

Deterministic: temp stores, no server, no model, no network.
Run: python3 tests/acceptance/v953_grant_does_not_widen_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v953-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG           # noqa: E402
from longrun.agent import architect as LRA      # noqa: E402
from longrun.memory import stores as STORES      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


reg = AG.REGISTRY
LEAD = reg.designate("s-lead", name="Lead")["agent"]["id"]
SUB = reg.designate("s-sub", name="Sub", reports_to="s-lead")["agent"]["id"]
WORKER = reg.designate("s-worker", name="Worker", reports_to="s-sub")["agent"]["id"]
GRANT_LEAD = reg.designate("s-granted-lead", name="Granted Lead")["agent"]["id"]
GRANT_SUB = reg.designate("s-granted-sub", name="Granted Sub",
                          reports_to="s-granted-lead")["agent"]["id"]
OUTSIDE = reg.designate("s-outside", name="Outsider")["agent"]["id"]
GRANT_LEAF = reg.designate("s-granted-leaf", name="Granted Leaf")["agent"]["id"]


def _grant(sid):
    STORES.get_or_create_session(sid)
    res = LRA.set_session_access(sid, True)
    assert res.get("ok"), res


_grant("s-granted-lead")
_grant("s-granted-leaf")
STORES.get_or_create_session("s-lead")
STORES.get_or_create_session("s-outside")

# ---- A) the scope VALUE: three cases, one meaning each ---------------------
_gl = LRA.coordinator_scope("s-granted-lead")
check("A1 a granted COORDINATOR is its subtree, never the whole org",
      isinstance(_gl, set) and _gl == {GRANT_LEAD, GRANT_SUB}, _gl)
_leaf = LRA.coordinator_scope("s-granted-leaf")
check("A2 a granted LEAF has an empty scope (the grant is not a team)",
      _leaf == set(), _leaf)
check("A3 the Architect and the operator (no caller) keep the whole org",
      LRA.coordinator_scope("longrunAgent") is None
      and LRA.coordinator_scope(None) is None)
check("A4 a plain coordinator is unchanged",
      LRA.coordinator_scope("s-sub") == {SUB, WORKER},
      LRA.coordinator_scope("s-sub"))

# ---- B) the gate: a granted lead cannot job a foreign agent -----------------
_out = LRA.execute("job.create", {"goal": "poach", "agents": ["s-outside"]},
                   run_id="s-granted-lead")
check("B1 a granted coordinator naming an outsider is refused (exit 126)",
      _out.get("permission_denied") is True and _out.get("exit_code") == 126,
      _out.get("error") or _out)
_coord = LRA.execute("job.create", {"goal": "poach lead", "agents": ["s-granted-sub"],
                                    "coordinator": "s-lead"}, run_id="s-granted-lead")
check("B2 an outsider named as COORDINATOR is refused too",
      _coord.get("permission_denied") is True and _coord.get("exit_code") == 126,
      _coord.get("error") or _coord)
_ok = LRA.execute("job.create", {"goal": "own team work", "agents": ["s-granted-sub"]},
                  run_id="s-granted-lead")
check("B3 the same coordinator still creates a job inside its subtree",
      _ok.get("ok") is True
      and (_ok.get("job") or {}).get("coordinator") == GRANT_LEAD,
      _ok.get("error") or _ok)
_leafjob = LRA.execute("job.create", {"goal": "leaf job", "agents": ["s-outside"]},
                        run_id="s-granted-leaf")
check("B4 a granted LEAF is still refused (nobody reports to it)",
      _leafjob.get("permission_denied") is True and _leafjob.get("exit_code") == 126,
      _leafjob.get("error") or _leafjob)

# ---- C) the prompt says what the gate does ---------------------------------
_sess = STORES.load_session("s-granted-lead") or {"id": "s-granted-lead"}
_text = LRA.delegation_section(_sess)
check("C1 the coordinator prompt still lists its subtree",
      "SCOPE" in _text and "subtree" in _text, _text[:200])
check("C2 it states that a grant does not widen it",
      "grant does not widen" in _text.lower(), _text[:400])
check("C3 it never advertises the outsider", "Outsider" not in _text, "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
