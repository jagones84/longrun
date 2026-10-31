#!/usr/bin/env python3
"""v757 — the chat must keep painting without a manual ↻ (live-channel liveness).

Operator report: "spesso la chat rimane intrappolata senza mostrare i progressi …
se faccio aggiorna si sblocca, ma per qualche secondo prima non si vede la chat".

Two defects behind it:

  A  a turn stream whose peer vanished silently (no FIN -> no `error`) was taken as
     authoritative forever: the turn ran with nothing painted, and only a rebuild
     showed the result;
  B  the rebuild itself emptied #log BEFORE its history/graph round-trips, so the
     chat was blank for seconds.

  A  the server publishes a NAMED heartbeat (an SSE comment is invisible to JS)
  B  reconcileTurn drops a CLOSED / silent handle, then asks the server
  C  the feed has the same watchdog (it is the page's only "a turn ended" source)
  D  the rebuild clears the log only right before the first paint
  E  the streamed answer render is throttled, and the tail is flushed at turn end

Deterministic: static contracts + `reconcileTurn` executed under Node with stubs.
No browser, no server, no model.
"""
import json
import os
import shutil
import glob
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
SSE = open(os.path.join(REPO, "src", "longrun", "core", "sse.py"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()


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

# ---- A: the server side ------------------------------------------------------
check("A1 sse.py exposes a NAMED heartbeat frame (a comment is invisible to JS)",
      "def heartbeat_frame(" in SSE and "event: heartbeat" in SSE)
check("A2 sse_pump can emit it while the producer is silent",
      "idle_timeout=None, heartbeat=False" in SSE
      and "if heartbeat:" in SSE.split("def sse_pump", 1)[1].split("def sse_tail", 1)[0])
check("A3 sse_tail can emit it on the always-on feed",
      "idle_limit=600,\n             heartbeat=False" in SSE
      and "heartbeat and idle % 5 == 0" in SSE)
check("A4 the chat stream, the re-attach stream and the feed all ask for it",
      "sse_pump(q, t, idle_timeout=CHAT_STREAM_IDLE or None, heartbeat=True)" in API
      and "heartbeat=True)" in API.split("def feed_gen", 1)[1][:400]
      and API.split("def chat_attach_gen", 1)[1].split("yield heartbeat_frame()", 1)[0].count(": ping") == 1)
check("A6 turn frames carry their durable id, so a recovery can resume from it",
      API.count('"id: %d\\n" % eid if eid else ""') == 2
      and 'ev = publish(kind, **d)' in API
      and 'ev = publish("chat.delta", session=sess["id"], channel=channel, text=text)' in API)

# ---- A2/E: the client side ---------------------------------------------------
check("A5 _bindRenderStream stamps every heartbeat on the handle",
      'es.addEventListener("heartbeat", () => { es._lrSeen = Date.now(); })' in UI
      and "es._lrSeen = Date.now();" in UI)
check("A7 a recovered stream resumes from the last frame id (no duplicated text)",
      "if (e.lastEventId) es._lrId = e.lastEventId;" in UI
      and "function attachTurn(sid, since) {" in UI
      and '(since ? "&since=" + encodeURIComponent(since) : "")' in UI)


def harness(body, live, running, api_result):
    script = """
const fakeEs = { close() { calls.closed = true; }, _lrSeen: SEEN, readyState: RS };
const turnSSE = LIVE;
const runningSessions = RUNNING;
let calls = { attach: 0, clear: [], endStream: 0, said: [] };
const api = async () => (API);
function attachTurn(sid, since) { calls.attach++; calls.since = since || ""; }
function setRunning(sid, on) { calls.clear.push([sid, on]); if (!on) delete runningSessions[sid]; }
function endStream() { calls.endStream++; }
function who(role, text) { calls.said.push(text); }
const sessionId = "S1";
FUNCS
(async () => {
  BODY
  await new Promise(r => setTimeout(r, 30));
  console.log(JSON.stringify({calls, turnSSE: Object.keys(turnSSE), running: Object.keys(runningSessions), closed: !!calls.closed}));
})();
""".replace("LIVE", json.dumps(live)).replace("RUNNING", json.dumps(running)) \
   .replace("API", json.dumps(api_result)) \
   .replace("SEEN", "Date.now()").replace("RS", "1") \
   .replace("FUNCS", RECONCILE).replace("BODY", body) \
   .replace('"__HANDLE__"', "fakeEs") \
   .replace('"__CLOSED__"', "{ close() { calls.closed = true; }, _lrSeen: Date.now(), readyState: 2 }")
    return run_js(script)


# a FRESH handle is still authoritative (no server call)
got = harness("await reconcileTurn('S1');", {"S1": "__HANDLE__"}, {"S1": True}, {"active": ["S1"]})
check("B1 a fresh handle is authoritative", got.get("calls", {}).get("attach") == 0
      and got.get("calls", {}).get("clear") == [], got)
# a handle with NO age information is not second-guessed (v709 A1 stays true)
got = harness("await reconcileTurn('S1');", {"S1": {}}, {"S1": True}, {"active": ["S1"]})
check("B2 a handle without an age is not second-guessed", got.get("calls", {}).get("attach") == 0, got)
# a CLOSED handle is dropped and the server verdict re-attaches
got = harness("await reconcileTurn('S1');", {"S1": "__CLOSED__"}, {"S1": True}, {"active": ["S1"]})
check("B3 a CLOSED handle is dropped and re-attached", got.get("calls", {}).get("closed") is True
      and got.get("calls", {}).get("attach") == 1, got)
# a SILENT handle (no heartbeat for > 20 s) is dropped and re-attached
got = harness("turnSSE['S1']._lrSeen = Date.now() - 60000; await reconcileTurn('S1');",
              {"S1": "__HANDLE__"}, {"S1": True}, {"active": ["S1"]})
check("B4 a silent handle is dropped and re-attached", got.get("calls", {}).get("closed") is True
      and got.get("calls", {}).get("attach") == 1, got)
# ... and when the server says the turn is gone, the busy state is cleared instead
got = harness("turnSSE['S1']._lrSeen = Date.now() - 60000; await reconcileTurn('S1');",
              {"S1": "__HANDLE__"}, {"S1": True}, {"active": []})
check("B5 a silent handle whose turn is gone clears the busy state",
      got.get("calls", {}).get("clear") == [["S1", False]]
      and "no longer running" in (got.get("calls", {}).get("said") or [""])[0], got)
# the recovery resumes from the last rendered frame, never from the turn's start
got = harness("turnSSE['S1']._lrSeen = Date.now() - 60000; turnSSE['S1']._lrId = '4242';"
              " await reconcileTurn('S1');",
              {"S1": "__HANDLE__"}, {"S1": True}, {"active": ["S1"]})
check("B6 the re-attach carries the last frame id", got.get("calls", {}).get("since") == "4242", got)

# ---- C: the feed watchdog ----------------------------------------------------
check("C1 the feed reconnects when its heartbeat stops",
      "_feedWatch" in UI and "Date.now() - (es._lrSeen || 0) < 20000" in UI
      and "connectFeed();" in UI.split("_feedWatch = setInterval", 1)[1][:400])
check("C2 a feed error and a feed watchdog never stack timers",
      UI.count("clearInterval(_feedWatch)") >= 2)

# ---- D: the rebuild does not blank the chat ---------------------------------
_paint_at = UI.find('_paintHistoryStart();   // 2026-11-01')
_graph_at = UI.find('GET", "/api/sessions/" + encodeURIComponent(_historySid) + "/graph"')
_first_paint = UI.find("evs.forEach(e => {", _paint_at if _paint_at > 0 else 0)
check("D1 the log is cleared AFTER the history + graph fetches, right before the paint",
      _paint_at > 0 and _paint_at > _graph_at and 0 < _first_paint - _paint_at < 900, (_paint_at, _graph_at))
check("D2 loadHistory no longer clears the log up front",
      '$("log").innerHTML = ""; curThink = curAns = null; _resetChatTree();\n  _historyReplaySession' not in UI)
check("D3 a turn this tab streamed is not rebuilt at its own end",
      "if (_streamedDone[d.session] || turnSSE[d.session]) { loadPlan(); loadCtx(); }" in UI)

# ---- E: bounded answer render ----------------------------------------------
check("E1 the streaming render is throttled by a timer, not only by rAF",
      "_MD_MIN_MS" in UI and "setTimeout(() => _mdRender(b), wait)" in UI
      and "_mdRaf = requestAnimationFrame(() => _mdRender(b));" in UI)
check("E2 the pending tail is flushed when the turn ends",
      "function endStream()" in UI
      and "renderAnswerBubble(_b);" in UI.split("function endStream()", 1)[1][:700])

print("\n---\nv757: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
