#!/usr/bin/env python3
"""v1044 — the Sessions page owns the AGENTS affordances and one reusable panel window.

Operator, 2026-11-16:
  *"i dont see the tree dot i see on the control panel in the agent session. i want to
    bring the AGENTS panel features into the sessions page left panel (leave as is for
    backup the control panel) … also job panel … the same for org chart and constellation
    … use the already done functions dont replicate codebase."*

Contract:
  A) the Sessions rail header exposes Agents / Jobs / Org / Constellation;
  B) every real team header carries the SAME assign + kebab as the Control AGENTS table,
     while the v910 No-team contract is untouched;
  C) the session row menu carries the AGENTS row actions, and the heavy editors/pickers
     are opened in the deck through postMessage (no second form in index.html);
  D) one reusable #panelView iframe hosts exactly one deck panel, scoped to the active
     session; closing it stops the frame;
  E) the deck understands `?panel=`, `longrun-show-panel`, `longrun-scope-session`,
     `longrun-team-action` and `longrun-agent-editor`, and never rewrites the Control
     tab's saved view/filter;
  F) Jobs defaults to the active session, offers an All toggle and reads the in-session
     SJ ledger from the existing route.

Deterministic: static contract on webui/index.html, webui/assets/filtersort.js and
src/longrun/orbit/web/orbit.html. No server, model or network.
Run: python3 tests/acceptance/v1044_session_agents_panels.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
FS = open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: rail header entry points ------------------------------------------------
for btn, label in (("railAgents", "agents"), ("railJobs", "jobs"),
                   ("railOrg", "org"), ("railConst", "constellation")):
    tag = UI[UI.find('id="%s"' % btn) - 120:UI.find('id="%s"' % btn) + 700]
    check("A1 %s is a named button" % btn,
          'id="%s"' % btn in UI and 'aria-label="open the %s' % label in tag
          and 'title="open the %s' % label in tag)
check("A2 the four buttons are bound to the one opener",
      '[["railAgents", "agents"], ["railJobs", "jobs"], ["railOrg", "org"], ["railConst", "const"]]'
      in UI and "b.onclick = () => _openDeckPanel(panel)" in UI)

# ---- B: team headers ------------------------------------------------------------
check("B1 assign + new agent are items of the team kebab (no separate icon)",
      'data-a="assign">＋ Assign agents…' in UI
      and 'data-a="newagent">＋ New agent…' in UI
      and 'class="gassign"' not in UI and "openTeamAssign" not in UI)
check("B2 every real team also gets the kebab",
      'g.key === "__none__" ? \'<button class="gkebab"' in UI
      and ': (g.id ? `<button class="gkebab" aria-label="team actions"' in UI)
check("B3 the v910 No-team menu/copy/route is still verbatim",
      '"/api/teams/__none__/" + action' in UI
      and all(x in UI for x in ("Reset all sessions…", "Compact all sessions…",
                                "Drop OLD plans…", "Delete ALL sessions…")))
check("B4 a real team's menu offers edit/policy/delete without a second engine",
      'data-a="edit"' in UI and 'data-a="policy"' in UI and 'data-a="del"' in UI
      and '"/api/teams/" + encodeURIComponent(tid) + "/models"' in UI
      and '"/api/teams/" + encodeURIComponent(tid) + "/" + action' in UI)
check("B5 create/automate in the team kebab run the deck's OWN controls",
      'data-a="newjob">＋ New job…' in UI
      and 'data-a="architect">✨ Automate with Architect…' in UI
      and '_dpPostAgentsAction("new-job")' in UI
      and '_dpPostAgentsAction("architect")' in UI
      and 'applyView(_act === "new-job" ? "jobs" : "agents")' in ORBIT
      and 'if (action === "new-job")' in ORBIT)

# ---- C: row menu + delegated editors -------------------------------------------
check("C1 the row menu carries the AGENTS actions",
      all(x in UI for x in ('data-a="prompt"', 'data-a="teams"', 'data-a="reports_to"',
                            'data-a="model"', 'data-a="release"')))
check("C2 every editor is delegated into the deck (no second form here)",
      '_dpPostAgent(s.id, "prompt")' in UI and '_dpPostAgent(s.id, "teams")' in UI
      and '_dpPostAgent(s.id, "reports_to")' in UI and '_dpPostAgent(s.id, "model")' in UI
      and "longrun-agent-editor" in ORBIT and "openTeamPicker" in ORBIT
      and "openAgentEditor" in ORBIT and "openPrompt" in ORBIT)
check("C3 release uses the existing agent DELETE route",
      'api("DELETE", "/api/agents/" + encodeURIComponent(s.id))' in UI)
check("C4 the rail shows the AGENTS row truth (empty ROLE.md + model)",
      'api("GET", "/api/orbit/sessions")' in UI and "_sessMeta" in UI
      and "EMPTY ROLE.md - this agent runs on the bare system prompt" in UI
      and '"model: " + _model' in UI and '"ROLE.md: " + _meta.prompt_chars' in UI)
check("C5 the A-id opens the organigram like the AGENTS table",
      'class="jid" role="button" tabindex="0"' in UI and "_showAgentInOrganigram(s.id)" in UI)
check("C6 right-click opens the SAME menus on sessions and teams",
      "d.oncontextmenu" in UI and "openSessMenu(d, s, ag, e)" in UI
      and "head.oncontextmenu" in UI and "openTeamMenu(head, g, e)" in UI
      and ".sess-menu { position: fixed;" in UI and "max-height: calc(100dvh" in UI)
check("C7 every other object has a right-click too (one dispatcher, no per-widget copies)",
      "function _wireObjectContextMenu()" in UI and "_wireObjectContextMenu();" in UI
      and "if (e.defaultPrevented) return;" in UI and "function _openCtx(" in UI
      and "Copy this text" in UI)

# ---- D: one reusable window -----------------------------------------------------
check("D1 there is exactly one panel window and one iframe",
      UI.count('id="panelView"') == 1 and UI.count('id="panelFrame"') == 1
      and UI.count('id="controlView"') == 1)
check("D2 the window has the four panel tabs and a named close",
      all('data-panel="%s"' % p in UI for p in ("agents", "jobs", "org", "const"))
      and 'id="pvClose" aria-label="close panel"' in UI)
check("D3 the URL is the deck's own embedded panel, scoped to the session",
      '"/orbit?embed=1&panel=" + encodeURIComponent(panel)' in UI
      and '"&session=" + encodeURIComponent(sid)' in UI)
check("D4 closing stops the deck (about:blank), Escape closes",
      'f.setAttribute("src", "about:blank")' in UI
      and 'e.key === "Escape" && el && !el.hidden' in UI)
check("D5 the full Control tab remains the backup door",
      'if ($("pvControl")) $("pvControl").onclick = () => { _closeDeckPanel(true); showControl(); }' in UI)
check("D6 the window follows the active session",
      '_DP.sid = sessionId; _dpPaint(_DP.panel); _dpSend(_DP.panel);' in UI)
check("D7 the constellation/org/job bridges now target #panelFrame",
      'const f = document.getElementById("panelFrame");' in UI
      and "_ensureDeckPanel(\"const\")" in UI and "_ensureDeckPanel(\"org\")" in UI
      and "_ensureDeckPanel(\"jobs\")" in UI
      and 'postMessage({ type: "longrun-focus-node", id: id, session: sid }' in UI)

# ---- E: the deck guest mode -----------------------------------------------------
check("E1 the deck marks itself as an embedded panel from ?panel=",
      'if(/[?&]panel=/.test(location.search))document.documentElement.classList.add("embed-panel")' in ORBIT
      and "html.embed-panel #deckRail" in ORBIT)
check("E2 the deck opens on the requested panel, not the Control tab's view",
      "this.embedPanel" in ORBIT and "this.applyView(this.embedPanel || saved" in ORBIT)
check("E3 a guest frame never rewrites the Control view/filter",
      "if (!this.embedPanel) try { localStorage.setItem(\"orbit_view_v1\", view); }" in ORBIT
      and "if (this.embedPanel) return;" in ORBIT
      and "noPersist: !!this.embedPanel" in ORBIT
      and "if (persist === false) return;" in FS)
check("E4 the new message bridge exists",
      'd.type === "longrun-show-panel"' in ORBIT
      and 'd.type === "longrun-scope-session"' in ORBIT
      and 'd.type === "longrun-team-action"' in ORBIT
      and 'd.type === "longrun-agent-editor"' in ORBIT)
check("E5 the team/agent actions route into the deck's own editors",
      "app.agents.openTeamEdit(ev, tid)" in ORBIT
      and "app.agents.openAssignPicker(ev, tid)" in ORBIT
      and "app.agents.openAgentEditor(ev, a, kind)" in ORBIT
      and "app.agents.openPrompt(a)" in ORBIT)

# ---- F: session-scoped Jobs ----------------------------------------------------
check("F1 Jobs has the session/all scope control",
      'id="jobScopeTools"' in ORBIT and 'id="jobScope"' in ORBIT
      and 'this.scope === "session"' in ORBIT
      and 'this.scope = v === "all" ? "all" : "session"' in ORBIT)
check("F2 the deck reads the existing in-session SJ ledger",
      '"/api/sessions/" + encodeURIComponent(this.scopeSession) + "/sj"' in ORBIT
      and "In-session jobs" in ORBIT and 'data-sj="' in ORBIT)
check("F3 the session slice uses the agent's jobs and keeps a settled toggle",
      "j.agents || []).includes(this.scopeAgent)" in ORBIT
      and "else if (changed) this.scope = \"session\";" in ORBIT)
check("F4 a job outside the slice widens to ALL before focusing",
      'if (!rec && this.scope === "session")' in ORBIT and "this.scope = \"all\";" in ORBIT)
# 2026-11-18 (operator: "the chat session jobs number is not synced in the job panel"):
# the header counted only RUNNING and TOTAL (a live BLOCKED job was invisible) and left
# the in-session ledger out although its rows are listed right below.
check("F5 the header counts EVERY state the panel shows, plus the in-session ledger",
      '["running", "blocked", "pending"].filter(s => _n(s))' in ORBIT
      and "const _shown = this.jobs.length + _sjJobs.length;" in ORBIT
      and "_parts.join(" in ORBIT)
check("F6 the empty in-session separator names the team jobs below it",
      "no subagent job \u00b7 " in ORBIT and "team job" in ORBIT
      and "This is empty (the in-session ledger)" not in ORBIT)
check("F7 a finished job no longer wears a `blocked by` chip",
      '["pending", "queued", "blocked"].indexOf(j.status) >= 0' in ORBIT)

print("---")
passed = sum(results)
print("v1044: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
