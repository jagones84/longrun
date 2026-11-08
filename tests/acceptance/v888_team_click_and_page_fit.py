#!/usr/bin/env python3
"""v888 — the team header toggles on a click, the architect never runs local, and the
deck stops growing.

Operator, 2026-11-08:
  *"still i can't manually expand a team in the Agents panel in Control"*
  *"the checkbox only agents without ROLE.md"* (it was the widest thing in the bar)
  *"can the architect edit specific things with no need to recreate from zero … does its
    tools enable to edit anything … everything settable by the webui?"*
  *"the architect is never finishing … its LLM model set in the session chatbox is not
    working (it's a local model)"*
  *"i cannot collapse the architect work by a single word"*
  *"make a bit smaller the setting gear and remove that frame"*
  *"the panels in control shall be bottom anchored to the bottom of the html page"*

Root cause of the click, found in the engine: `DragSort.bind` called
`setPointerCapture` on POINTERDOWN, which retargets the compatibility `click` to the
capture element — so the team header's own disclosure never received it (v886 only fixed
the suppression, not the retargeting). Capture is now taken when the drag really starts.

Pinned here:
  A) a click keeps its target; the capture is deferred past the move threshold;
  B) the deck: a two-word checkbox, a one-word disclosure for the record, a page-filling
     grid, and a bounded wait on the run;
  C) an automation turn NEVER runs on a local model;
  D) the settings gear is smaller and frameless;
  E) every field the WebUI can set on an object has a tool property that sets it.

Deterministic: temp dirs, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-888-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
for _d in ("sessions", "graphs", "roles", "ws"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


DRAG = open(os.path.join(REPO, "webui", "assets", "dragsort.js"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
INDEX = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

# ---- A: a click on a control inside a drag handle keeps its target ----------
_down = DRAG[DRAG.index('handle.addEventListener("pointerdown"'):DRAG.index('handle.addEventListener("touchstart"')]
check("A1 pointerdown does NOT capture (that is what ate the click)",
      "setPointerCapture(e.pointerId)" not in _down)
check("A2 the capture happens when the drag really starts (threshold first)",
      "if (!state.live) {" in _down
      and "Math.hypot(ev.clientX - state.startX, ev.clientY - state.startY) < MOVE_PX" in _down
      and "handle.setPointerCapture(state.pointerId)" in _down)
check("A3 the move/up listeners live on window, so an uncaptured drag still ends",
      'window.addEventListener("pointermove", move)' in _down
      and 'window.addEventListener("pointerup", up, true)' in _down)
check("A4 a real drag still swallows its tail click",
      "state.live = true;\n    state.suppressClick = true;" in DRAG)

# ---- B: the deck stops growing --------------------------------------------
check("B1 the ROLE.md scope checkbox is two words",
      '<input type="checkbox" id="lraAutoEmpty" checked> empty ROLE.md' in ORBIT)
check("B2 the record is ONE disclosure a single word opens",
      '<details class="replog"><summary class="small muted">what Architect wrote · ' in ORBIT
      and ".replog>summary{cursor:pointer" in ORBIT)
check("B3 the page is a column and the agent grid takes the free height",
      "body{display:flex;flex-direction:column;height:100%}" in ORBIT
      and ".wrap.deck{flex-direction:row;gap:8px;align-items:stretch;flex:1 1 auto;min-height:0}" in ORBIT
      and ".grid2.ab{flex:1 1 auto;min-height:0}" in ORBIT)
check("B4 the bar stops waiting instead of spinning forever",
      "Promise.race([" in ORBIT and "no answer after 4 minutes" in ORBIT)

# ---- C: an automation turn is never local ---------------------------------
from longrun.agent import longrun_agent as lra          # noqa: E402
from longrun.memory import stores                       # noqa: E402
from longrun.orchestrate import teams as teams_mod      # noqa: E402

_local = "dgx:qwen-3.8-27b-uncensored-q4"
_local_from_session = lra.resolve_automation_model(active_session_id=None, explicit_model=_local)
check("C1 an explicitly local model is refused for an automation run",
      teams_mod.machine_of(_local_from_session) is None, _local_from_session)
stores.save_session({"id": "sessLocal", "title": "t", "model": _local, "messages": []})
_resolved = lra.resolve_automation_model(active_session_id="sessLocal", explicit_model="@chat")
check("C2 a session model that is local does not leak into the run",
      teams_mod.machine_of(_resolved) is None, _resolved)
check("C3 a cloud choice is kept as it is",
      lra.resolve_automation_model(explicit_model="openrouter:z-ai/glm-5.3-flash")
      == "openrouter:z-ai/glm-5.3-flash")

# ---- D: the settings gear -------------------------------------------------
check("D1 the gear is smaller and frameless",
      "#settingsBtn { width: 26px; height: 26px; padding: 0; border: 0; background: transparent;" in INDEX)
check("D2 the old bordered rule is gone",
      "#settingsBtn { border-color: var(--line-2); color: var(--dim); }" not in INDEX)

# ---- E: everything the WebUI can set has a tool that sets it --------------
SET_BY_UI = {
    "agent.create": ["name", "role", "prompt", "model", "reports_to", "team",
                     "workspace", "daily_budget"],
    "agent.update": ["name", "role", "reports_to", "workspace", "daily_budget"],
    "team.create": ["name", "description", "symbol", "color", "members"],
    "team.update": ["name", "description", "symbol", "color"],
    "team.member_add": ["team", "agent"],
    "team.member_remove": ["team", "agent"],
    "job.create": ["goal", "coordinator", "agents", "deps", "mode", "blocked_by"],
    "job.update": ["goal", "coordinator", "agents", "deps", "mode", "blocked_by"],
    "routine.create": ["agent", "goal", "every_seconds"],
    "routine.update": ["agent", "goal", "every_seconds", "enabled", "model"],
    "session.rename": ["title"],
}
_missing = []
for tool, fields in SET_BY_UI.items():
    props = (lra.TOOL_SCHEMAS.get(tool) or {}).get("properties") or {}
    for f in fields:
        if f not in props:
            _missing.append(tool + "." + f)
check("E1 every settable field has a tool property", not _missing, _missing)
check("E2 model is the ONE deliberate exception (it is the operator's routing call)",
      "NEVER change an agent's model" in lra.SECTION_PROMPTS["teamorg"])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
