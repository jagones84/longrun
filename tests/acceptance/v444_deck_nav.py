"""v444 — Plan ↔ constellation navigation (JAG-431r10).

Two directions the operator asked for, pinned deterministically:

  * FORWARD: the RH "Plan" panel gets an explicit "◇ constellation" button (the
    todo right-click menu stays), and opening the Control deck rings the selected
    task AND reveals the deck's docked constellation panel.
  * REVERSE: a double-click on a constellation task hops back to the Sessions
    sheet, opens the Plan panel and reveals the task row — expanding the
    collapsible "older plan" group when the node lives in one. When the deck runs
    EMBEDDED (Control tab iframe) it must ask the PARENT to navigate, never
    navigate the iframe itself.

Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
DECK = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1) forward: an explicit button in the RH Plan panel --------------------
check("1a the Plan panel offers a '◇ constellation' button",
      'data-call="showConstellation"' in HTML and "\u25c7 constellation" in HTML, "")
check("1b showConstellation() exists and opens the deck at the chosen task",
      "function showConstellation()" in HTML and "_showInConstellation(n)" in HTML, "")

# --- 2) forward: opening the deck reveals the constellation PANEL -----------
check("2a _showInConstellation rings the deck's docked constellation panel",
      "function _planRing(" in HTML and 'getElementById("constPanel")' in HTML
      and "_planRing(f, n2)" in HTML, "")
check("2b the forward focus message is still posted into the deck",
      'postMessage({ type: "longrun-focus-node", id: id }' in HTML, "")

# --- 3) reverse: the main app answers the deck's navigation request ---------
check("3a the main WebUI listens for the deck's 'longrun-open-task' request",
      'd.type !== "longrun-open-task"' in HTML
      and 'addEventListener("message"' in HTML, "")
check("3b the request returns to the Sessions sheet and focuses the task",
      "showSessions(); } catch" in HTML and "_focusPlanNode(d.node)" in HTML, "")

# --- 4) reverse: focus ONE task row in the Plan panel ----------------------
check("4a _focusPlanNode opens the Plan inspector (RH panel)",
      "function _focusPlanNode(" in HTML and 'openTab("tasks")' in HTML
      and "#tasks .task[data-id=" in HTML, "")
check("4b it expands an ancestor 'older plan' <details> so old rows are revealed",
      'task.closest("details")' in HTML and "d.open = true" in HTML, "")
check("4c the ?node= deep-link routes through _focusPlanNode",
      "_focusPlanNode(_dn)" in HTML, "")

# --- 5) the deck navigates via the PARENT when embedded --------------------
check("5a the deck posts 'longrun-open-task' to the parent when embedded",
      'window.parent.postMessage({ type: "longrun-open-task"' in DECK
      and "window.self !== window.top" in DECK, "")
check("5b gotoTask routes through _deckGo (no iframe-trapping navigation)",
      "this._deckGo(agent.session, node && node.id)" in DECK
      and "encodeURIComponent(node.id)" not in DECK, "")
check("5c the deck still answers the forward focus message",
      'd.type === "longrun-focus-node"' in DECK and "focusConstellationNode(d.id)" in DECK, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)