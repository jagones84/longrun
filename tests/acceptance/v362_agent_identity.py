#!/usr/bin/env python3
"""v362 — harmonise the prompt layers: the AGENT identity is real (JAG-362).

Before this, `_provider_role` returned "" whenever the session had no ROLE.md, so
an agent with no role file contributed NOTHING to the system prompt: every agent
looked identical to the model and the agent's own name/label never reached it
(33 agents, only 3 role files on the live instance).

  A) the `agent-role` section always states the agent identity (A# · name ·
     label) and appends the session ROLE.md when set — behavioural, via a temp
     agents.json + roles dir;
  B) the Rules panel shows WHO the session is, and a stale tab self-heals.

Run: python3 tests/acceptance/v362_agent_identity.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v362-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.makedirs(os.environ["LONGRUN_ROLES_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

_AGENTS = {"seq": 2, "agents": {
    "sess_a1": {"id": "A1", "n": 1, "session": "sess_a1", "name": "Tester", "role": "QA"},
    "sess_a2": {"id": "A2", "n": 2, "session": "sess_a2", "name": "Builder", "role": "Dev"},
}}
with open(os.environ["LONGRUN_AGENTS_FILE"], "w", encoding="utf-8") as f:
    json.dump(_AGENTS, f)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import prompt  # noqa: E402
from longrun.orchestrate import roles  # noqa: E402

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    SRV = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8") as f:
    SRV += f.read()

# --- A: the agent identity is really in the prompt ---------------------------
t1 = prompt._provider_role({"id": "sess_a1"}, None, None)
check("A1 an agent with NO role file still announces its identity",
      "A1" in t1 and "Tester" in t1 and "QA" in t1, t1.replace("\n", " | ")[:110])
check("A2 it says the identity is the roster's, not the ROLE.md",
      "this agent" in t1 and "No extra role text is set" in t1, "")
check("A3 two agents get DIFFERENT prompt sections",
      t1 != prompt._provider_role({"id": "sess_a2"}, None, None)
      and "Builder" in prompt._provider_role({"id": "sess_a2"}, None, None), "")
roles.write("sess_a1", "Answer with the endpoint list only.")
t2 = prompt._provider_role({"id": "sess_a1"}, None, None)
check("A4 the session ROLE.md is appended under the identity",
      "endpoint list only" in t2 and "A1" in t2, "")
check("A5 a plain session with nothing set contributes nothing",
      prompt._provider_role({"id": "sess_plain"}, None, None) == "", "")
check("A6 no session id -> empty (never raises)",
      prompt._provider_role({}, None, None) == "" and prompt._provider_role(None, None, None) == "", "")
check("A7 the docstring names the layer order",
      "GLOBAL Global_rules.md" in prompt._provider_role.__doc__
      and "PROJECT Project_rules.md" in prompt._provider_role.__doc__, "")

# --- B: the panel shows who, and a stale tab self-heals ----------------------
check("B1 the Rules panel states the agent identity",
      'id="rulesWho"' in HTML and ".rwho {" in HTML
      and 'api("GET", "/api/agents")' in HTML, "")
check("B2 it falls back to 'ad-hoc session' when not designated",
      "ad-hoc session (no agent)" in HTML, "")
check("B3 the server exposes a build fingerprint",
      'if path == "/api/build":' in SRV and '"build": _b' in SRV, "")
check("B4 the SPA notices a build change WITHOUT restarting the open tab (JAG-500)",
      "async function _checkBuild()" in HTML and "function _offerReload()" in HTML
      and "t.onclick = () => location.reload();" in HTML
      and "b !== _build0) { _build0 = b; location.reload(); }" not in HTML
      and 'setInterval(_checkBuild, 60000)' in HTML, "")
check("B5 the sandbox pill says what it means",
      'sb.isolated ? "sandboxed" : "no sandbox"' in HTML
      and "no sandbox" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

