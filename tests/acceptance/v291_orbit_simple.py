#!/usr/bin/env python3
"""v291 — Team derivation + job-by-recipient + the simplified Orbit page (JAG-293).

Locked here:
  * `team_of(ref)` = the agent plus its DIRECT reports (a job's auto team);
  * POST /api/jobs with `assignee` derives agents + coordinator from the org chart;
  * the simplified Orbit page: agents table (model + reports-to), a graphical
    org chart, a job form (goal + assignee); the old panels are gone; every id
    used by the JS exists in the markup.

Deterministic, no live model. Run: python3 tests/v291_orbit_simple.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v291-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402

AR = agents.REGISTRY
AR.designate("sess-a", name="Ana", role="analyst")
AR.designate("sess-b", name="Bob", reports_to="sess-a")
AR.designate("sess-c", name="Cy", reports_to="sess-a")
AR.designate("sess-d", name="Dee", reports_to="sess-b")

# --- team_of = self + direct reports ---------------------------------------
check("team_of is the agent plus its DIRECT reports", AR.team_of("A1") == ["A1", "A2", "A3"])
check("team_of of a leaf is just itself", AR.team_of("A4") == ["A4"])
check("team_of of an unknown agent is empty", AR.team_of("A999") == [])


class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


# --- API: a job assigned to an agent derives its team ----------------------
fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/jobs", {}, {"goal": "build it", "assignee": "A1"})
job = fh.sent["obj"]["job"]
# v629: the derived team is the assignee's ORG SUBTREE, not only its direct
# reports — `subjob_depth` (config/jobs.yaml, default 3) decides how deep. The
# fixture has A4 (Dee) reporting to A2 (Bob), so the job now covers her too and
# her subjob nests as JN.2.1.
check("POST /api/jobs with assignee derives the org subtree + coordinator",
      ok and job["agents"] == ["A1", "A2", "A3", "A4"] and job["coordinator"] == "A1",
      str(job["agents"]))
check("the derived job is coordinator mode", job["mode"] == "coordinator")

fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/jobs", {}, {"goal": "x", "assignee": "A999"})
check("a job for an unknown agent is refused", ok and fh.sent["obj"]["ok"] is False)

# --- UI wiring -------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("the agents table has a model + reports-to control",
      'id="agBody"' in ui and 'data-f="model"' in ui and 'data-f="reports_to"' in ui)
check("agents are creatable with +", 'id="agNew"' in ui and '＋ new agent' in ui)
check("the job form is goal + assignee",
      'id="jobGoal"' in ui and 'id="jobTo"' in ui and "{goal, assignee}" in ui)
check("routines + feed are kept", 'id="rtCreate"' in ui and 'id="feed"' in ui)
check("the old panels are gone",
      "Tactical Task Graph" not in ui and "Model Bay" not in ui
      and "Decision queue" not in ui and "class BoardView" not in ui
      and "class ModelBayView" not in ui)

import re  # noqa: E402
_ids = set(re.findall(r'\$\("([A-Za-z0-9_]+)"\)', ui))
_missing = sorted(i for i in _ids if ('id="%s"' % i) not in ui)
check("every $() id used by the JS exists in the markup", _missing == [],
      "missing=" + ",".join(_missing))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

