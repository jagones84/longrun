#!/usr/bin/env python3
"""v715 — a mined draft can be MOVED from the panel, and the panel tells the truth.

v710 made the drafts visible; nothing could act on them, so the operator had to
ask the agent to run two tool calls by hand. Each draft row now has `verify` and
`promote`; both call the real tool endpoint, and every line printed is the
tool's own answer (a gated promote says "approval raised", never "installed").

  A  the real `draftAct` (extracted from index.html, run under Node) renders
     green, red, installed, raised, refused and error without inventing a result
  B  the panel really wires the two actions to that function
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def run_js(script):
    node = shutil.which("node")
    if node is None:
        import glob
        cand = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
        node = cand[-1] if cand else "node"
    out = subprocess.run([node], input=script, text=True, capture_output=True, timeout=20,
                         env=dict(os.environ, PATH=os.environ.get("PATH", "") + ":/usr/local/bin"))
    if out.returncode != 0:
        return {"error": (out.stderr or "")[:600]}
    return json.loads((out.stdout or "").strip().splitlines()[-1])


def act(answer, action="verify", path="/d"):
    fn = "async function draftAct(path, action, slot) {" + UI.split(
        "async function draftAct(path, action, slot) {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = """
const slot = { textContent: "" };
const api = async () => (ANSWER);
FUNCTION
draftAct(PATH, ACTION, slot).then(() => console.log(JSON.stringify({text: slot.textContent})));
""".replace("ANSWER", "(" + json.dumps(answer) + ")").replace("FUNCTION", fn) \
        .replace("PATH", json.dumps(path)).replace("ACTION", json.dumps(action))
    return run_js(script)


# ------------------------------------- A: every answer is the tool's own ----
got = act({"status": "executed", "result": {"ok": True, "synth": True,
                                            "verify": {"green": True, "output": "ok: 3 valid step(s)"}}})
check("A1 a green verify is shown with its own output",
      got.get("text", "").startswith("✅ green") and "3 valid step" in got.get("text", ""), got)
got = act({"status": "executed", "result": {"ok": True,
                                            "verify": {"green": False, "output": "unknown tools: x"}}})
check("A2 a red verify shows the reason, not a success",
      got.get("text", "").startswith("❌") and "unknown tools" in got.get("text", ""), got)
got = act({"status": "executed", "result": {"ok": True, "installed_to": "/s/skills/created/x"}}, "promote")
check("A3 an install is reported with the real path",
      got.get("text", "").startswith("installed") and "/s/skills/created/x" in got.get("text", ""), got)
got = act({"status": "pending", "approval": {"id": "abc"}, "result": {}}, "promote")
check("A4 a gated promote says an approval was raised, never 'installed'",
      "approval raised" in got.get("text", "") and "installed" not in got.get("text", ""), got)
got = act({"status": "executed", "result": {"ok": False, "error": "skill not verified"}}, "promote")
check("A5 a refused promote shows the refusal",
      got.get("text", "").startswith("refused") and "not verified" in got.get("text", ""), got)
got = act(None, "verify", "")
check("A6 a draft without a folder says so", "no folder" in got.get("text", ""), got)


def act_err():
    fn = "async function draftAct(path, action, slot) {" + UI.split(
        "async function draftAct(path, action, slot) {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = """
const slot = { textContent: "" };
const api = async () => { throw new Error("boom"); };
FUNCTION
draftAct("/d", "verify", slot).then(() => console.log(JSON.stringify({text: slot.textContent})));
""".replace("FUNCTION", fn)
    return run_js(script)


got = act_err()
check("A7 a transport error is reported as an error", "error:" in got.get("text", ""), got)

# ------------------------------------- B: the panel wires both actions ------
check("B1 the drafts row offers verify and promote",
      'mk("verify"' in UI and 'mk("promote"' in UI, "")
check("B2 both call the same real endpoint", 'draftAct(x.path, action, slot)' in UI
      and '"/api/tools/call"' in UI.split("async function draftAct(")[1][:800], "")
check("B3 promote is described as approval-gated",
      "approval-gated" in UI, "")
check("B4 the row says a draft is material, not installed",
      "Nothing here is installed" in UI, "")

print("\n---\nv715: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
