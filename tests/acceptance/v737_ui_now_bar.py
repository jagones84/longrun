#!/usr/bin/env python3
"""v737 — the sticky "now" bar above the composer only claims work that RUNS.

Live 2026-10-30: the operator saw `A1.n39 (doing) Export/preview …` pinned above
the composer while the graph said that step was `done` and no turn was running
(the session had been interrupted by a service restart). A "doing" step means a
turn is working it; with no turn running it is a leftover, and the bar must not
show it. A `blocked` step is a real state without a running turn, so it stays.

The function is EXECUTED (Node) with stubs, not grepped.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    UI = _f.read()

START = "function _updateNowBar() {"
END = "/* JAG-427: chat todo-group expand / collapse ALL"
FUNC = UI.split(START, 1)[1].split(END, 1)[0]
FUNC = START + FUNC

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def run_js(script):
    node = shutil.which("node")
    if node is None:
        installed = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
        node = installed[-1] if installed else "node"
    result = subprocess.run([node], input=script, text=True, capture_output=True, timeout=10)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


HARNESS = """
let sessionId = "s1";
const runningSessions = RUNNING;
const graph = {nodes: NODES};
let _activeNodeId = ACTIVE;
let _nowLast = "";
const _bar = {hidden: true, dataset: {}, innerHTML: "", onclick: null};
const $ = id => (id === "nowbar" ? _bar : null);
function _updateTreeTools() {}
function planNodes(g) { return (g && g.nodes) || []; }
function _nodeById(id) { return graph.nodes.find(n => String(n.id) === String(id)) || null; }
function _todoid(n) { return "A1." + String(n.id); }
function esc(s) { return String(s == null ? "" : s); }
function _scrollToNode() {}
FUNC
_updateNowBar();
console.log(JSON.stringify({hidden: _bar.hidden, id: _bar.dataset.id || "",
                            html: _bar.innerHTML}));
"""

DOING = [{"id": "n39", "status": "doing", "label": "Export/preview"}]
DONE = [{"id": "n39", "status": "done", "label": "Export/preview"}]
BLOCKED = [{"id": "n40", "status": "blocked", "label": "needs a decision"}]


def state(running, nodes, active=""):
    script = (HARNESS.replace("RUNNING", json.dumps(running))
                      .replace("NODES", json.dumps(nodes))
                      .replace("ACTIVE", json.dumps(active))
                      .replace("FUNC", FUNC))
    return run_js(script)


got = state({}, DOING)
check("A1 a 'doing' step with NO turn running is not shown", got["hidden"] is True, got)

got = state({"s1": True}, DOING)
check("A2 a 'doing' step WHILE the turn runs is shown",
      got["hidden"] is False and got["id"] == "n39" and "Export/preview" in got["html"], got)

got = state({}, DONE)
check("A3 a finished plan leaves no bar behind", got["hidden"] is True, got)

got = state({}, BLOCKED)
check("A4 a BLOCKED step survives with no turn running (it is real)",
      got["hidden"] is False and got["id"] == "n40", got)

got = state({}, DOING, active="n39")
check("A5 a stale ACTIVE id does not resurrect a doing step", got["hidden"] is True, got)

got = state({"s1": True}, DONE, active="")
check("A6 with a turn running, a plan of done steps shows nothing", got["hidden"] is True, got)

print("\n---")
print("v737: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
