#!/usr/bin/env python3
"""v1004 — My Artifacts lists FOLDERS (this session's, or every session's), and the
rules say how to verify a change.

Operator: *"if i put this session disappear the artifacts!!! all counted zero. BUG! please
write in the project rules general way to verify after coding"*, then, after the first fix
turned the session into a per-row filter: *"failed. was good before. session show files in
the workspace of the session selected in session panel. all consider all session workspaces
files whats difficult its simple"* and *"what the fuck that menu stand for? it has just ONE
session listed kb test what does it mean? i told to verify!!"*.

So the page asks ONE question — WHICH FOLDERS — with two answers, both read from the disk:
  * `session`  → the workspace folder of the session the Sessions panel has open;
  * `all`      → the UNION of every session's workspace folder (`scope=sessions`).
A per-row session filter is NOT the question ("kb test" alone was the answer to a question
nobody asked), and the 2026-11-14 scope that read a session's EDIT JOURNAL is the defect
that zeroed the page: a journal is not a folder.

Locked here:
  A1 the route resolves the folders from the session store, never from the client;
  A2 the union walks each distinct root once, drops nested roots, shares one file budget,
     and stamps each row with the root it was found under;
  A3 the union really dedupes (a workspace inside another lists its file once);
  A4 the single-folder scan keeps its shape and now names its root on every row;
  B1 the page's two queries (workspace / sessions) and no third;
  B2 the control's two options come from the sessions panel, never from the rows;
  B3 choosing an option re-queries (a different folder is a different answer);
  B4 an empty answer names the folder and offers the other scope;
  B5 the per-row session filter and the journal route are gone;
  C1 a file no session wrote wears its FOLDER's name, not the word "workspace";
  D1 the project rules carry the general verification protocol;
  D2 `UserPrompts.md` carries the app-wide rule (a view never empties itself).

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1004_artifacts_scope_and_verify_protocol.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1004-")
OUTER = os.path.join(TMP, "outer")
INNER = os.path.join(OUTER, "inner")
SIDE = os.path.join(TMP, "side")
for _d in ("config", "sessions", "edits", "runs", "graphs", OUTER, INNER, SIDE):
    os.makedirs(os.path.join(TMP, _d) if not _d.startswith(TMP) else _d, exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_BROWSE_ROOTS"] = TMP
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import edits as E          # noqa: E402
from longrun.core import api_v02 as A         # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


ui = read("webui/index.html")
rules = read(".trae/rules/project_rules.md")
ups = read("UserPrompts.md")
backend = read("src/longrun/core/api_v02.py")
edits_src = read("src/longrun/tools/edits.py")

# --- A: the union is the folder set, resolved on the server -------------------
check("A1 the route resolves the folders from the session store (never the client)",
      'if scope == "sessions":' in backend
      and "stores_mod.list_sessions()" in backend
      and "_safe_fs_path(ws, allowed)" in backend
      and "edits_mod.workspaces_artifacts(" in backend)
check("A2 the union drops nested roots and gives each root its own budget",
      "def workspaces_artifacts(roots" in edits_src
      and 'p.startswith(k.rstrip(os.sep) + os.sep)' in edits_src
      and "_scan_root(root, kind, needle, own, MAX_WORKSPACE_FILES)" in edits_src
      and "budget - scanned" not in edits_src)
check("A3 each row says which root it was found under",
      '"exists": True, "workspace": root' in edits_src)

write(os.path.join(OUTER, "report.html"), "<h1>outer</h1>\n")
write(os.path.join(INNER, "notebook.md"), "# inner\n")
write(os.path.join(SIDE, "sheet.csv"), "a,b\n1,2\n")
union = E.workspaces_artifacts([INNER, OUTER, SIDE])
names = sorted(r["name"] for r in union["artifacts"])
check("A4 the union lists each file ONCE, nested folder folded into its parent",
      names == ["notebook.md", "report.html", "sheet.csv"]
      and sorted(union["workspaces"]) == sorted([os.path.realpath(OUTER), os.path.realpath(SIDE)]),
      {"names": names, "workspaces": union["workspaces"]})
check("A5 the union names its scope and stamps every row with its folder",
      union.get("scope") == "sessions" and union.get("count") == 3
      and {r["workspace"] for r in union["artifacts"]} == {os.path.realpath(OUTER), os.path.realpath(SIDE)},
      union.get("count"))
one = E.workspace_artifacts(OUTER)
check("A6 the single-folder scan keeps its shape and now names its root",
      one.get("scope") == "workspace" and one.get("count") == 2
      and {r["workspace"] for r in one["artifacts"]} == {OUTER}, one.get("count"))
check("A7 a kind filter applies inside the union",
      sorted(r["name"] for r in E.workspaces_artifacts([OUTER, SIDE], kind="html")["artifacts"])
      == ["report.html"])

# --- B: the page's one question, two answers ---------------------------------
load = ui[ui.find("async function loadArtifacts()"):][:3200]
check("B1 the page asks two folder questions and no third",
      'new URLSearchParams({ limit: "500", scope: "sessions" })' in load
      and 'new URLSearchParams({ limit: "500", scope: "workspace", workspace: _art.ws })' in load
      and 'qs.set("session"' not in load and "scope: \"journal\"" not in load)
check("B2 the control's options come from the sessions panel, never from the rows",
      # 2026-11-18: the labels now name FOLDERS ("This session's folder" / "All
      # sessions' folders") because that is what these two scopes answer, while the
      # RH Workspace panel lists the session's journal — a different set.
      'const opts = [["session", "This session\'s folder · " + mine]' in ui
      and '["all", "All sessions\' folders · " + n + " folder"' in ui
      and "const mine = _art.titles[sessionId] || _art.wsName" in ui
      and "_art.all.forEach(a => { seen[a.session" not in ui)
check("B3 choosing an answer re-queries the folder (never filters the old rows)",
      "ss.onchange = () => { _art.scope = ss.value; loadArtifacts(); };" in ui)
check("B4 an empty answer names the folder and offers the other scope",
      'no artifact-typed files in " + esc(_art.wsName || "this folder")' in ui
      and 'data-scope="all"' in ui and "show all sessions" in ui
      and "no artifact-typed files in the workspaces of these sessions" in ui)
art = ui[ui.find("const ART_KIND_ORDER"):]
art = art[:art.find("function _artThumbDrop(")]
check("B5 the per-row session filter and the journal route are gone",
      "_art.sess" not in art and "_artSessMatch" not in art and "data-clear-sess" not in art
      and '"__none__"' not in art)
check("C1 a file no session wrote wears its folder's name",
      "function _artFolderName(p)" in ui
      and "esc(a.session ? (_art.titles[a.session] || a.session) : _artFolderName(a.workspace))" in ui)
check("C2 the counter names the scope it is counting",
      '_art.scope === "all" ? " · all sessions" : " · " + (_art.wsName || "this folder")' in ui)
check("C3 the control is named for what it does (a11y, one vocabulary)",
      'aria-label="list this session\'s workspace folder or every session\'s folder"' in ui)

# --- D: the protocol the operator asked to have written down ------------------
check("D1 the rules carry the general verification protocol",
      "## Verification after coding — the general protocol (2026-11-14)" in rules
      and all(("%d. **" % n) in rules for n in range(1, 8)))
check("D1b the Workflow line points at it instead of describing a second time",
      "MEANS is §Verification after coding" in rules)
check("D1c the protocol names the states that broke these rounds",
      "visual pixels inside a zoomed page" in rules and "emptied the whole page" in rules)
check("D2 UserPrompts carries the app-wide rule",
      "## 5. Lists, filters and empty states" in ups
      and "a view never empties itself" in ups
      and "5.1" in ups and "5.2" in ups and "5.3" in ups and "5.4" in ups
      and "implement §1–§5 literally" in ups)

print("---")
passed = sum(RESULTS)
print("v1004: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
