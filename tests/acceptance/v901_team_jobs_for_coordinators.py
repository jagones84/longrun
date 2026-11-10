#!/usr/bin/env python3
"""v901 — team jobs (job.*) belong to every COORDINATOR, at every org level.

Operator: *"job tools shall be allowed to all the agents that have other agents
reporting to them … at cascade level … the dispatched agent can call other
dependent jobs … its not an exclusive tool, remove from there and put in the
baseline tools"*.

Before this, `job.*` was an EXCLUSIVE tool: only the Architect or a session the
operator granted `allow_architect` could touch it, and `approvals.mode=full`
did not lift it. A dispatched lead therefore had to improvise dependencies with
sequential dispatches.

Contract pinned here:
  A) GATE — a `job.*` call needs the ORG CHART, not a grant: an agent with at
     least one direct report may; a leaf agent, an unrelated session and any
     unknown session may not; the Architect keeps the unrestricted path.
  B) SCOPE (cascade) — a coordinator may name only agents in its OWN SUBTREE,
     and may touch only jobs its subtree contains (reads) / it coordinates (writes).
  C) DEPENDENCIES — a coordinator can create a job `blocked_by` another job and
     release only its own blocked jobs with `job.wake`.
  D) ONE CLASS — the schemas are `_origin: "delegation"` (not "exclusive"), the
     registry reports that origin, and the coordinator's prompt tells it the tools
     and its scope from LIVE state.

Deterministic: temp stores, no model, no server, no network.
Run: python3 tests/acceptance/v901_team_jobs_for_coordinators.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v901-")
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
from longrun.model import prompt as P            # noqa: E402
from longrun.orchestrate import jobs as JM       # noqa: E402
from longrun.tools import registry as REG        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- the org chart: lead -> sub -> worker, plus two unconnected agents -------
reg = AG.REGISTRY
LEAD = reg.designate("s-lead", name="Lead")["agent"]["id"]
SUB = reg.designate("s-sub", name="Sub", reports_to="s-lead")["agent"]["id"]
WORKER = reg.designate("s-worker", name="Worker", reports_to="s-sub")["agent"]["id"]
SOLO = reg.designate("s-solo", name="Solo")["agent"]["id"]
OTHER = reg.designate("s-other", name="Other")["agent"]["id"]


# ---- A) the gate is the org chart ------------------------------------------
_ok, _why = LRA.check_delegation("job.create", "s-solo")
check("A1 a leaf agent (nobody below it) may NOT run a team job",
      _ok is False and "nobody reporting" in _why, _why)
check("A2 a direct report is enough (first level)",
      LRA.check_delegation("job.create", "s-lead")[0] is True)
check("A3 every manager below is a coordinator too (cascade)",
      LRA.check_delegation("job.create", "s-sub")[0] is True)
check("A4 a non-agent session may not", LRA.check_delegation("job.create", "s-nobody")[0] is False)
check("A5 the Architect keeps the whole org",
      LRA.check_delegation("job.create", "architect")[0] is True)
_d, _r = REG.classify("job.delete", {"run_id": "s-solo"})
_d2, _r2 = REG.classify("job.delete", {"run_id": "s-lead"})
check("A6 classify() carries the same verdict (one gate, two entry points)",
      _d == "denied" and "nobody reporting" in _r and _d2 != "denied", (_d, _d2))

# ---- B) the scope is the caller's subtree ---------------------------------
check("B1 the scope of a middle manager is its own subtree",
      LRA.coordinator_scope("s-sub") == {SUB, WORKER}, LRA.coordinator_scope("s-sub"))
check("B2 the top lead sees the whole cascade",
      LRA.coordinator_scope("s-lead") == {LEAD, SUB, WORKER},
      LRA.coordinator_scope("s-lead"))
check("B3 a leaf has an empty scope (not 'everything')",
      LRA.coordinator_scope("s-solo") == set())
check("B4 the Architect / a grant is unrestricted",
      LRA.coordinator_scope("architect") is None and LRA.coordinator_scope(None) is None)

# ---- C) create / read / mutate inside the subtree -------------------------
_lead = LRA.execute("job.create", {"goal": "lead job", "agents": [SUB]}, run_id="s-lead")
J_LEAD = (_lead.get("job") or {}).get("id")
check("C1 a coordinator creates a job; the coordinator defaults to itself",
      _lead.get("ok") is True
      and (_lead.get("job") or {}).get("coordinator") == LEAD, _lead.get("error") or _lead)
_out = LRA.execute("job.create", {"goal": "poach", "agents": [OTHER]}, run_id="s-lead")
check("C2 an agent outside the subtree is REFUSED (exit 126, not a silent retarget)",
      _out.get("permission_denied") is True and _out.get("exit_code") == 126
      and "outside your org subtree" in str(_out.get("error")), _out.get("error"))
_leaf = LRA.execute("job.create", {"goal": "solo job", "agents": [SOLO]}, run_id="s-solo")
check("C3 a leaf agent is refused by the same path", _leaf.get("permission_denied") is True,
      _leaf.get("error"))

_sub = LRA.execute("job.create", {"goal": "dependent sub job", "agents": [WORKER],
                                  "blocked_by": [J_LEAD]}, run_id="s-sub")
J_SUB = (_sub.get("job") or {}).get("id")
check("C4 a dispatched lead creates a DEPENDENT job at cascade level",
      _sub.get("ok") is True and (_sub.get("job") or {}).get("status") == "blocked"
      and (_sub.get("job") or {}).get("coordinator") == SUB, _sub.get("error") or _sub)

check("C5 a job containing the caller's team is readable",
      LRA.execute("job.get", {"job": J_LEAD}, run_id="s-sub").get("ok") is True)
check("C6 a job coordinated by someone else cannot be deleted",
      LRA.execute("job.delete", {"job": J_LEAD}, run_id="s-sub")
      .get("permission_denied") is True)
_other = LRA.execute("job.create", {"goal": "other team job", "agents": [OTHER]},
                     run_id="architect")
J_OTHER = (_other.get("job") or {}).get("id")
_listed = LRA.execute("job.list", {}, run_id="s-sub")
_ids = {j.get("id") for j in _listed.get("jobs") or []}
check("C7 job.list shows the caller's jobs and hides a foreign team's",
      J_SUB in _ids and J_LEAD in _ids and J_OTHER not in _ids, sorted(_ids))
check("C8 where a coordinator's job is not readable at all, job.get refuses",
      LRA.execute("job.get", {"job": J_LEAD}, run_id="s-other")
      .get("permission_denied") is True)

# ---- D) wake releases only the caller's blocked jobs ----------------------
_captured = {}
_real_wake = JM.JOBS.wake


def _fake_wake(only=None):
    _captured["only"] = only
    return {"released": [], "failed": []}


JM.JOBS.wake = _fake_wake
try:
    _w = LRA.execute("job.wake", {}, run_id="s-sub")
finally:
    JM.JOBS.wake = _real_wake
check("D1 job.wake is scoped to the caller's blocked jobs",
      _w.get("ok") is True and _captured.get("only") == [J_SUB], _captured.get("only"))

# ---- E) one class, declared once ------------------------------------------
_origin = (REG.tool_spec("job.create") or {}).get("schema", {}).get("_origin")
check("E1 job.* is its own class, not 'exclusive'",
      _origin == "delegation"
      and "job" not in {k.split(".", 1)[0] for k, v in LRA.TOOL_SCHEMAS.items()
                        if isinstance(v, dict) and v.get("_origin") == "exclusive"},
      _origin)
check("E2 the registry reports the origin (the Tool panel badge reads it)",
      (REG.tool_spec("job.dispatch") or {}).get("origin") == "delegation",
      (REG.tool_spec("job.dispatch") or {}).get("origin"))
check("E3 the router accepts the new origin",
      "_origin\") in (\"exclusive\", \"delegation\")" in
      open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
           encoding="utf-8").read())

# ---- F) the coordinator's prompt is generated from live state -------------
_sec = LRA.delegation_section({"id": "s-sub"})
check("F1 a coordinator is TOLD it owns job.* and who is in scope",
      "Your team jobs" in _sec and "job.create" in _sec
      and (SUB in _sec and WORKER in _sec) and LEAD not in _sec, _sec[:200])
check("F2 a leaf agent gets no section (it would be a lie)",
      LRA.delegation_section({"id": "s-solo"}) == "")
check("F3 the Architect uses its own section", LRA.delegation_section({"id": "architect"}) == "")
check("F4 the section is wired into the prompt registry",
      any(s["id"] == "delegation" for s in P.SECTIONS)
      and P._PROVIDERS.get("delegation") is not None)
# F5: through the REAL renderer, so the wiring is proven end to end (registry ->
# provider -> section text), not just the function in isolation.
_texts = P.section_texts({"id": "s-sub", "title": "Sub"})
check("F5 the rendered prompt carries it for a coordinator",
      "Your team jobs" in (_texts.get("delegation") or ""),
      (_texts.get("delegation") or "")[:80])
_texts_leaf = P.section_texts({"id": "s-solo", "title": "Solo"})
check("F6 the rendered prompt carries nothing for a leaf",
      not (_texts_leaf.get("delegation") or ""))

_bad = results.count(False)
print("\n%d/%d checks passed%s" % (len(results) - _bad, len(results),
                                   "" if not _bad else " — FAILED"))
sys.exit(1 if _bad else 0)
