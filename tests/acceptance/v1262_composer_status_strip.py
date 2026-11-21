#!/usr/bin/env python3
"""v1262 — the composer status strip (TRAE reference): five icons, one label, one panel.

Operator (2026-11-22, round 180): *"vedi la barra sopra msg box di trae come è strutturata?
le icone … tasks process, file review, messages (queued), background command processes, goal,
cliccando su ognuna mostra sopra la barra ciò che va mostrato … mi piace molto molto
compatto"*. Decisions: ONE strip (the goal bar and the queue chips stop being rows), and
"background" means the SHELL background commands (bgjobs), not the tool jobs/agent runs
(those stay in RH ▸ Feed).

  A  the strip carries the five icon toggles + the status label, in the message box's top row
  B  the goal bar and the queue chips are BORROWED into the panel (no row, no lost action)
  C  one label, with the declared priority and the goal icon disabled without a goal
  D  the background panel reads GET /api/bgjobs; the backend lists the shell jobs
  E  the existing surfaces are not duplicated
  F  the goal popovers clear the strip's panel (A54 R180-1)

Deterministic and offline. Run: python3 tests/acceptance/v1262_composer_status_strip.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
API = src("src", "longrun", "core", "api_v02.py")
BG = src("src", "longrun", "tools", "bgjobs.py")
STRIP = UI[UI.index('<div id="cmpSuper">'):UI.index('<div id="inpWrap">')]
CS = UI[UI.index("var _cs = { key: null"):UI.index("function _setAllInspector(")]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


# ---- A: the strip ---------------------------------------------------------
KEYS = ("plan", "files", "queue", "bg", "goal")
check("A1 five icon toggles, each with a name and a tooltip",
      all(('data-cs="%s"' % k) in STRIP for k in KEYS)
      and STRIP.count('class="cs-tab"') == 5
      and STRIP.count("aria-label=") >= 5 and STRIP.count("title=") >= 5)
check("A2 the status label sits after the icons, polite, and collapses when empty",
      '<span id="csLabel" class="cs-label" aria-live="polite"></span>' in STRIP
      and ".cs-label:empty { display: none; }" in UI
      and STRIP.index('data-cs="goal"') < STRIP.index('id="csLabel"'))
check("A3 the strip is still the message box's top row with the spark and the close",
      UI.index('id="cmpSuper"') < UI.index('id="inpWrap"')
      and '<span id="cmpSpark"></span>' in STRIP and 'id="csClose"' in STRIP
      and ".cs-body { position: absolute;" in UI)

# ---- B: the goal bar and the queue are borrowed, not rows ------------------
check("B1 the goal bar no longer paints itself into the flow",
      'bar.hidden = !_csIsOpen("goal");' in UI
      and "bar.hidden = false;" not in between(UI, "function renderGoal() {", "function renderGoalVerdict()"))
RQ = between(UI, "function renderQueue() {", "function editQueued(i)")
check("B2 the queue chips are the panel, never a row",
      'if (!q.length && _csIsOpen("queue")) _csReturn();' in RQ
      and 'bar.hidden = !(q.length && _csIsOpen("queue"));' in RQ)
check("B3 _csOpen borrows #queueBar and #goalBar with the same return contract",
      'const _CS_NODES = { queue: "queueBar", goal: "goalBar" };' in UI
      and 'node = $(_CS_NODES[key]);' in UI
      and "_cs.parent.insertBefore(_cs.node, _cs.next || null);" in UI)
check("B4 every action stays reachable: goal menu, verdict, queue edit/steer/remove",
      all(s in UI for s in ('id="goalMore"', 'id="goalVerdictBadge"', 'id="goalEdit"',
                            'id="goalDel"', "function editQueued(i)", "function steerQueued(i)")))
check("B5 an empty queue in the panel says so",
      'if (key === "queue" && !_q().length)' in UI and "no messages waiting" in UI)

# ---- C: one label, one priority, the goal icon follows the goal -----------
LBL = between(UI, "function _csLabel() {", "function _csReturn()")
check("C1 the closed strip NAMES every live state: queue, then background, then goal/tasks",
      'if (q) parts.push(q + " waiting to send");' in LBL
      and 'if (bg !== "nothing running") parts.push(bg);' in LBL
      and LBL.index('if (q) parts.push') < LBL.index('if (bg !== "nothing running") parts.push')
      < LBL.index("_goalStatusText() || _taskStatusText(true)"))
check("C2 the open panel labels itself (tasks/files/queue/bg/goal)",
      all(s in LBL for s in ('_taskStatusText(false)', "_filesStatusText()", "_bgStatusText()",
                             '_goalStatusText() || "no goal"')))
check("C3 the goal icon is disabled while there is no goal",
      'b.disabled = !ok;' in UI and 'title = ok ? "goal — objective, progress and actions" : "no active goal";' in UI)
check("C4 the label is fed by the real surfaces, not a second count",
      "_setRailBadge(\"editsBtn\", files.length);\n  _csLabel();" in UI
      and '$("taskCount").textContent = (c.done || 0) + "/" + _nodes.length;\n  _csLabel();' in UI
      and '_csPaint();   // ROUND 180/181: the strip follows the queue (label + the count badge)' in UI)

# ---- D: background shell commands -----------------------------------------
check("D1 GET /api/bgjobs and POST stop are registered on the shell-job owner",
      'if path == "/api/bgjobs":' in API and "_bgj.listing(qs.get(\"session\")" in API
      and "_bgj.stop(body.get(\"job\"))" in API)
from longrun.tools import bgjobs  # noqa: E402


class _P:
    def __init__(self, code=None):
        self.pid = 4242
        self._code = code

    def poll(self):
        return self._code


log = os.path.join(tempfile.mkdtemp(prefix="lr-v1262-"), "bg.log")
with open(log, "w", encoding="utf-8") as f:
    f.write("hello tail\n")
saved = dict(bgjobs._JOBS)
now = time.time()
try:
    bgjobs._JOBS.clear()
    bgjobs._JOBS["bg-1"] = {"job": "bg-1", "proc": _P(None), "cmd": "sleep 60", "cwd": "/tmp",
                            "label": "", "log": log, "session": "S1", "started": now - 10,
                            "ended": None, "exit_code": None, "announced": False}
    bgjobs._JOBS["bg-2"] = {"job": "bg-2", "proc": _P(0), "cmd": "make", "cwd": "/tmp",
                            "label": "", "log": "", "session": "S2", "started": now - 20,
                            "ended": now - 5, "exit_code": 0, "announced": True}
    one = bgjobs.listing("S1", 100)
    both = bgjobs.listing(None, 100)
finally:
    bgjobs._JOBS.clear()
    bgjobs._JOBS.update(saved)
check("D2 listing filters by session and puts the running job first",
      [j["job"] for j in one["jobs"]] == ["bg-1"] and one["jobs"][0]["running"] is True
      and [j["job"] for j in both["jobs"]] == ["bg-1", "bg-2"], [j["job"] for j in both["jobs"]])
check("D3 the row carries the command, the exit state and the log tail",
      one["jobs"][0]["command"] == "sleep 60" and "hello tail" in one["jobs"][0]["tail"]
      and both["jobs"][1]["exit_code"] == 0 and both["jobs"][1]["running"] is False)
PANEL = between(UI, "function _renderBgPanel() {", "function _setAllInspector(")
check("D4 the panel stops a job, opens its tail and links the full Feed",
      'data-bgstop="' in PANEL and "api(\"POST\", \"/api/bgjobs\", { job: b.dataset.bgstop })" in PANEL
      and 'data-bgtail="' in PANEL and 'focusInsp("feed")' in PANEL)
check("D5 the count is refreshed on boot, on a session switch and after a turn",
      UI.count("_loadBgJobs();") >= 3 and "_bgPollStart();" in UI
      and "document.visibilityState === \"visible\"" in UI)

# ---- E: no duplicate surface ----------------------------------------------
check("E1 the RH Feed still owns tool jobs and agent runs (one implementation)",
      'id="runningNowList"' in UI and "async function loadRunning()" in UI
      and UI.count("function loadRunning(") == 1
      and "/api/tools/running" in UI and "/api/agent/runs" in UI)
check("E2 the doc bar is untouched and still above the strip",
      'id="docBar"' in UI and UI.index('id="docBar"') < UI.index('id="cmpSuper"'))

# ---- F: the goal popovers clear the strip's panel (A54 R180-1) ------------
# The bar only exists inside #csBody (a z-70 layer above the composer). Anchored with
# bottom:100% of the composer, the popover's last row landed UNDER that layer and could
# not be pressed. Both popovers are fixed and placed from the panel's rect instead.
check("F1 both goal popovers are fixed above the panel layer",
      ".gb-menu { position: fixed;" in UI and ".gb-editor { position: fixed;" in UI
      and "z-index: 90; }" in between(UI, ".gb-menu { position: fixed;", ".gb-menu[hidden]")
      and "z-index: 90; }" in between(UI, ".gb-editor { position: fixed;", ".gb-editor[hidden]"))
HELP = between(UI, "function _gbPlaceDropup(", "function goalMenuToggle()")
check("F2 the placement reads the panel rect and opens ABOVE it",
      "const r = body.getBoundingClientRect();" in HELP
      and "let top = r.top - 6 - h;" in HELP
      and "if (top < 8) top = Math.min(r.bottom + 6, vh - h - 8);" in HELP)
check("F3 both openers place the popover, and closing the panel closes them",
      "if (!m.hidden) _gbPlaceDropup(m, false);" in UI
      and "_growGoalEdit();\n  _gbPlaceDropup(panel, true);" in UI
      and 'if (key === "goal") { goalMenuClose(); goalEditCancel(); }' in UI)

print("\n---\nv1262: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
