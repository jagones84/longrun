#!/usr/bin/env python3
"""v1062 — an external MCP tool never receives the harness `workspace` key.

Measured 2026-11-15 (chrome-devtools, github, PMCP): the gate injected
`args["workspace"] = <session workspace>` into every tool whose `_origin` was not
`exclusive`/`delegation`. External tools are registered with `origin: "mcp"`, so a
strict server rejected the whole call:

    Input validation error: Invalid arguments for tool list_pages:
    Unrecognized key: "workspace"

while the same tool answered `{}` correctly when called directly. The rule is now
`_workspace_is_object_field()`: a tool whose `workspace` is the remote object's
business is never injected.

  A1 origin=mcp is never injected
  A2 exclusive / delegation keep their old exemption
  A3 `workspace.*` keeps its own exemption
  A4 a plain nucleous tool still receives the key
  A5 an unknown tool falls back to the old behaviour (inject)
  A6 both injection sites consult the helper
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1062-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A  # noqa: E402
from longrun.tools import registry as R  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


_SPECS = {
    "chrome-devtools__list_pages": {"origin": "mcp", "schema": {}},
    "github__get_me": {"origin": "mcp", "schema": {}},
    "agent.update": {"origin": "exclusive", "schema": {"_origin": "exclusive"}},
    "job.start": {"origin": "delegation", "schema": {"_origin": "delegation"}},
    "workspace.set": {"origin": "nucleous", "schema": {}},
    "shell.exec": {"origin": "nucleous", "schema": {}},
}
_real = R.tool_spec
R.tool_spec = lambda name, *a, **k: _SPECS.get(str(name))
try:
    check("A1 mcp chrome tool skipped",
          A._workspace_is_object_field("chrome-devtools__list_pages") is True)
    check("A1b mcp github tool skipped",
          A._workspace_is_object_field("github__get_me") is True)
    check("A2 exclusive skipped", A._workspace_is_object_field("agent.update") is True)
    check("A2b delegation skipped", A._workspace_is_object_field("job.start") is True)
    check("A3 workspace.* skipped", A._workspace_is_object_field("workspace.set") is True)
    check("A4 native tool still injected",
          A._workspace_is_object_field("shell.exec") is False)
    check("A5 unknown tool injects", A._workspace_is_object_field("nope.nothing") is False)
finally:
    R.tool_spec = _real

with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
    src = f.read()
check("A6 both doors inject through the one guarded helper",
      src.count("= _inject_workspace(tool, args, workspace)") == 2
      and src.count("and not _workspace_is_object_field(tool)") >= 1)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
