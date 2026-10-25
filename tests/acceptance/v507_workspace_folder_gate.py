#!/usr/bin/env python3
"""v507 — Workspace folder is browsable, and ONE dirty-gate drives every Save.

The WebUI has a single save/apply behaviour for every settings panel:

  * a button carrying the `.config-save` class stays DIMMED and DISABLED until
    the form around it differs from the values it was loaded/saved with;
  * the shared helpers `_gateValue/gateSync/gateEnroll` + the two delegated
    input/change listeners implement it once — no panel re-implements it;
  * the folder picker is target-aware, and picking a folder for the Workspace
    card commits it immediately (the pick IS the save);
  * folder browsing goes through the SERVER (`GET /api/fs/dirs`), so it works
    whatever the harness host is (Windows, Linux, ARM64);
  * the oversized "use this folder" label is gone: the action reads `save`.

JAG-2.8 adds the two halves that made the card look broken: the picker names the
SESSION (so a workspace outside the browse roots is still browsable instead of a
dead end), and the card states whether a save targets THIS session or the global
default. The shipped default workspace is DERIVED from the checkout
(`<repo parent>/.longrun/workspaces`), never a hardcoded absolute path.

This test is a source contract, plus four executed checks: it never starts a
server and never calls a model.

Run: python3 tests/acceptance/v507_workspace_folder_gate.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as fh:
    UI = fh.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one source contract for the workspace picker and the save gate."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _function_body(source: str, name: str, next_name: str) -> str:
    """Return a named function and its body from the inline UI script."""
    start = source.find(name)
    end = source.find(next_name, start + len(name))
    return source[start:end] if start >= 0 and end > start else ""


gate_value = _function_body(UI, "function _gateValue(root)", "function gateSync")
gate_sync = _function_body(UI, "function gateSync(root)", "function gateEnroll")
gate_enroll = _function_body(UI, "function gateEnroll(root)", "function _gateOwner")
gate_owner = _function_body(UI, "function _gateOwner(el)", "[\"input\", \"change\"]")
open_picker = _function_body(UI, "async function openDirPicker(target)",
                            "function closeDirPicker")
load_dirs = _function_body(UI, "async function loadDirs(path)", "function dirUp")
pick_dir = _function_body(UI, "function pickCurrentDir()", "async function loadHistory")
load_rules = _function_body(UI, "async function loadRules()", "async function saveRules")

# --- A: the Workspace card can browse folders ---------------------------------
check("the Workspace card can open the folder picker for its own path",
      'id="wsCard"' in UI
      and 'data-call="openDirPicker" data-args=\'["wsPath"]\'' in UI,
      "browse button targets #wsPath")

check("the folder list comes from the server, so browsing is host-agnostic",
      "function openDirPicker(target)" in UI
      and '"/api/fs/dirs"' in load_dirs
      and "const qs = path ? (\"?path=\" + encodeURIComponent(path)) : \"\"" in load_dirs,
      "GET /api/fs/dirs")

check("the picker remembers which input opened it",
      "let _dirTarget" in UI
      and "_dirTarget = target || \"nsWs\"" in open_picker
      and "const src = $(_dirTarget)" in open_picker,
      "_dirTarget")

# --- B: the pick auto-saves for the Workspace card ----------------------------
check("picking a folder writes the input it was opened from",
      "const target = _dirTarget, path = _dirState.path || \"\"" in pick_dir
      and "const el = $(target)" in pick_dir
      and "el.value = path" in pick_dir,
      "target input receives the picked path")

check("choosing a folder for the Workspace card saves it immediately",
      'if (target === "wsPath") setWorkspace();' in pick_dir
      and "async function setWorkspace()" in UI
      and 'toast("folder path required"' in UI,
      "browse → save, and the empty-path guard is kept")

# --- C: one shared dirty-gate, never copied per panel -------------------------
check("exactly one gate compares a form against its loaded baseline",
      "function _gateValue(root)" in UI
      and "root.querySelectorAll(\"input,select,textarea\")" in gate_value
      and "if (!root || root._gate === undefined) return;" in gate_sync
      and "const dirty = _gateValue(root) !== root._gate;" in gate_sync,
      "gateSync")

check("a gated Save is disabled and un-highlighted until the form changes",
      "btn.disabled = !dirty;" in gate_sync
      and "btn.classList.toggle(\"dirty\", dirty);" in gate_sync
      and "title = dirty ?" in gate_sync,
      "highlight + block")

check("enrolling a panel snapshots the baseline the Save compares against",
      "root._gate = _gateValue(root);" in gate_enroll
      and "if (!root || !root.querySelector(\"button.config-save\")) return;" in gate_enroll,
      "gateEnroll")

check("a live gated Save never claims there is nothing to save",
      "/^no changes/i.test(authored)" in gate_sync
      and "btn.dataset.gateIdle = idle;" in gate_sync
      and 'btn.title = dirty ? (btn.dataset.gateTitle || "save changes") : btn.dataset.gateIdle;' in gate_sync,
      "idle wording only while dimmed")

check("the gate is wired with delegated listeners, not per field",
      '["input", "change"].forEach(ev =>' in UI
      and "document.addEventListener(ev, e => { const o = _gateOwner(e.target); if (o) gateSync(o); }, true));" in UI
      and "if (n._gate !== undefined) return n;" in gate_owner,
      "document-level input/change")

check("the pre-existing structured-form and raw-YAML gates are not duplicated",
      "function _syncSectionDirty" in UI
      and "save.disabled = !isDirty" in UI
      and "_cfgFileBaseline" in UI
      and 'id="cfgFileSave" disabled' in UI,
      "v506 contracts preserved")

# --- D: every similar save/apply button joined the same class -----------------
GATED_BUTTONS = (
    ('id="wsSave"', 'class="ghost config-save" id="wsSave" data-call="setWorkspace" disabled'),
    ("saveRuntime", '<button class="ghost config-save" data-call="saveRuntime" disabled'),
    ("saveVerifier", '<button class="ghost config-save" data-call="saveVerifier" disabled'),
    ("saveBestofn", '<button class="ghost config-save" data-call="saveBestofn" disabled'),
    ("saveDifficulty", '<button class="ghost config-save" data-call="saveDifficulty" disabled'),
    ("saveSelfevolve", '<button class="ghost config-save" data-call="saveSelfevolve" disabled'),
    ("saveToken", '<button class="ghost config-save" data-call="saveToken" disabled'),
    ("saveRules global",
     '<button class="ghost config-save u-mt8" data-call="saveRules" data-args=\'["global"]\' disabled'),
    ("saveRules project",
     '<button class="ghost config-save u-mt8" data-call="saveRules" data-args=\'["project"]\' disabled'),
    ("saveProvider", '<button class="ghost config-save u-mt8" data-call="saveProvider" disabled'),
    ("sandbox", '<button class="ghost config-save" id="sbxSave" disabled'),
    ("advanced tool policy", '<button class="ghost config-save" id="advSave" disabled'),
    ("mcp json confirm", '<button class="ghost config-save" data-call="applyMcpJson" disabled'),
)
_missing = [label for label, needle in GATED_BUTTONS if needle not in UI]
check("every save/apply button of the settings class is gated the same way",
      not _missing, "missing: " + ", ".join(_missing) if _missing else
      "%d buttons gated" % len(GATED_BUTTONS))

check("every gated panel enrolls the gate when it loads and re-bases after a save",
      UI.count("gateEnroll(") >= 20
      and 'gateEnroll($("wsCard"))' in load_rules
      and 'gateEnroll(sandboxEl.querySelector("#sbxCard"))' in UI
      and "gateEnroll(box);" in UI
      and UI.count("re-base after a save") >= 5,
      "%d gateEnroll calls" % UI.count("gateEnroll("))

# --- E: the oversized picker label is gone ------------------------------------
check("the picker action is a compact save, not the oversized label",
      'id="dirPick"' in UI
      and ">save</button>" in UI
      and "use this folder" not in UI,
      "no 'use this folder' left")

check("the highlight reuses the existing accent token",
      "button.config-save.dirty:not(:disabled)" in UI
      and "color: var(--acc)" in UI,
      ".config-save.dirty")

# --- F: the picker is session-aware and never dead-ends (JAG-2.8) -------------
check("the picker names the SESSION, so that session's own workspace is a root",
      'const sid = (typeof sessionId !== "undefined" && sessionId) ? sessionId : "";' in load_dirs
      and '"session=" + encodeURIComponent(sid)' in load_dirs,
      "GET /api/fs/dirs?…&session=<sid>")

check("a folder outside the roots falls back to the first root and says why",
      "await loadDirs(roots[0]);" in load_dirs
      and "is outside the browsable roots" in load_dirs
      and "roots: \" + roots.join" in load_dirs,
      "no empty dead-end list")

# v638: the always-visible "save links this folder to THIS session" line was a second
# row of prose saying what the checkbox next to it already says. The SCOPE is now the
# checkbox label; the card carries no status sentence.
check("the save scope is stated by the checkbox, not by a status line",
      '<input type="checkbox" id="wsDefault"> default for new sessions' in UI
      and 'id="wsTarget"' not in UI and "function _wsTargetHint()" not in UI,
      "session vs default is explicit without a paragraph")

check("the UI carries no hardcoded absolute folder example",
      "/home/jagones" not in UI and 'placeholder="folder path…"' in UI,
      "placeholders are host-agnostic (v636: the 📁 link became an icon button)")

with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as fh:
    API = fh.read()
_fs_dirs = _function_body(API, "def fs_dirs(qs=None)", "def _ws_root")
with open(os.path.join(REPO, "src", "longrun", "memory", "rules.py"), encoding="utf-8") as fh:
    RULES = fh.read()

check("server: the picker allows the browse roots PLUS the session workspace",
      "roots = _fs_allowed_roots(qs)" in _fs_dirs,
      "same rule as the file tree")

check("server: the default workspace is DERIVED from the user data home, never hardcoded",
      "base = paths.WORKSPACES_DIR" in RULES
      and 'LONGRUN_WORKSPACES_ROOT' in RULES
      and "base = workspaces_root()" in RULES,
      "workspaces_root()")

# --- G: the same rules, executed (no server, no network) ----------------------
import tempfile  # noqa: E402
import shutil  # noqa: E402

TMP = tempfile.mkdtemp(prefix="sf-v507-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")   # no config.json at all
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
os.environ.pop("LONGRUN_WORKSPACE", None)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import rules as rules_mod  # noqa: E402

check("G1 with nothing configured the default workspace is the derived workspaces root",
      rules_mod.get_workspace() == os.path.join(TMP, "ws"), rules_mod.get_workspace())
check("G2 that root is created on demand", os.path.isdir(os.path.join(TMP, "ws")))

from longrun.core import api_v02  # noqa: E402

ROOTS = os.path.join(TMP, "roots")
OUTSIDE = os.path.join(TMP, "outside")
os.makedirs(os.path.join(OUTSIDE, "sub"))
os.makedirs(ROOTS)
os.environ["LONGRUN_BROWSE_ROOTS"] = ROOTS

_refused = api_v02.fs_dirs({"path": OUTSIDE})
check("G3 without a session, a path outside the browse roots is still refused",
      _refused.get("error") == "path outside browse roots", _refused.get("error"))

_orig_ws = api_v02._session_ws
api_v02._session_ws = lambda sid: (OUTSIDE, {"id": sid})
_allowed = api_v02.fs_dirs({"path": OUTSIDE, "session": "s1"})
api_v02._session_ws = _orig_ws
check("G4 naming the session allows that session's workspace (was the dead end)",
      not _allowed.get("error") and _allowed.get("count") == 1, _allowed)
shutil.rmtree(TMP, ignore_errors=True)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
