#!/usr/bin/env python3
"""v354 — chat file links, pinned-session marker, todos survive compaction, doc honesty (JAG-354).

Deterministic (no model, no network). Two halves:

  A) Static guards on the WebUI + API + docs:
     - a pinned session is MARKED in the left rail (📌 + heavier title);
     - the reply linkifier matches absolute, RELATIVE and bare paths (so the
       `viz/trend.png` / `insights.md` an agent emits become clickable) and covers
       code extensions too;
     - `_rawUrl` carries the session so a relative image preview resolves;
     - the fs endpoints resolve a relative `?path=` against the session workspace;
     - the README no longer frames Longrun as "not a meta-harness" and states the
       one real dependency (PyYAML) instead of "zero pip dependencies".
  B) Behavioural: a task list survives transcript compaction (it is re-injected into
     the current user turn, and the task graph is never touched).

Run: python3 tests/acceptance/v354_ui_links_pins.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
API = _read("src", "longrun", "core/api_v02.py")
README = _read("README.md")
CHANGELOG = _read("CHANGELOG.md")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A1: pinned sessions are marked in the rail ------------------------------
check("P1 pinned rows carry a marker span + class",
      '<span class="pin" title="pinned session">📌</span>' in HTML
      and 'pinnedIds.includes(s.id) ? " pinned"' in HTML, "")
check("P2 the pin marker has its own style",
      ".sess .pin {" in HTML and ".sess.pinned .t {" in HTML, "")
check("P3 pinned sessions are still sorted first",
      "pinnedIds.includes(b.id) ? 1 : 0" in HTML, "")

# --- A2: the reply linkifier matches relative + bare paths -------------------
check("L1 the linkifier matches absolute/~ paths (no space over-capture)",
      r'"(?:\\/|~\\/)[\\w.\\-\\/]*\\' in HTML, "")
check("L2 the linkifier matches RELATIVE dir paths",
      r'"|(?:\\.{1,2}\\/)?(?:[\\w.\\-]+\\/)+[\\w.\\-]+\\' in HTML, "")
check("L3 the linkifier matches BARE filenames (guarded, no console.log)",
      r'"|(?<![\\w.\\-\\/])[\\w\\-]+\\' in HTML, "")
check("L4 code extensions are linkifiable (a generated script opens)",
      "|py|js|mjs|" in HTML, "")
check("L5 `_readable` shares the same extension set",
      'return READABLE_END_RE.test(p || "")' in HTML, "")

# --- A3: relative paths resolve against the session workspace ----------------
check("A1 the image preview URL carries the session",
      '(sessionId ? "&session=" + encodeURIComponent(sessionId) : "")' in HTML, "")
check("A2 `_resolve_fs_arg` exists in the fs API",
      "def _resolve_fs_arg(" in API, "")
check("A3 a relative path is tried against the workspace root FIRST",
      "d = _os.path.abspath(_os.path.expanduser(root))" in API
      and "candidates.append(_os.path.join(d, p))" in API, "")
check("A4 every fs handler resolves the path argument",
      "def _fs_allowed_roots(qs=None)" in API
      # 3 handlers in JAG-354 (list/read/write) + the JAG-501 search handler
      and API.count("_fs_allowed_roots(q)") == 4
      and "_fs_allowed_roots(b)" in API, "")

# --- A4: the README is accurate (positioning + dependencies) -----------------
check("D1 the wrong 'not another meta-harness' framing is gone",
      "not another meta-harness" not in README, "")
check("D2 the 'zero pip dependencies' claim is corrected",
      "zero pip dependencies" not in README and "PyYAML" in README, "")
check("D3 README states product scope and excludes private test endpoints",
      "Self-hosted AI agent harness" in README
      and all(value not in README for value in (
          "100.102.61.23", "192.168.1.37", "100.76.251.9",
          "Ollama Windows test", "a05c548dce55")), "")
check("D4 the 1.0.0 changelog no longer says 'merely spawns sub-agents'",
      "merely spawns sub-agents" not in CHANGELOG, "")
_ntests = len([f for f in os.listdir(os.path.join(REPO, "tests", "acceptance"))
               if f.startswith("v") and f.endswith(".py")])
check("D5 the README battery count matches the acceptance-suite size",
      ("%d/%d" % (_ntests, _ntests)) in README, "%d tests" % _ntests)

# --- B: a task list survives compaction --------------------------------------
TMP = tempfile.mkdtemp(prefix="sf-v354-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine as CE  # noqa: E402
from longrun.core import server as S  # noqa: E402
from longrun.core import api_v02 as API_MOD  # noqa: E402
from longrun.plan import taskgraph as TG  # noqa: E402
from longrun.tools import registry as REG  # noqa: E402

# Keep prompt construction local; acceptance tests must never start MCP clients.
REG._external_tools = lambda: {}

# An explicit `root=` must not grant itself access outside configured browse roots.
_browse_root = os.path.join(TMP, "browse")
_outside_root = os.path.join(TMP, "outside")
os.makedirs(_browse_root, exist_ok=True)
os.makedirs(_outside_root, exist_ok=True)
os.environ["LONGRUN_BROWSE_ROOTS"] = _browse_root
_outside_file = os.path.join(_outside_root, "guarded.txt")
with open(_outside_file, "w", encoding="utf-8") as _f:
    _f.write("original")
_fs_read = API_MOD.fs_read({"path": _outside_file, "root": _outside_root})
check("A5 explicit roots cannot read outside configured browse roots",
      _fs_read.get("error") == "path outside allowed roots", str(_fs_read))
_fs_list = API_MOD.fs_list({"path": _outside_root, "root": _outside_root})
check("A6 explicit roots cannot list outside configured browse roots",
      _fs_list.get("error") == "path outside allowed roots", str(_fs_list))
_fs_write = API_MOD.fs_write({"path": _outside_file, "root": _outside_root,
                              "content": "tampered"})
with open(_outside_file, encoding="utf-8") as _f:
    _outside_content = _f.read()
check("A7 explicit roots cannot write outside configured browse roots",
      _fs_write.get("error") == "path outside allowed roots"
      and _outside_content == "original", str(_fs_write))
_session_ws_original = API_MOD._session_ws
API_MOD._session_ws = lambda sid: (_outside_root, {"id": sid})
try:
    _session_read = API_MOD.fs_read(
        {"path": _outside_file, "session": "trusted-workspace"})
finally:
    API_MOD._session_ws = _session_ws_original
check("A8 a session-owned workspace remains accessible outside browse roots",
      _session_read.get("text") == "original", str(_session_read))
_previous_browse_roots = os.environ.get("LONGRUN_BROWSE_ROOTS")
os.environ["LONGRUN_BROWSE_ROOTS"] = (
    r"C:\Users\Operator\Longrun Work;D:\Shared Files")
with patch("os.pathsep", ";"), \
        patch("os.path.realpath", side_effect=lambda path: path), \
        patch("os.path.expanduser", side_effect=lambda path: path):
    _windows_roots = API_MOD._browse_roots()
if _previous_browse_roots is None:
    os.environ.pop("LONGRUN_BROWSE_ROOTS", None)
else:
    os.environ["LONGRUN_BROWSE_ROOTS"] = _previous_browse_roots
check("A9 browse roots parse Windows drives and paths containing spaces",
      _windows_roots == [r"C:\Users\Operator\Longrun Work", r"D:\Shared Files"],
      str(_windows_roots))
os.environ["LONGRUN_BROWSE_ROOTS"] = os.path.abspath(os.sep)
_root_file = API_MOD.fs_read({"path": _outside_file})
check("A10 filesystem root permits reads of files beneath it",
      _root_file.get("text") == "original", str(_root_file))
os.environ["LONGRUN_BROWSE_ROOTS"] = _browse_root

g = TG.ensure("cc1", session_id="cc1")
TG.add_node(g, "open task XY")

state = S.state_block(session_id="cc1")
check("B1 the harness state block lists the open step", "open task XY" in state, state)

# A long transcript (well over the compaction floor) + the live todo block on the
# current user turn — exactly how assemble_turn feeds context_engine.build.
msgs = [{"role": "user", "content": "step %d filler %s" % (i, "x" * 400)} for i in range(24)]
turn = "please continue\n\n" + state
out, stats = CE.build("system prompt", msgs, turn, budget_tokens=300, keep_recent=1,
                      retrieve_memory=False)
joined = "\n".join(str(m.get("content")) for m in out)
check("B2 compaction really happened", stats["compaction"]["compacted"] > 0, str(stats["compaction"]))
check("B3 the todo list survives compaction", "open task XY" in joined, "")
check("B4 the todo list rides the FINAL user turn (added after compaction)",
      out[-1]["role"] == "user" and out[-1]["content"].endswith(state), "")
check("B5 the task graph itself is untouched by compaction",
      any(n.get("label") == "open task XY" for n in (TG.load("cc1") or {}).get("nodes", [])), "")
check("B6 the always-on state section still names the open step",
      "open task XY" in S.context_summary(session_id="cc1"), "")

# --- B8: the editor tree shows hidden + gitignored entries (JAG-509) --------
# The tree used to drop every dot-entry, so .Matrix / .agent / .env were absent
# from the editor: the operator could not see or open them at all.
_tree_root = os.path.join(TMP, "tree")
for _rel in (".Matrix/docs/MANUAL.md", ".agent/docs/handoff/HANDOFF.md", ".env", "src.py",
             "node_modules/pkg/index.js", ".git/config"):
    _fp = os.path.join(_tree_root, *_rel.split("/"))
    os.makedirs(os.path.dirname(_fp), exist_ok=True)
    with open(_fp, "w", encoding="utf-8") as _fh:
        _fh.write("x")
_prev_tree_roots = os.environ.get("LONGRUN_BROWSE_ROOTS")
os.environ["LONGRUN_BROWSE_ROOTS"] = _tree_root
try:
    _tree = API_MOD.fs_list({"path": _tree_root})
    _hidden_read = API_MOD.fs_read(
        {"path": os.path.join(_tree_root, ".Matrix", "docs", "MANUAL.md")})
finally:
    if _prev_tree_roots is None:
        os.environ.pop("LONGRUN_BROWSE_ROOTS", None)
    else:
        os.environ["LONGRUN_BROWSE_ROOTS"] = _prev_tree_roots
_tree_names = ({e["name"] for e in _tree.get("dirs", [])}
               | {e["name"] for e in _tree.get("files", [])})
check("A11 the editor tree lists hidden + gitignored entries",
      {".Matrix", ".agent", ".env", "src.py"} <= _tree_names,
      str(sorted(_tree_names)))
check("A12 the tree still hides VCS internals and dependency folders",
      not ({".git", "node_modules"} & _tree_names), str(sorted(_tree_names)))
check("A13 a hidden entry stays readable through the same sandboxed API",
      _hidden_read.get("text") == "x", str(_hidden_read))

# --- B7: the context PREVIEW uses the REAL system prompt (JAG-366) -----------
_pv = CE.preview(S.get_or_create_session(None, title="preview-probe")["id"])
check("B7 preview reports the REAL section-registry system prompt (not the legacy constant)",
      "error" not in _pv and _pv.get("system_prompt_tokens", 0) > 1000,
      "sys_tokens=%s" % _pv.get("system_prompt_tokens"))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
