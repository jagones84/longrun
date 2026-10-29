#!/usr/bin/env python3
"""v710 — self-evolve output must be VISIBLE and its refusals must not lie.

Found by driving the real WebUI:

  A  the Improve panel counted 0 pending proposals while
     `<DATA>/proposals/skills/` held 20 machine-mined DRAFTS — self-evolve
     produced 20 artifacts the operator could not see anywhere;
  B  a dry run on a session that does not exist kept showing the PREVIOUS
     report, so a refusal looked like a fresh success.

  A  list_drafts reads the real draft folders (status, support, age), is bounded,
     and reports unreadable folders instead of hiding them
  B  the API and the panel expose that view (and state it is not installed)
  C  runHarnessDryRun surfaces a refusal and never re-renders a stale report

Deterministic: fixture folders + the real UI function under Node.
"""
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v710-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402

results = []
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def write_draft(root, name, created, status="proposed", support=3, green=None, corrupt=False):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    if corrupt:
        with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        return d
    rec = {"kind": "skill", "status": status, "name": name, "support": support,
           "created": created, "origin": "auto", "pattern": ["fs.read", "fs.edit"]}
    if green is not None:
        rec["verify"] = {"green": green}
        rec["green_streak"] = 1 if green else 0
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return d


DRAFTS = os.path.join(TMP, "data", "proposals", "skills")
now = time.time()
write_draft(DRAFTS, "older", now - 500)
write_draft(DRAFTS, "newer", now, status="verified", support=7, green=True)
write_draft(DRAFTS, "broken", now, corrupt=True)
improve.DRAFT_DIR = DRAFTS

# ------------------------------------------------------- A: the real drafts --
info = improve.list_drafts()
names = [d["name"] for d in info["drafts"]]
check("A1 every readable draft is listed", sorted(names) == ["newer", "older"], info)
check("A2 newest first", names == ["newer", "older"], names)
check("A3 status and support come from the draft itself",
      info["drafts"][0]["status"] == "verified" and info["drafts"][0]["support"] == 7
      and info["drafts"][1]["status"] == "proposed", info["drafts"])
check("A4 a verified draft shows its green proof",
      info["drafts"][0]["verified"] is True, info["drafts"][0])
check("A5 an unreadable folder is counted, not hidden", info["unreadable"] == 1, info)
check("A6 the total is the real count", info["total"] == 2, info)
check("A7 a limit bounds the list but not the total",
      len(improve.list_drafts(limit=1)["drafts"]) == 1
      and improve.list_drafts(limit=1)["total"] == 2)
improve.DRAFT_DIR = os.path.join(TMP, "nope")
empty = improve.list_drafts()
check("A8 a missing directory is empty, not an error",
      empty["drafts"] == [] and empty["total"] == 0 and empty["unreadable"] == 0, empty)
improve.DRAFT_DIR = DRAFTS

# ------------------------------------------------------- B: API + panel ------
api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("B1 the improvement API serves the drafts", '"drafts": ' in api
      and '"drafts_total"' in api, "")
check("B2 the panel has its own section", 'id="impDraftsBox"' in UI and 'id="impDrafts"' in UI)
check("B3 it says plainly that nothing there is installed",
      "Nothing here is installed" in UI)
check("B4 the render reads the API field", "d.drafts" in UI)
check("B5 an unreadable draft folder is surfaced, not swallowed",
      "drafts_unreadable" in UI or "drafts_unreadable" in api)

# ------------------------------------------- C: a refusal is never a success --
def run_js(script):
    import glob
    node = shutil.which("node")
    if node is None:
        cand = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
        node = cand[-1] if cand else "node"
    out = __import__("subprocess").run([node], input=script, text=True,
                                       capture_output=True, timeout=15,
                                       env=dict(os.environ, PATH=os.environ.get(
                                           "PATH", "") + ":/usr/local/bin:/usr/bin"))
    if out.returncode != 0:
        return {"error": (out.stderr or "")[:700]}
    return json.loads((out.stdout or "").strip().splitlines()[-1])


def dry_run(answer):
    fn = "async function runHarnessDryRun() {" + UI.split(
        "async function runHarnessDryRun() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = """
let nodes = { hcSession: { value: "sess-x" }, hcLast: { textContent: "" } };
const $ = id => nodes[id];
let reloaded = 0;
function loadHarnessCycle() { reloaded++; }
const api = async () => (ANSWER);
FUNCTION
runHarnessDryRun().then(() => console.log(JSON.stringify(
  {reloaded, last: nodes.hcLast.textContent})));
""".replace("ANSWER", "(" + json.dumps(answer) + ")").replace("FUNCTION", fn)
    return run_js(script)


got = dry_run({"status": "refused", "reason": "the session has no tool steps"})
check("C1 a refusal is shown instead of a stale report",
      "not recorded" in got.get("last", "") and "no tool steps" in got.get("last", ""), got)
check("C2 the previous report is NOT re-rendered as this run", got.get("reloaded") == 0, got)
got = dry_run({"status": "failed", "reason": "editor failed: TimeoutError"})
check("C3 a failed run is shown too", "not recorded" in got.get("last", ""), got)
got = dry_run({"status": "dry-run", "base": {"steps": 3}})
check("C4 a real dry run reloads the panel", got.get("reloaded") == 1, got)

print("\n---\nv710: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
