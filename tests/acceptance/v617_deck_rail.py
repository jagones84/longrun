#!/usr/bin/env python3
"""v617 — Control deck is left-bar driven (graphical refactor only).

The top panel-select is gone; a LH rail names every pane and shows it
ALONE in the center-RH area (v622 adds named custom views beside the
singles and drops the stacked board). Same applyView truth underneath:
every panel, button, endpoint and bridge is untouched.

  A  rail markup: ONE nav with all six panes + stacked board, keyboard
     native buttons, labelled;
  B  wiring: buttons call applyView, saved view restores, aria-current
     repaints in applyView (one decider), narrow screens stack the rail
     on top;
  C  no function loss: all six panels, every create/automate/zoom/team/
     job control and every backend path still present.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v617_deck_rail.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


VIEWS = ["agents", "routines", "jobs", "org", "const", "feed"]

# ---------------- A: rail ----------------------
check("A1 ONE labelled nav owns the panes (no second switcher)",
      '<nav id="deckRail" aria-label="Control panels">' in ORBIT
      and 'id="deckView"' not in ORBIT and 'id="deckViewBar"' not in ORBIT)
check("A2 every pane has a rail button, and the stacked board is gone",
      all('data-view="%s"' % v in ORBIT for v in VIEWS)
      and 'data-view="all"' not in ORBIT,
      "%d buttons" % ORBIT.count("data-view="))
check("A3 rail buttons are keyboard-native with a visible current state",
      '<button data-view=' in ORBIT and 'aria-current="page"' in ORBIT
      and "button:focus-visible" in ORBIT)

# ---------------- B: wiring ----------------------
check("B1 buttons call the ONE applyView truth",
      'b.onclick = () => this.applyView(b.dataset.view)' in ORBIT)
check("B2 saved view restores through the rail (unknown lands on first view)",
      'localStorage.getItem("orbit_view_v1")' in ORBIT
      and "this.applyView(saved" in ORBIT)
check("B3 aria-current repaints inside applyView (one decider)",
      'b.setAttribute("aria-current", "page")' in ORBIT
      and "b.removeAttribute(\"aria-current\")" in ORBIT)
check("B4 narrow screens stack the rail on top (same buttons)",
      "@media (max-width:1100px)" in ORBIT
      and ".wrap.deck{flex-direction:column}" in ORBIT)
check("B5 hiding still flows through data-panel (logic untouched)",
      'const key = p.getAttribute("data-panel")' in ORBIT
      and "p.hidden = !show.includes(key)" in ORBIT)

# ---------------- C: no function loss ----------------------
for _p in ["agents", "routines", "jobs", "org", "const", "feed"]:
    check("C panel '%s' still rendered" % _p,
          'data-panel="%s"' % _p in ORBIT)
check("C7 create/automate controls survive",
      all(_id in ORBIT for _id in (
          'id="agNewBtn"', 'id="tmNewBtn"', 'id="jobCreate"', 'id="rtCreate"',
          'id="lraAutoRun"', 'id="orgFit"', 'id="constAll"')))
check("C8 team bulk + job bridges survive",
      "openTeamMenu" in ORBIT and "teamBulk" in ORBIT
      and "focusJob" in ORBIT and "longrun-focus-job" in ORBIT
      and 'data-a="dropold"' in ORBIT)
check("C9 backend paths untouched",
      all(_p in ORBIT for _p in (
          '"/api/jobs/"', '"/api/agents/tree"', '"/api/teams/"',
          '"/api/routines"', '"/api/orbit/sessions"')))
check("C10 select-node-no-camera contract still pinned (v615)",
      "selectNode(sid, scroll)" in ORBIT and "if (scroll === true && hit)" in ORBIT)

print("---")
ok = sum(results)
print("\nv617: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
