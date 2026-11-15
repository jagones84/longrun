#!/usr/bin/env python3
"""v1002 — a file opens in a dedicated preview window, with a first frame on its card.

Source (operator, 2026-11-14): *"i want previews thanks. also dont open in the
editor open in a new dedicated window … all command to close, tree dot menu to do
things to open path, right click on files to get abs path etcetera"*.

Locked here:
  B  the raw route serves INERT media (video/audio) and still refuses every script
     container (text/html, image/svg+xml) — the preview window plays a video
     without widening the XSS surface;
  U1 the window exists (dialog semantics) and has three ways to close: ✕, Esc, the
     backdrop;
  U2 the ⋯ menu is named and carries the real actions (editor, raw tab, source,
     copies, reload);
  U3 the card opens the WINDOW (not the editor dock), and right-click prints the
     absolute path for both a card and a Workspace row;
  U4 posters: only a kind with a first frame gets one, it is a SIBLING of the card
     button (never `nested-interactive`), and it is created only while on screen;
  U5 each renderer uses the safe route: raw for media/pdf, /api/fs/read for text
     and HTML (sandbox, never allow-same-origin), /api/fs/sheet for a workbook,
     sanitized markdown for a note;
  U6 the phone makes the window full-bleed.

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1002_preview_window.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1002-")
os.environ["LONGRUN_BROWSE_ROOTS"] = TMP
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


class Stub:
    def __init__(self):
        self.codes = []
        self.ctypes = []

    def _send(self, code, obj, ctype="application/json"):
        self.codes.append(code)
        self.ctypes.append(ctype)


def write(name, data):
    p = os.path.join(TMP, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


# --- B: the raw route stays an allow-list, now with inert media --------------
mp4 = write("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 32)
mp3 = write("tone.mp3", b"ID3\x04\x00" + b"0" * 32)
html = write("page.html", b"<script>alert(1)</script>")
svg = write("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="x=1"/>')

h = Stub()
A._fs_raw(h, {"path": mp4})
check("B1 a video is served inline (200 video/mp4)",
      h.codes == [200] and h.ctypes[-1].startswith("video/"), (h.codes, h.ctypes))

h = Stub()
A._fs_raw(h, {"path": mp3})
check("B2 audio is served inline (200 audio/*)",
      h.codes == [200] and h.ctypes[-1].startswith("audio/"), (h.codes, h.ctypes))

h = Stub()
A._fs_raw(h, {"path": html})
check("B3 text/html is still refused (415)", h.codes == [415], h.codes)

h = Stub()
A._fs_raw(h, {"path": svg})
check("B4 image/svg+xml is still refused (415)", h.codes == [415], h.codes)

# --- U: the page -------------------------------------------------------------
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("U1a the preview is a modal dialog with a name",
      'id="pvWin"' in ui and 'role="dialog" aria-modal="true" aria-labelledby="pvName"' in ui
      and 'id="pvBody"' in ui)
check("U1b three doors close it: the ✕, the backdrop and Esc",
      'data-call="closePreview"' in ui
      and ui.count('data-call="closePreview"') >= 2
      and 'if ($("pvWin") && !$("pvWin").hidden) closePreview();' in ui)
check("U1c the close control is a named icon, not a bare glyph",
      'aria-label="close preview"' in ui and 'title="close preview (Esc)"' in ui)
check("U1d the absolute path is printed under the name and copies on click",
      'id="pvPath"' in ui and '$("pvPath").textContent = path;' in ui
      and 'pp.onclick = () => { if (_pv.path) _pvCopy(_pv.path); };' in ui)

check("U2a the ⋯ menu is a named icon button with expanded state",
      'id="pvMore"' in ui and 'aria-label="more actions"' in ui
      and 'aria-controls="pvMenu"' in ui and 'aria-expanded="false"' in ui)
check("U2a2 both popups are named regions (a floating role=menu outside a landmark is axe's `region`)",
      'id="pvMenu" role="region" aria-label="preview actions"' in ui
      # 2026-11-16: the one context menu now serves every object (right-click rollout),
      # so its name is `object actions`; same region contract.
      and 'id="artCtx" role="region" aria-label="object actions"' in ui
      and 'role="menuitem"' not in ui)
check("U2b the ⋯ menu carries the real actions",
      all(s in ui for s in ('"Open in the editor"', '"Open raw in a new tab"',
                            '"Show the source"', '"Copy the absolute path"',
                            '"Copy the path inside the workspace"', '"Reload"')))

check("U3a a card opens the window, not the editor dock",
      "c.onclick = () => openPreview(c.dataset.path, row);" in ui
      and "function openArtifact(" not in ui)
check("U3b a card right-click prints the absolute path",
      "c.oncontextmenu = e => {" in ui and 'class="cx-path"' in ui
      and "openFileCtx(e.clientX, e.clientY" in ui)
check("U3c a Workspace row has the same right-click menu",
      'row.oncontextmenu = e => {' in ui
      and 'exists: f.disk !== "missing"' in ui)
check("U3d the context menu offers the three copies",
      all(s in ui for s in ('"Copy the absolute path"', '"Copy the path inside the workspace"',
                            '"Copy the file name"', '"Preview"')))

check("U4a only a kind with a first frame gets a poster",
      'function _pvHasPoster(kind, path)' in ui
      and 'kind === "image" || kind === "video" || kind === "html" || _pvIsPdf(path)' in ui)
check("U4b the poster is a SIBLING of the card button (nested-interactive guard)",
      '\'<div class="art-item">\'' in ui
      and '\'<div class="art-thumb" data-path="' in ui
      and ".art-item > .art-card" in ui)
check("U4c posters are created only while on screen, with a bound",
      "new IntersectionObserver" in ui and "ART_THUMB_LIVE = 12" in ui
      and "function _artThumbDrop(box)" in ui)
check("U4d the poster is decorative for the a11y tree",
      'aria-hidden="true" title="preview ' in ui)

check("U5a media and pdf go through the token-bearing raw URL",
      "img.src = _rawUrl(path);" in ui and "f.src = _rawUrl(path);" in ui
      and "v.src = _rawUrl(path);" in ui)
check("U5b HTML renders in a sandboxed frame, never same-origin",
      'f.setAttribute("sandbox", "allow-scripts allow-popups")' in ui
      and 'f.setAttribute("sandbox", "allow-same-origin")' not in ui
      and "f.srcdoc = r.text || \"\";" in ui)
check("U5c text is read through /api/fs/read and set as TEXT (no HTML injection)",
      '"/api/fs/read?path=" + encodeURIComponent(_pv.path)' in ui
      and "pre.textContent = r.text || \"\";" in ui)
check("U5d a workbook renders its rows through /api/fs/sheet as a real grid",
      '"/api/fs/sheet?path=" + encodeURIComponent(_pv.path)' in ui
      and "function _pvSheetTable(rows, numbered)" in ui
      and 'bar.className = "pv-sheet-bar";' in ui)
check("U5e a markdown note renders through the sanitizer (mdToHtml)",
      "d.innerHTML = mdToHtml(r.text || \"\");" in ui and "mdToHtml(" in ui)

check("U6 the phone makes the preview full-bleed",
      "height: calc(100dvh / var(--zoom, 1)); max-height: calc(100dvh / var(--zoom, 1));" in ui
      and "border-radius: 0; border-left: 0; border-right: 0; }" in ui)

shutil.rmtree(TMP, ignore_errors=True)
print("---")
passed = sum(RESULTS)
print("v1002: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
