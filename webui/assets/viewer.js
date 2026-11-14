/* Longrun WebUI — read-only code view for the preview window (v1011).
   Operator: *"the code is predisplayed … doesn't exist standard way to display
   each file type?"* The answer is NOT a second highlighter: the preview mounts the
   SAME CodeMirror 6 engine, the SAME extension→language table (filetypes.js) and
   the SAME oneDark theme as the editor dock — one vocabulary, two hosts. Read-only
   (no edits, no save), with line numbers, folding, wrapping and Mod-F search.

   index.html is a classic script, so this module publishes one small API on
   `window.LRViewer`; a missing module falls back to the plain `<pre>` in the page. */
import {
  EditorState, EditorView, lineNumbers, highlightSpecialChars, drawSelection,
  keymap, defaultKeymap, searchKeymap, foldGutter, foldKeymap,
  syntaxHighlighting, defaultHighlightStyle, bracketMatching, oneDark,
} from "./vendor/codemirror.js";
import { langExt, langOf } from "./filetypes.js";

let _view = null;

/* One theme for the window: CodeMirror paints its own background, so the host is
   transparent and the code sits on the preview's surface. */
const PV_THEME = EditorView.theme({
  "&": { height: "100%", background: "transparent", fontSize: "12px" },
  ".cm-scroller": {
    overflow: "auto",
    fontFamily: "var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
    lineHeight: "1.55",
  },
  ".cm-content": { padding: "8px 0 18px" },
  ".cm-gutters": { background: "transparent", border: "0", color: "var(--dim)" },
});

function clear() {
  if (_view) { _view.destroy(); _view = null; }
}

/* Mount `text` into `el`. The language is chosen from the PATH, never from the
   file's contents, so the same file is painted the same way in both hosts. */
function show(el, text, path) {
  clear();
  if (!el) return null;
  const exts = [
    lineNumbers(), highlightSpecialChars(), drawSelection(), bracketMatching(),
    foldGutter(),
    keymap.of([...defaultKeymap, ...searchKeymap, ...foldKeymap]),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    EditorView.lineWrapping,
    EditorState.readOnly.of(true),
    EditorView.editable.of(false),
    oneDark, PV_THEME,
  ];
  const lang = langExt(langOf(path));
  if (lang) exts.push(lang);
  _view = new EditorView({
    parent: el,
    state: EditorState.create({ doc: String(text == null ? "" : text), extensions: exts }),
  });
  return _view;
}

window.LRViewer = { show, clear, langOf };
