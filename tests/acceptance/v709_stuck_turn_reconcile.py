#!/usr/bin/env python3
"""v709 — a dead turn stream must not leave the composer "stuck".

Operator report: the chat looked stuck with the LLM "running" and no approval.
The server had 0 live turns and 0 pending approvals: a service restart had
closed the turn's SSE WITHOUT a terminal frame, and nothing in the tab ever
reconciled `runningSessions` with the server, so Stop mode stayed forever.

  A  reconcileTurn trusts a live stream and ignores an idle session
  B  the server still runs the turn -> re-attach instead of clearing
  C  the server does not run it   -> clear busy, end the stream, say why
  D  an API failure never guesses (busy stays, retry continues)
  E  a lost stream drops its dead handle BEFORE asking the server
  F  wiring: watchdog, visibility/focus hooks, and approvals refreshed at end

Deterministic: the function is extracted from `webui/index.html` and executed
under Node with stubs. No browser, no server, no model.
"""
import json
import os
import shutil
import sys
import glob
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v709-")
results = []
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def run_js(script):
    node = shutil.which("node")
    if node is None:
        installed = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
        node = installed[-1] if installed else "node"
    out = subprocess.run([node], input=script, text=True, capture_output=True, timeout=15)
    if out.returncode != 0:
        return {"error": (out.stderr or "")[:900]}
    try:
        return json.loads((out.stdout or "").strip().splitlines()[-1])
    except ValueError:
        return {"error": (out.stdout or "")[-300:]}


def extract(name, end_marker):
    head = UI.split(name, 1)
    if len(head) < 2:
        return ""
    return name + head[1].split(end_marker, 1)[0] + end_marker


RECONCILE = extract("async function reconcileTurn(sid, force) {", "\n}\n")
SETTLE = extract("function settleLostStream(sid, es) {", "\n}\n")


def harness(body, live, running, api_result, session="S1"):
    """Run one reconcileTurn/settleLostStream scenario under Node."""
    script = """
const turnSSE = LIVE;
const runningSessions = RUNNING;
let calls = { attach: 0, clear: [], endStream: 0, said: [] };
const api = async () => (API);
function attachTurn(sid) { calls.attach++; }
function setRunning(sid, on) { calls.clear.push([sid, on]); if (!on) delete runningSessions[sid]; }
function endStream() { calls.endStream++; }
function who(role, text) { calls.said.push(text); }
const sessionId = "S1";
const fakeEs = { close() { calls.closed = true; } };
FUNCS
(async () => {
  BODY
  await new Promise(r => setTimeout(r, 30));
  console.log(JSON.stringify({calls, turnSSE: Object.keys(turnSSE), running: Object.keys(runningSessions), closed: !!calls.closed}));
})();
""".replace("LIVE", json.dumps(live)).replace("RUNNING", json.dumps(running)) \
   .replace("API", json.dumps(api_result)).replace("FUNCS", RECONCILE + "\n" + SETTLE) \
   .replace("BODY", body)
    return run_js(script)


# ------------------------------------------------------ A: what it ignores --
got = harness("await reconcileTurn('S1');", {"S1": {}}, {"S1": True}, {"active": ["S1"]})
check("A1 a live stream is authoritative (nothing is asked)",
      got.get("calls", {}).get("attach") == 0 and got.get("calls", {}).get("clear") == [],
      got)
got = harness("await reconcileTurn('S1');", {}, {}, {"active": ["S1"]})
check("A2 an idle session is not resurrected", got.get("calls", {}).get("attach") == 0, got)

# ------------------------------------------- B: server still runs the turn --
got = harness("await reconcileTurn('S1');", {}, {"S1": True}, {"active": ["S1"]})
check("B1 it re-attaches instead of clearing", got.get("calls", {}).get("attach") == 1
      and got.get("calls", {}).get("clear") == [], got)

# ------------------------------------------------- C: the turn is really gone --
got = harness("await reconcileTurn('S1');", {}, {"S1": True}, {"active": []})
check("C1 the busy state is cleared", got.get("calls", {}).get("clear") == [["S1", False]], got)
check("C2 the stream is closed and the operator is told",
      got.get("calls", {}).get("endStream") == 1
      and got.get("calls", {}).get("said")
      and "no longer running" in got["calls"]["said"][0], got)

# ------------------------------------------------------- D: offline is no guess --
got = harness("await reconcileTurn('S1');", {}, {"S1": True}, None, )
check("D1 an unreadable server keeps the turn marked busy", got.get("calls", {}).get("clear") == [], got)

# ----------------------------------------- E: a lost stream drops the handle --
got = harness("turnSSE['S1'] = fakeEs; settleLostStream('S1', fakeEs);",
              {"S1": {}}, {"S1": True}, {"active": []})
check("E1 the dead handle is removed before reconciling",
      got.get("turnSSE") == [] and got.get("closed") is True, got)
check("E2 and the server verdict still clears the busy state",
      got.get("calls", {}).get("clear") == [["S1", False]], got)

# --------------------------------------------------------------- F: wiring ---
check("F1 a watchdog re-checks every busy session", "setInterval(reconcileAllTurns" in UI)
check("F2 returning to the tab reconciles (visibility + focus)",
      'addEventListener("visibilitychange"' in UI and 'addEventListener("focus", reconcileAllTurns)' in UI)
check("F3 a bare stream error asks the server instead of clearing blindly",
      "settleLostStream(turnSession, es)" in UI)
check("F4 approvals are refreshed when a turn ends",
      "loadApprovals();" in UI.split("const end = (reload, flush) => {", 1)[1][:1200])
check("F5 a turn that is gone is not silently resumed",
      "no longer running on the server" in UI)

print("\n---\nv709: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
