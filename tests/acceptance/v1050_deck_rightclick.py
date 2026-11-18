#!/usr/bin/env python3
"""v1050 — right-click on every object of the deck, and menus that keep their promise.

Operator, 2026-11-16:

  *"right click doesn't work..in the org chart bloc go to constellation and the others
    are not all working. the opened menus does not shift the focus to the parts it
    promises. check right click menus on the whole webui on every object they are very
    useful"*

Contract:
  A) every list in the deck answers a right-click with the SAME menu its ⋮ opens
     (agents rows, team headers, jobs, routines), and the org chart / constellation
     nodes carry theirs;
  B) a menu that names a destination reaches it: org ▸ Constellation actually shows
     the constellation, job ▸ open coordinator travels, constellation ▸ select only
     selects;
  C) a hosted panel that changes its own panel tells the host, so the tab strip can
     never name a panel the window no longer shows;
  D) the host answers: it moves its tabs without reloading, and "open in Sessions"
     closes the window so the chat is really visible.

Deterministic: static contract on the two files. No server, model or network.
Run: python3 tests/acceptance/v1050_deck_rightclick.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one gesture per object, always the object's own menu --------------------
check("A1 an agent row's right-click opens the row menu at the pointer",
      'body.querySelectorAll("tr[data-sid]").forEach(tr => {' in ORBIT
      and "this.openAgentMenu(ev, a, (aidEl && aidEl.textContent) || \"\")" in ORBIT)
check("A2 a team header's right-click opens the team menu",
      'body.querySelectorAll("tr.grp-head").forEach(tr => {' in ORBIT
      and "this.openTeamMenu(ev, id)" in ORBIT)
check("A3 a job row's right-click opens ONE job menu (shared with its ⋮)",
      "openJobMenu(ev, jid, canRun){" in ORBIT
      and 'el.oncontextmenu = (ev) => {' in ORBIT
      and "this.openJobMenu(ev, el.dataset.id" in ORBIT
      and "this.openJobMenu(e, b.dataset.jmore" in ORBIT)
check("A4 a routine row's right-click offers its own three controls",
      'class="orgrow" data-rid="' in ORBIT
      and 'this.edit(ev, rid)' in ORBIT and 'this.toggle(rid, !!r.enabled)' in ORBIT
      and 'this.del(rid)' in ORBIT)
check("A5 the org chart node keeps its right-click actions",
      "n.oncontextmenu = (ev) => { ev.preventDefault();" in ORBIT
      and "this.menu(ev, this.bySid[n.dataset.sid])" in ORBIT)
check("A6 the constellation task, job pill and subjob pill all answer a right-click",
      ORBIT.count('addEventListener("contextmenu"') >= 3
      and 'data-cx="task"' in ORBIT and 'data-cx="job"' in ORBIT and 'data-cx="sub"' in ORBIT)

# ---- B: the menu reaches what it names -----------------------------------------
check("B1 org ▸ Constellation SHOWS the constellation in a single-panel frame",
      'if (this.embedPanel) this.applyView("const");' in ORBIT)
check("B2 the org tooltip does not promise a preview the guest cannot show",
      "click = select this agent" in ORBIT
      and 'classList.contains("embed-panel")' in ORBIT)
check("B3 job ▸ open coordinator travels (the same onOpenAgent as the row)",
      'data-jmenu="go"' in ORBIT and "this.onOpenAgent(coord)" in ORBIT)
check("B4 constellation ▸ select selects without travelling",
      "this.tac.onFocus = (a) => { if (a) this.focusAgentSession(a.session); };" in ORBIT
      and "if (this.onFocus) this.onFocus(agent)" in ORBIT)

# ---- C: the hosted deck tells the host which panel it shows --------------------
check("C1 applyView announces a real panel change, and only a real one",
      'type: "longrun-panel-request"' in ORBIT
      and "if (this.embedPanel && _prev && view !== _prev" in ORBIT
      and "/^(agents|jobs|org|const)$/.test(view)" in ORBIT)
check("C2 the host moves its tabs without reloading the frame",
      'd.type === "longrun-panel-request"' in UI
      and "_DP.panel = panel;" in UI
      and "_dpPaint(panel); _dpRailState(panel); _dpScopeLabel();" in UI)

# ---- D: the host's own objects ------------------------------------------------
check("D1 'open in Sessions' from the panel closes the window first",
      "if (f && e.source && e.source === f.contentWindow) _closeDeckPanel(true);" in UI)
check("D2 a runs-panel row's right-click is the session menu",
      "openSessMenu(a, s, ag, e);" in UI)
check("D3 an approval answers a right-click with its own two decisions",
      "if (a.can_approve !== false) items.push({ ic: \"✓\", label: \"Approve\"" in UI
      # af28a09 (2026-11-16): documents joined the Approvals inbox, so the negative
      # decision is spelled by kind — "Reject" for a document, "Deny" for a tool.
      and 'label: a.kind === "document" ? "Reject" : "Deny"' in UI
      and "_openCtx(e.clientX, e.clientY, kind" in UI)

print("---")
print("v1050: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
