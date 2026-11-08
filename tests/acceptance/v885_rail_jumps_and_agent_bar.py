#!/usr/bin/env python3
"""v885 — the rail's section jumps, and the Agents bar stops carrying dead weight.

Operator, 2026-11-08:
  *"you have to remove what it wrote and model policy … they occupy space, it's not
  clear what all of that stuff. what run does? … first understand the backend functions
  of all the objects related to the buttons/webui then reform accordingly to best"*
  *"the right sidebar in sessions add the icons to open and center all the RH panel
  menus please, in correct separations"*

Pinned here:
  A) the chat rail carries a JUMP list of the Inspector sections, built from the REAL
     sections (order included), one icon each, opening AND centering the section;
  B) it is separated from the object cluster and the view cluster by the rail's own
     hairlines (`tb-sec`), and the open section is marked on the icon;
  C) two sections keep their badged object button instead (no duplicate control);
  D) the Agents toolbar no longer shows a "what it wrote" or a "model policy" text
     button: the ledger rides inside the automation bar, the policy is one named icon
     in the panel's action cluster;
  E) the automation bar is one row and says what the send does.

Deterministic: reads webui/index.html + src/longrun/orbit/web/orbit.html, no browser.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the jump list is built from the real sections ----------------------
check("A1 the rail mounts a jump cluster",
      'id="inspJump"' in HTML and 'class="tb-sec" id="inspJump"' in HTML)
check("A2 it is built from the REAL inspector sections, in their order",
      "function _buildInspJump()" in HTML
      and "_inspSections().forEach(sec => {" in HTML
      and 'document.querySelectorAll("#inspector section[data-insp]")' in HTML)
check("A3 every jump is a named 30px icon that opens AND centers",
      'b.title = "open and center the " + label + " panel";' in HTML
      and 'b.setAttribute("aria-label", "open and center the " + label + " panel")' in HTML
      and "b.onclick = () => { _railOpenInsp(key); _paintInspJump(); };" in HTML)
check("A4 centering is real (the panel is the scroller, block: center)",
      'sec.scrollIntoView({ block: "center" });   // v885' in HTML
      and 'block: "nearest"' not in HTML.split("function _railOpenInsp")[1].split("}")[0])
check("A5 the label is READ from the section header, not copied into a second table",
      "function _inspLabel(sec)" in HTML and "hd.firstChild" in HTML)
check("A6 the list follows a drag-reorder instead of keeping a stale order",
      "_applyInspOrder();\n        _buildInspJump();   // v885" in HTML)
check("A7 the open section is marked from the real class, and lit in CSS",
      '_paintInspJump();   // v885' in HTML
      and 'const on = !!(sec && sec.classList.contains("insp-open"));' in HTML
      and "#toolsBar #inspJump button.is-current { color: var(--acc); }" in HTML)

# ---- B: correct separations, no duplicate control --------------------------
check("B1 one group per job: objects | jumps | view controls",
      HTML.count('<div class="tb-sec"') >= 3
      and HTML.index('id="inspJump"') > HTML.index('id="kbSessionBtn"')
      and HTML.index('id="inspJump"') < HTML.index('id="chatReloadBtn"'))
check("B2 the sections that already own a badged object button are not repeated",
      'const INSP_JUMP_SKIP = ["approvals", "files"];' in HTML
      and 'if (!key || INSP_JUMP_SKIP.indexOf(key) >= 0) return;' in HTML)

# ---- C: the Agents toolbar loses the two text buttons ----------------------
check("C1 'what it wrote' is gone from the toolbar",
      'id="lraRepBtn"' not in ORBIT)
check("C2 the ledger is still reachable: the ✨ loads it with the bar",
      'id="lraRep"' in ORBIT and "this.loadReport(true);   // v885" in ORBIT)
check("C3 an empty ledger costs no row",
      'if (!runs.length) box.style.display = "none";   // v885' in ORBIT
      and "no automation recorded yet" not in ORBIT)
check("C4 'model policy' is no longer a text button",
      ">⚙ model policy</button>" not in ORBIT)
check("C5 it is one named icon in the panel's own action cluster",
      'id="agPolicy"' in ORBIT
      and ORBIT.index('id="agPolicy"') < ORBIT.index('id="rzReset"')
      and 'aria-label="apply the team model policy to the agents in scope">⚙</button>' in ORBIT)
check("C6 the policy itself is still the server's (no second rule in the browser)",
      '"/api/teams/" + encodeURIComponent(tid) + "/models"' in ORBIT
      and 'this.api.post("/api/agents"' not in ORBIT.split("async applyModelPolicy(){")[1].split("/* v622:")[0])

# ---- D: the bar is one row and says what "send" does -----------------------
bar = ORBIT[ORBIT.index('id="lraAutoBar"'):ORBIT.index('id="agAddBar"')]
check("D1 the bar is a single row: no block children of its own",
      bar.count("flex-basis:100%") == 1)   # only the ledger container
check("D2 the send button explains the effect and the cost",
      'id="lraAutoRun" title="send this instruction to longrunAgent:' in ORBIT
      and "its own session is wiped" in ORBIT)
check("D3 cancel is one named icon, not a word",
      'id="lraAutoCancel" type="button" title="close this bar' in ORBIT
      and 'aria-label="close the automation bar">✕</button>' in ORBIT)
check("D4 the actor is still named (the ✨ has no text of its own)",
      ">automate with longrunAgent</span>" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
