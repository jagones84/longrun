#!/usr/bin/env python3
"""v501 — keyboard file/folder search, workspace auto-refresh, DSML self-heal (JAG-501).

Live findings this locks:

  A) The folder/file browser had no search: choosing a deep workspace folder meant
     clicking every level, and the same browsing logic was duplicated between the
     workspace dir picker, the attach-file picker and the editor tree. ONE shared
     controller now lives in `webui/assets/fsfind.js` and is driven by the server
     endpoint `/api/fs/find`. Behavioural half: the endpoint really walks a tree
     and ranks exact > prefix > substring, dirs before files, honouring `kind`.

  B) Saving a new workspace did not refresh the Files panel, so the operator saw
     the OLD tree until a manual ↻. `setWorkspace` now refreshes every browser.

  C) The Master session "got stuck" and popped a HUMAN IN THE LOOP card too early.
     Ground truth from the event log: the model emitted its native DSML tool call
     with a BARE closing tag (`</|DSML|>`); `_dsml_action` did not parse it, so
     `_extract_action` fell back to `extract_json`, which returned the JSON *inside*
     the markup (`{"script": …}`). That dict has no action key, so the chat loop
     accepted it as the model's final ARTIFACT and ended the turn with 2 todos open
     and 0 keepgoing rounds used — the tool never ran, and the gate reported a
     fake "step_budget · undefined". Both halves are fixed and pinned here.

Deterministic, no model, no network. Run: python3 tests/acceptance/v501_fs_find.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v501-")
WS = os.path.join(TMP, "workspace")
for _d in ("alpha", "alpha/alpha-deep", "beta", "node_modules/alpha"):
    os.makedirs(os.path.join(WS, _d), exist_ok=True)
for _f in ("alpha/alpha-report.md", "alpha/notes.txt", "beta/alphabet.txt", "root.md"):
    with open(os.path.join(WS, _f), "w", encoding="utf-8") as h:
        h.write("x")

os.environ["LONGRUN_BROWSE_ROOTS"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02, server            # noqa: E402,F401  (server first: breaks the import cycle)
from longrun.agent import agent as A                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# --- A: the search endpoint -------------------------------------------------
d = api_v02.fs_find({"q": "alpha", "kind": "dir", "path": WS})
names = [h["name"] for h in d.get("results", [])]
check("A1 a folder fragment finds folders, best match first",
      names[:1] == ["alpha"] and "alpha-deep" in names, names)
check("A2 folders under a skipped heavy dir are not reported",
      "node_modules" not in names, names)
d = api_v02.fs_find({"q": "alpha", "kind": "file", "path": WS})
fnames = [h["name"] for h in d.get("results", [])]
check("A3 kind=file returns files only",
      "alpha-report.md" in fnames and "alpha" not in fnames, fnames)
d = api_v02.fs_find({"q": "root.md", "kind": "file", "path": WS})
check("A4 an exact file name is the first hit",
      [h["name"] for h in d.get("results", [])][:1] == ["root.md"], d.get("results"))
check("A5 each hit carries dir + relative path",
      all("dir" in h and h.get("rel") for h in d.get("results", [])), "")
check("A6 an empty query is rejected, not a full walk",
      "error" in api_v02.fs_find({"q": ""}), "")
check("A7 a path outside the browse roots is refused",
      "error" in api_v02.fs_find({"q": "x", "path": "/etc"}), "")
check("A8 the endpoint is routed", "/api/fs/find" in read("src", "longrun", "core/api_v02.py"))

# --- B: one shared UI controller, wired everywhere --------------------------
FSF = read("webui", "assets", "fsfind.js")
EDITOR = read("webui", "assets", "editor.js")
HTML = read("webui", "index.html")
check("B1 the shared module exposes findPaths + bindSearch",
      "export async function findPaths" in FSF and "export function bindSearch" in FSF)
check("B2 it is usable from the classic inline script too",
      "window.FsFind = { findPaths, bindSearch }" in FSF)
check("B3 the editor imports that module (no second implementation)",
      'from "./fsfind.js"' in EDITOR and "bindSearch(" in EDITOR)
check("B4 the editor tree has the keyboard search box",
      'class="ed-search"' in EDITOR and "state.search = bindSearch" in EDITOR)
check("B5 the folder picker has the search box",
      'id="dirSearch"' in HTML and "bindSearch($(\"dirSearch\")" in HTML)
check("B6 the attach-file picker searches the whole tree",
      "_pickRemoteRun" in HTML and "{ kind: \"any\", base:" in HTML)
check("B7 arrow keys move the picker selection",
      'e.key === "ArrowDown" || e.key === "ArrowUp"' in HTML)
check("B8 the FILES panel hands the tree off to the editor (no second browser)",
      'id="fileSearch"' not in HTML and 'id="fileTree"' not in HTML
      and "window.SparkEditor.toggle()" in HTML)

# --- C: a workspace change refreshes every browser --------------------------
check("C1 saving a workspace refreshes the panels + the editor tree",
      "function _afterWorkspaceChange()" in HTML
      and "_afterWorkspaceChange();" in HTML
      and "window.SparkEditor.reloadTree" in HTML)
check("C2 the editor exports a tree reload",
      "reloadTree: () => loadTree()" in EDITOR)
check("C3 a finished turn refreshes the pending-changes list",
      "refreshEdits(); linkifyAll();" in HTML)

# --- D: DSML self-heal + a truthful human gate ------------------------------
_DSML = "\uff5c\uff5cDSML\uff5c\uff5c"


def _o(rest):
    """Opening tag: `<` + DSML + rest + `>` (the model's native markup)."""
    return "<" + _DSML + rest + ">"


def _c(rest=""):
    """Closing tag; the live markup uses BOTH `</|DSML| invoke>` and a bare `</|DSML|>`."""
    return "</" + _DSML + rest + ">"


BARE = (_o(" calls") + _o(' invoke name="tool"')
        + _o(' parameter name="args"')
        + '{"script": "verify.py", "target": "tool:x"}' + _c(" parameter")
        + _o(' parameter name="tool" string="true"') + "matrix.test" + _c(" parameter")
        + _c() + _c(" calls"))
act = A._extract_action(BARE)
check("D1 the bare closing tag parses into a REAL tool call",
      isinstance(act, dict) and act.get("tool") == "matrix.test"
      and act.get("args", {}).get("script") == "verify.py", act)
WRAPPED = (_o(" calls") + _o(' invoke name="update_todos"')
           + _o(' parameter name="steps" string="false"')
           + '[{"id": "n1", "status": "doing"}]' + _c(" parameter")
           + _c() + _c(" calls"))
act2 = A._extract_action(WRAPPED)
check("D2 a harness action keeps its canonical name + payload",
      isinstance(act2, dict) and act2.get("action") == "todo.update"
      and isinstance(act2.get("steps"), list), act2)
check("D3 DSML never degenerates into an 'artifact' answer",
      A._extract_action(BARE) is not None
      and not A._looks_like_action_dict({"script": "x"}), "")
SRC = read("src", "longrun", "agent", "agent.py")
check("D4 DSML is parsed as DSML only (no extract_json fallback)",
      "if _looks_like_dsml(answer):" in SRC
      and "return _normalize_action(_dsml_action(answer))" in SRC)
check("D5 the turn-end gate reports the REAL reason",
      "_reason2 = _kg_stop_reason or \"open_todos\"" in SRC
      and 'reason=_reason2' in SRC)
check("D6 the gate carries a duration so the UI never prints 'undefined'",
      'duration_s=round(time.time() - _kg_started, 1)' in SRC)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
