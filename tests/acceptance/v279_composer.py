#!/usr/bin/env python3
"""v279 — composer + context panel: real attachments, pickers, copy URLs, voice help.

JAG-279 (live UI feedback): the "+" menu was a stub — "Attach a file" popped a
browser prompt() instead of a file picker, "Workspace files" just opened the
editor, and "Skills" typed a literal "/skill " (not even a real skill name). The
Context panel's Web-Search list had no way to grab the URLs. And the mic silently
failed on the DGX because the page is served over plain HTTP (insecure origin).

Locked here:
  * /api/attach stores an uploaded file and returns a path the model can read;
  * the filename is sanitized, duplicates do not overwrite, oversize/empty rejected;
  * JAG-523: the route accepts EVERY content type (a .json body used to 404) and the
    composer's busy-state sync never runs in the Temporal Dead Zone;
  * the composer uploads via a native <input type=file>, not prompt();
  * Workspace file + Skill open searchable pickers (not the editor / a literal);
  * the Context Web-Search list has per-URL copy + a "copy all URLs" button;
  * voice failure explains the insecure-origin remedy instead of doing nothing.

Deterministic, no live server. Run: python3 tests/v279_composer.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v279-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A   # noqa: E402
from longrun.core import server as S      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1) /api/attach storage ---------------------------------------------------
S.DATA_DIR = os.path.join(TMP, "data")
_ws = os.path.join(S.DATA_DIR, "attachments", "s1")

r = A.attach_save(b"hello world", name="note.txt", session="s1")
check("attach_save returns ok", r.get("ok") is True)
check("the uploaded file is on disk", os.path.isfile(r.get("path") or ""))
check("the stored bytes match", open(r["path"], "rb").read() == b"hello world")
check("the file lives under data/attachments/<session>",
      os.path.join("attachments", "s1") in (r.get("path") or ""))
check("the returned path is absolute for the model to fs.read",
      os.path.isabs(r.get("path") or ""))
check("the upload API marks text documents as knowledge-indexable",
      r.get("indexable") is True)

r_dup = A.attach_save(b"second", name="note.txt", session="s1")
check("a duplicate name does not overwrite the first",
      r_dup["path"] != r["path"] and os.path.isfile(r["path"]))
check("both copies exist", open(r["path"], "rb").read() == b"hello world"
      and open(r_dup["path"], "rb").read() == b"second")
binary = A.attach_save(b"\x00\x01", name="opaque.bin", session="s1")
check("unknown binary uploads are not marked as knowledge-indexable",
      binary.get("indexable") is False)

r_trav = A.attach_save(b"x", name="../../etc/passwd", session="s1")
check("a path-traversal name is neutralised (kept inside the folder)",
      os.path.dirname(r_trav["path"]) == _ws
      and ".." not in os.path.basename(r_trav["path"]))

r_sid = A.attach_save(b"y", name="a.bin", session="../../evil")
check("a path-traversal session id is neutralised (stays under attachments/)",
      os.path.realpath(r_sid["path"]).startswith(
          os.path.realpath(os.path.join(S.DATA_DIR, "attachments")) + os.sep))

check("an empty upload is rejected", A.attach_save(b"", name="z") .get("ok") is False)

os.environ["LONGRUN_ATTACH_MAX"] = "4"
check("an oversize upload is rejected", A.attach_save(b"12345", name="big.bin").get("ok") is False)
del os.environ["LONGRUN_ATTACH_MAX"]

# --- 2) server route ----------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8") as f:
    srv += f.read()
check("server exposes the raw upload route", 'path == "/api/attach"' in srv)
check("the route calls attach_save", "api_v02.attach_save(" in srv)
# JAG-523: the route has NO JSON body contract, so `application/json` is raw bytes
# too. Excluding it (the zip guard, copy-pasted) made a .json attachment 404.
check("attach accepts EVERY content type (no application/json exclusion)",
      'not ctype.startswith("application/json")' not in srv)

# --- 3) composer UI (JAG-279) -------------------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
check("a native file input backs the attach action", 'id="attachInput"' in ui)
check("the attach action uploads the picked files", "function attachFiles" in ui
      and '"/api/attach?"' in ui)
# JAG-523: `_syncAttachmentBusyUI()` reaches `runningSessions` via refreshSendBtn,
# and that state is declared LATER in the same script. Calling it at top level was a
# Temporal Dead Zone crash ("Cannot access 'runningSessions' before initialization")
# that aborted the WHOLE WebUI script, so nothing after it was wired at all.
_busy_call = ui.find("\n_syncAttachmentBusyUI();")
_decl = ui.find("let runningSessions")
check("the busy-state sync never runs before its state is declared",
      _busy_call == -1 or _decl < _busy_call,
      "top-level call at %d, declaration at %d" % (_busy_call, _decl))
check("the busy-state sync still runs from the init chain",
      "_syncAttachmentBusyUI(); refreshSendBtn();" in ui)
check("the old prompt()-based path attach is gone", 'prompt("file path to attach' not in ui)
check("a searchable picker modal exists", 'id="pickModal"' in ui and "function openPick" in ui)
check("workspace files open a picker (not the editor)",
      "function openFsPicker" in ui and "/api/fs/list?" in ui)
check("skills open a picker that inserts /<name>",
      "function openSkillPicker" in ui and '"/api/skills"' in ui)
check("paste-text uses a modal, not prompt()", 'id="textModal"' in ui
      and "function openTextModal" in ui and 'prompt("paste the text' not in ui)
check("the + menu offers Attach files / Workspace / Paste / Commands / Skill",
      all(k in ui for k in ('data-a="files"', 'data-a="workspace"', 'data-a="text"',
                            'data-a="commands"', 'data-a="skills"')))

# --- 4) context panel: copy URLs (JAG-279) -----------------------------------
check("Web-Search shows a 'copy all URLs' button", 'id="ctxCopyAll"' in ui
      and "copy all URLs" in ui)
check("each URL row has its own copy button", 'class="ctxcopy mini"' in ui
      and "data-url=" in ui)
check("copy uses a secure-context-aware helper", "function copyText" in ui
      and "function _copyFallback" in ui)
check("a toast confirms the copy", "function toast" in ui and ".sf-toast" in ui)
check("copy-all joins the URLs one per line", 'webUrls.join("\\n")' in ui)

# --- 5) voice help (JAG-279) --------------------------------------------------
check("voice input detects an insecure origin", "window.isSecureContext" in ui)
check("an in-GUI voice help dialog explains the remedy",
      "function voiceHelp" in ui and "unsafely-treat-insecure-origin-as-secure" in ui
      and 'id="voiceHelp"' in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
