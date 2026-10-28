#!/usr/bin/env python3
"""v703: the RH "constellation" shows the ACTIVE chat session, not the team board.

Defect (operator report): the Plan panel's constellation landed on the deck's
agent-registry view (agents[0] / the ALL board) because the bridge sent only a task
id — and node ids are per-session (n1..nN). The fix carries the session id, filters
the DOM node by data-sid, and lets the deck pin a session that is not a designated
org agent by reading its own graph endpoint.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
          encoding="utf-8") as f:
    DECK = f.read()

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(("PASS " if condition else "FAIL ") + label + ((" :: " + str(detail)) if detail else ""))


# --- parent: the bridge carries the active session -------------------------
check("A1 _showInConstellation resolves the active session id",
      "const sid = (typeof sessionId === \"string\" && sessionId) ||" in HTML
      and "(graph && (graph.session_id || graph.session))" in HTML)
check("A2 the focus message carries it",
      'postMessage({ type: "longrun-focus-node", id: id, session: sid }' in HTML)
check("A3 the message is sent even when no task node is known",
      "id: id, session: sid" in HTML and "if (id) f.contentWindow.postMessage" not in HTML)

# --- deck: the listener forwards the session -------------------------------
check("B1 the deck listener forwards the session",
      "focusConstellationNode(d.id, 0, d.session)" in DECK)

# --- deck: the node is matched INSIDE that session ------------------------
check("B2 the node lookup is scoped by data-sid",
      "'.cnode[data-id=\"' + cssEsc + '\"][data-sid=\"' + sidEsc + '\"]'" in DECK)
check("B3 the label fallback filters on the same session",
      'if (sidEsc && el.getAttribute("data-sid") !== String(sid)) return false;' in DECK)
check("B4 no ALL-board fallback when the session is known",
      "if (tries === 0 && !sid){ const b = document.getElementById(\"constAll\")" in DECK)

# --- deck: a plain chat session can be shown at all -----------------------
check("C1 the deck pins the session across its 5 s refresh",
      "this._pinnedSid = String(sid || \"\")" in DECK
      and "if (this._pinnedSid) await this._pinGraph(this._pinnedSid);" in DECK)
check("C2 it reads that session's own graph from the existing route",
      '"/api/sessions/" + encodeURIComponent(sid) + "/graph"' in DECK)
check("C3 a non-registry session gets an explicit agent row",
      "{id: \"S.\" + sid.slice(0, 6), session: sid, adhoc: true," in DECK
      and "this.data.agents = [a].concat(this.data.agents);" in DECK)
check("C4 focusing the session happens before the ring",
      "window.__orbitApp.tac.ensureSession(sid).then(a => {" in DECK)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
