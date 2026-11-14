#!/usr/bin/env python3
"""v1011 — the preview window is expandable and paints each file type the standard way.

Source (operator, 2026-11-14): *"the page is not expanible..i dont like how the
code is prdispalyed doesnt exists standard way to sdispaly each fiel types? and to
switch form a viewq to anotehr (maybe use same fucniotns of teh editor rewrittne
best if possible). also .md viewer tehre a re alot of extension doin git fidn on
weg impeknt..for code also serch how to be dispalyed in ide, with correct colors
different for objects etcettrea and so no for other extension files"*.

Locked here:
  A  ONE extension→language table (filetypes.js) feeds the editor and the preview,
     backed by the vendored legacy stream parsers (vendor/langs.js) so `.rs`, `.go`,
     `.sql`, `.sh`, `.toml`, `.xml`, `.c`/`.cpp`, `.java` … are coloured, not
     monospace grey;
  B  viewer.js mounts the SAME CodeMirror engine + oneDark theme read-only (line
     numbers, wrapping, Mod-F search) and publishes `window.LRViewer`;
  C  the window has ⤢ (persisted, full-screen) and a view switch that only offers
     views the file really has (Preview/Source for markdown+HTML, Table/Source for
     CSV/TSV); markdown has real typography; source goes through CodeMirror with a
     TEXT fallback (never innerHTML).

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1011_preview_views_and_highlight.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ui = read("webui", "index.html")
ft = read("webui", "assets", "filetypes.js")
ed = read("webui", "assets", "editor.js")
vw = read("webui", "assets", "viewer.js")
build = read("webui", "assets", "build-vendor.sh")
langs_path = os.path.join(REPO, "webui", "assets", "vendor", "langs.js")
langs = read("webui", "assets", "vendor", "langs.js") if os.path.isfile(langs_path) else ""

# --- A: one vocabulary, many languages ---------------------------------------
check("A1 the legacy language bundle is vendored (a real module, not a stub)",
      len(langs) > 100_000, "%d bytes" % len(langs))
check("A2 the build script owns it (legacy-modes + its own esbuild output)",
      "@codemirror/legacy-modes" in build and "langs-entry.js" in build
      and '--outfile="$OUT/langs.js"' in build)
check("A3 filetypes.js imports the seven Lezer languages AND the stream parsers",
      'from "./vendor/codemirror.js"' in ft and 'from "./vendor/langs.js"' in ft
      and "StreamLanguage.define(" in ft and "StreamLanguage.of(" not in ft
      and all(k in ft for k in ("export const EXT_LANG", "export function langExt",
                                "export function viewerFor", "export function langOf",
                                "export function extOf", "export const IMG_EXT")))
check("A4 the extension table covers the operator's 'other extension files'",
      all(s in ft for s in ('rs: "rust"', 'go: "go"', 'sql: "sql"', 'sh: "shell"',
                            'toml: "toml"', 'xml: "xml"', 'java: "java"',
                            'cpp: "cpp"', 'c: "c"', 'rb: "ruby"', 'ps1: "powershell"',
                            'hs: "haskell"', 'jl: "julia"', 'tex: "stex"', 'tex:')))
check("A5 langExt maps every family it names to a real extension",
      all('case "%s":' % k in ft for k in (
          "rust", "go", "sql", "shell", "toml", "xml", "java", "cpp", "c",
          "ruby", "powershell", "haskell", "julia", "stex", "dockerfile", "diff")))
check("A6 the editor consumes the shared table instead of owning a second copy",
      'from "./filetypes.js"' in ed and "LANG_BY_EXT" not in ed
      and "function viewerFor(" not in ed and "function langExt(" not in ed)

# --- B: the read-only viewer ------------------------------------------------
check("B1 viewer.js mounts CodeMirror, not a second highlighter",
      all(s in vw for s in ("EditorView", "EditorState", "oneDark", "lineNumbers",
                            "searchKeymap", "foldGutter")))
check("B2 it is read-only and non-editable (a preview is not an editor)",
      "EditorState.readOnly.of(true)" in vw and "EditorView.editable.of(false)" in vw)
check("B3 long lines wrap and the language comes from the path",
      "EditorView.lineWrapping" in vw and "langExt(langOf(path))" in vw)
check("B4 the module API is published for the classic page script",
      "window.LRViewer = { show, clear, langOf }" in vw)
check("B5 index.html loads it as a module next to the editor",
      '<script type="module" src="/assets/viewer.js"></script>' in ui)
check("B6 the source view calls it and keeps a TEXT fallback",
      "window.LRViewer.show(wrap, r.text || \"\", _pv.path);" in ui
      and 'pre.textContent = r.text || "";' in ui
      and "wrap.appendChild(pre);" in ui)

# --- C: expandable window + per-type views ----------------------------------
check("C1 the window has the ⤢ control with its state on the control",
      'id="pvSize"' in ui and 'aria-label="expand the preview"' in ui
      and 'aria-pressed="false"' in ui and 'const pz = $("pvSize");' in ui)
check("C2 full screen is one persisted state (sf_pv_full + .pv-full)",
      'const LS_PV_FULL = "sf_pv_full";' in ui and "#pvWin.pv-full" in ui
      and "w.classList.toggle(\"pv-full\", on);" in ui)
check("C3 the window is resizable in between, never in full screen",
      "resize: both;" in ui and "resize: none; }" in ui
      and "min-width: calc(420px / var(--zoom, 1));" in ui)
check("C4 the view switch is a named segmented control",
      'id="pvViews" role="group" aria-label="preview view"' in ui
      and 'aria-pressed="' in ui and "function _pvPaintViews()" in ui)
check("C5 only the views a file really has (render/source, table/source)",
      'if (kind === "markdown" || kind === "html") return ["render", "source"];' in ui
      and 'if (kind === "csv") return ["table", "source"];' in ui
      and "if (views.length < 2)" in ui)
check("C6 clicking a view re-renders (a different view is a different answer)",
      "_pv.view = b.dataset.view;" in ui and "renderPreview();" in ui
      and 'const PV_VIEW_LABEL = { render: "Preview", source: "Source", table: "Table" };' in ui)
check("C7 HTML keeps the sandboxed frame in Preview and the source in Source",
      'if (_pv.view === "source") return _pvRenderText(body, note);' in ui
      and 'f.setAttribute("sandbox", "allow-scripts allow-popups")' in ui)
check("C8 markdown renders through the sanitizer and now HAS typography",
      "d.innerHTML = mdToHtml(r.text || \"\");" in ui
      and ".pv-md h1" in ui and ".pv-md pre" in ui and ".pv-md table" in ui
      and ".pv-md blockquote" in ui)
check("C9 the code host fills the window and scrolls inside the editor",
      ".pv-code .cm-editor { height: 100%; }" in ui
      and ".pv-code .cm-scroller { overscroll-behavior: contain; }" in ui)
check("C10 CSV/TSV open as a TABLE first, with quoted cells and a cap",
      "function _pvCsvRows(text, delim)" in ui and "s[i + 1] === '\"'" in ui
      and "rows.length >= 500" in ui and "function _pvRenderCsv(body, note)" in ui
      and 'table.className = "pv-table";' in ui)
check("C11 SVG is TEXT (XML), so the window never asks the raw route for it",
      '".svg"' in ui and ui.index('if (_pvIsText(path)) return "text";')
      < ui.index('const k = String((row && row.kind) || "");'))
check("C12 the ⋯ source toggle drives the SAME view state",
      'label: _pv.view === "source" ? "Show the rendered view" : "Show the source"' in ui
      and '_pv.view = _pv.view === "source" ? "render" : "source";' in ui)
check("C13 closing the window destroys the editor view (no leaked CodeMirror)",
      "if (window.LRViewer) window.LRViewer.clear();" in ui
      and "if (window.LRViewer) window.LRViewer.clear();" in ui.split("function closePreview()")[1][:300])

print("---")
passed = sum(RESULTS)
print("v1011: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
