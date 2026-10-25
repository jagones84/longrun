#!/usr/bin/env python3
"""v618 — shell can no longer curl around the dual-permission gate.

Incident: session b7329cccf94c got a correct 126 on job.get (no Teamorg
grant), then the agent lifted LONGRUN_TOKEN from the repo .env via shell
and curled POST /api/jobs/J22/dispatch around the gate. v616 scrubbed
the token from observations but did NOT stop the bypass itself.

Fixes pinned:
  E1 denial message names FULL as non-bypass + tells operator the exact
     grant and tells the agent the no-grant alternative (dispatch, not
     job.*) and never shell/curl.
  E2 shell hard-deny blocks the bypass ingredients: LONGRUN_TOKEN,
     grep of .env, curl to the local API jobs/agents/teams/longrun-agent
     (both 127.0.0.1 and localhost).
  E3 prompt copy disambiguates `dispatch` (teammate turn, no grant) from
     `job.dispatch` (waves, grant needed, no shell needed).

Deterministic: temp dirs, no server, no model, no network.
Run: python3 tests/acceptance/v618_permit_shell_bypass.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v618-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.tools import registry as REG  # noqa: E402
from longrun.agent import longrun_agent as LRA  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SID = "v618-gate-probe"
STORES.get_or_create_session(SID)
LRA.set_session_access(SID, False)

# E1: denial is actionable (FULL named, grant path, alternative, no shell)
_ok, _why = LRA.check_dual_permission("job.get", SID)
check("E1a denial names FULL as non-bypass",
      _ok is False and "approvals.mode=full does NOT" in _why, _why)
check("E1b denial gives the exact grant call",
      "/api/longrun-agent/access" in _why and "allow_longrun_agent" in _why)
check("E1c denial names the no-grant alternative and forbids shell/curl",
      "`dispatch`" in _why and "never shell/curl" in _why)
_d, _r = REG.classify("job.get", {"run_id": SID})
check("E1d classify and execute paths deny identically (one truth)",
      _d == "denied" and _r == _why)

# E2: shell bypass ingredients are hard-denied
J22_CMD = ("cd /home/jagones/Repositories/longrun && TOK=$(grep -oP "
           "'LONGRUN_TOKEN:\\K.*' .env | tr -d '\"'); "
           "curl -s -m 20 -X POST "
           "\"http://127.0.0.1:8790/api/jobs/J22/dispatch?token=$TOK\"")
_d0, _r0 = REG.classify("shell", {"command": J22_CMD})
check("E2a the exact J22 bypass command is hard-denied",
      _d0 == "denied" and "hard-deny" in _r0, _r0)
for label, cmd in [
    ("token name", "echo $LONGRUN_TOKEN"),
    ("grep .env", "grep -oP 'LONGRUN_TOKEN' .env"),
    ("curl localhost jobs", "curl http://localhost:8790/api/jobs/J22/dispatch"),
    ("curl 127 agents", "curl http://127.0.0.1:8790/api/agents"),
    ("curl 127 teams", "curl http://127.0.0.1:8790/api/teams/T1/reset"),
]:
    _d1, _r1 = REG.classify("shell", {"command": cmd})
    check("E2b hard-deny: %s" % label, _d1 == "denied", _r1)
_d2, _r2 = REG.classify("shell", {"command": "ls /tmp"})
check("E2c legit shell still auto-approved (no overblock)",
      _d2 == "auto", (_d2, _r2))

# E3: prompt copy disambiguates dispatch vs job.dispatch
AGENT_SRC = _read("src", "longrun", "agent", "agent.py")
check("E3 prompt names waves, FULL non-bypass, and the two dispatches",
      "run the dependency waves in order (job.dispatch, no shell needed)" in AGENT_SRC
      and "approvals.mode=full does NOT bypass it" in AGENT_SRC
      and "`dispatch` (a teammate turn, no grant needed)" in AGENT_SRC)

print("---")
ok = sum(results)
print("\nv618: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
