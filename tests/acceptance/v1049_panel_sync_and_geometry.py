#!/usr/bin/env python3
"""v1049 — one filter for the whole Sessions page, job→agent sync, a movable panel.

Operator, 2026-11-16:

  *"the filter in sessions lh panel doesn't update the ORG chart and the AGENTS
    panel … in orbit they are all synchronized … it shall remain … no duplications.
    This is valid also for jobs, and clicking on jobs and subjobs in the webui shall
    cause relevant agents to activate in AGENTS panel and session synced and also the
    map/org…"*

  *"why grant Teamorg/Architect to the orchestrator if it is already enabled by
    default? … the boss of the ORG of a team, only the top ones … shall have it
    naturally enabled, then I can revoke"*

  *"the floating panel opened by the open the agent panel button shall be movable
    and resizable by hand"*

Contract:
  A) the rail's ONE FilterSort state is pushed to the hosted deck, which writes it
     into its own FilterSort and repaints — agents, jobs, org and map share it;
  B) a job/subjob click activates the agent behind it (the active session), so every
     panel follows one selection;
  C) the floating panel is dragged by its head and resized in both axes, and its
     geometry survives a reload and a restart;
  D) Teamorg/Architect is a tri-state: explicit grant/revoke wins, and with no
     decision a TOP org leader has it by default (a plain chat does not);
  E) teams already are `T<n>` objects with a create/update/delete lifecycle, and the
     rail shows that id — no new object is introduced.

Deterministic: static contracts plus a fake org registry for (D). No server, model
or network.
Run: python3 tests/acceptance/v1049_panel_sync_and_geometry.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
TEAMS = open(os.path.join(REPO, "src", "longrun", "orchestrate", "teams.py"),
             encoding="utf-8").read()
STORES = open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"),
              encoding="utf-8").read()
PROMPT = open(os.path.join(REPO, "src", "longrun", "model", "prompt.py"),
              encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one filter state for every hosted panel --------------------------------
check("A1 the host sends its FilterSort state with every panel switch",
      'function _dpFilterState()' in UI
      and 'Object.assign({}, FilterSort.get("sessions"))' in UI
      and 'msgs.push({ type: "longrun-scope-filter", state: fst })' in UI)
check("A2 a rail filter change pushes the same state to the open panel",
      'loadSessions(); _dpPushFilter();' in UI
      and 'function _dpPushFilter()' in UI
      and '_dpPostReady([{ type: "longrun-scope-filter", state: st }])' in UI)
check("A3 the deck applies it to ITS OWN FilterSort and repaints (no second state)",
      'd.type === "longrun-scope-filter"' in ORBIT
      and "app.fs.setSilent(st)" in ORBIT
      and "app.agents.sort = st.sort" in ORBIT
      and "app.agents.dir = st.dir" in ORBIT
      and "app.refresh();" in ORBIT)
check("A4 a hosted deck hides its own funnel — the rail owns the control",
      "html.embed-panel #agFilterBtn{display:none!important}" in ORBIT)
check("A5 the deck's team scope already reaches agents/jobs/org/map",
      "const team = this.team;" in ORBIT
      and "const inTeam = (a) => (!team || team === \"ALL\"" in ORBIT
      and "const fJobs = jobs ? {jobs: (jobs.jobs || []).filter(" in ORBIT
      and "if (this.org) this.org.teams = this.teams;" in ORBIT)

# ---- B: a job click activates its agent ---------------------------------------
check("B1 the subjob's own agent, then the coordinator, resolves to a session",
      "async function _jobFocusSession(jid)" in UI
      and "const candidates = [sub.agent, j.coordinator]" in UI
      and "sid = _sessOfAgentLabel(label)" in UI
      and "if (sid !== sessionId)" in UI
      and "selectSession(s)" in UI)
check("B2 the job panel opens only AFTER that sync (one selection, then the panel)",
      "async function _showJobInControl(jid)" in UI
      and "try { await _jobFocusSession(full); } catch (e) {}" in UI
      and 'type: "longrun-focus-job"' in UI)
check("B3 the active session is what rings agents and the org chart",
      "focusAgentSession(sid){" in ORBIT
      and "this.agents.focusAgent(sid, true);" in ORBIT
      and "this.org.selectNode(sid, true);" in ORBIT)

# ---- C: movable + resizable panel, remembered --------------------------------
check("C1 the window is dragged by its head, never through its controls",
      "function _dpDrag()" in UI
      and 'e.target.closest("button, a, input, select, textarea")' in UI
      and 'head.classList.add("dragging")' in UI)
check("C2 a corner grip resizes width AND height",
      'id="pvGrip" class="pv-grip"' in UI
      and "bind(grip, false);" in UI and "bind(corner, true);" in UI
      and "if (both) el.style.height = h + \"px\";" in UI)
check("C3 the geometry is persisted and clamped back on screen",
      'localStorage.setItem("sf_panel_geo", JSON.stringify(g))' in UI
      and 'JSON.parse(localStorage.getItem("sf_panel_geo") || "null")' in UI
      and "left = Math.max(0, Math.min(left, Math.max(0, vw - w)));" in UI)

# ---- D: Teamorg/Architect — explicit decision, else top leader ---------------
from longrun.agent import architect as LRA           # noqa: E402
from longrun.agent import agents as AG               # noqa: E402

_orig_reg = AG.REGISTRY


class FakeReg:
    """The org used by both paths: one record (`resolve`/`reports_of`) and a roster."""

    def __init__(self):
        self.rows = [{"id": "A1", "session": "boss1", "reports_to": None},
                     {"id": "A2", "session": "chat9", "reports_to": "A1"}]
        self.by_session = {r["session"]: r for r in self.rows}
        self.by_id = {r["id"]: r for r in self.rows}

    def resolve(self, ref):
        return self.by_session.get(str(ref)) or self.by_id.get(str(ref))

    def reports_of(self, ref):
        a = self.resolve(ref)
        if not a:
            return []
        return sorted(r["id"] for r in self.rows if r.get("reports_to") == a["id"])

    def list(self):
        return {"agents": [dict(r) for r in self.rows]}


try:
    AG.REGISTRY = FakeReg()
    check("D1 no decision + a top boss (nobody above, agents below) = granted",
          LRA.access_from_record({"id": "boss1"}) is True)
    check("D2 no decision + a bare session (every session has an agent record) = not granted",
          LRA.access_from_record({"id": "chat9"}) is False)
    check("D3 an explicit revoke wins over the default",
          LRA.access_from_record({"id": "boss1", "allow_architect": False}) is False)
    check("D4 an explicit grant wins over the default",
          LRA.access_from_record({"id": "chat9", "allow_architect": True}) is True)
    check("D5 the Architect session itself always has access",
          LRA.access_from_record({"id": LRA.ARCHITECT_SESSION_ID}) is True)
    m = LRA.effective_access_map([
        {"id": "boss1"}, {"id": "chat9"}, {"id": "revoked", "allow_architect": False},
        {"id": "given", "allow_architect": True}])
    check("D6 one roster pass resolves the whole list",
          m == {"boss1": True, "chat9": False, "revoked": False, "given": True}, m)
finally:
    AG.REGISTRY = _orig_reg

check("D7 the tool gate uses the tri-state, not the raw field",
      "return access_from_record(stores.load_session(sid))" in
      open(os.path.join(REPO, "src", "longrun", "agent", "architect.py"),
           encoding="utf-8").read())
check("D8 the prompt section follows the same decision (never promises less)",
      "granted = lra.access_from_record(sess) if isinstance(sess, dict) else False" in PROMPT)
check("D9 the roster keeps the undecided state and resolves it once per list",
      '"allow_architect": (s.get("allow_architect")' in STORES
      and "from longrun.agent.architect import effective_access_map" in STORES
      and 'r["allow_architect"] = bool(eff[r["id"]])' in STORES)

# ---- E: teams already are T<n> objects ---------------------------------------
check("E1 a team is created with the next T<n> id",
      '"id": "T%d" % n' in TEAMS and 'd["seq"] += 1' in TEAMS)
check("E2 it has the same lifecycle as every other object",
      "def update(self, ref" in TEAMS and "def delete(self, ref)" in TEAMS
      and "def set_members(self, ref, aids)" in TEAMS)
check("E3 the Sessions rail shows the team id beside its name",
      '<span class="gid">' in UI and 'esc(g.id)' in UI)
check("E4 the rail's team menu can copy that id",
      'data-a="copy">⧉ Copy team id' in UI and '_pvCopy(tid)' in UI)

print("---")
print("v1049: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
