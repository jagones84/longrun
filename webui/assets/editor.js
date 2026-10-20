/* Longrun WebUI — Editor dock (JAG-150).
   Right-side resizable dock, one tab per file. CodeMirror 6 for code, plus
   per-type previews (markdown / image / pdf / html). Vendored libs only. */
import {
  EditorState, Compartment, EditorView, keymap, lineNumbers,
  highlightActiveLine, highlightActiveLineGutter, drawSelection, dropCursor,
  rectangularSelection, crosshairCursor, highlightSpecialChars,
  defaultKeymap, history, historyKeymap, indentWithTab,
  syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput,
  foldGutter, foldKeymap, searchKeymap, highlightSelectionMatches,
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
  javascript, python, json, markdown, html, css, yaml, oneDark,
} from "./vendor/codemirror.js";

const TOKEN = () => localStorage.getItem("sf_token") || "";
/* JAG-299: the file tree is session-scoped (?session=), but read/write/raw were
   NOT — so the editor opened/saved against the DEFAULT workspace instead of the
   session's, and could even be refused a file the tree had just listed. Scope
   every fs call the same way the tree already does. */
const SESSION = () => localStorage.getItem("sf_session") || "";
const sessionQS = () => { const s = SESSION(); return s ? ("&session=" + encodeURIComponent(s)) : ""; };
const LS_W = "sf_ed_w";
const LS_TREE_W = "sf_ed_tree_w";    // JAG-252: width of the file-tree pane
const LS_TABS = "sf_ed_tabs";        // legacy/global tab set (no session)
const LS_TABS_S = "sf_ed_tabs_";     // JAG-157: per-session tab set
const LS_OPEN = "sf_dock_open";      // JAG-157: "false" = the user closed the dock
const LS_MODE = "sf_ed_mode";        // JAG-453: "dock" (default) | "float" | "full"
const LS_POS = "sf_ed_pos";          // JAG-453: floating window geometry {left,top,w,h}
const IMG_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "bmp", "avif"]);
const LANG_BY_EXT = {
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
  ts: "javascript", tsx: "javascript", py: "python", json: "json",
  md: "markdown", markdown: "markdown", html: "html", htm: "html",
  css: "css", scss: "css", yml: "yaml", yaml: "yaml",
};

const $id = (id) => document.getElementById(id);
function authHeaders() { const t = TOKEN(); return t ? { Authorization: "Bearer " + t } : {}; }
async function jget(url) { const r = await fetch(url, { headers: authHeaders() }); return r.json(); }
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
    body: JSON.stringify(body),
  });
  return r.json();
}

function extOf(p) { const m = /\.([a-z0-9]+)$/i.exec(p || ""); return m ? m[1].toLowerCase() : ""; }
function viewerFor(p) {
  const e = extOf(p);
  if (IMG_EXT.has(e)) return "image";
  if (e === "pdf") return "pdf";
  if (e === "md" || e === "markdown") return "markdown";
  if (e === "html" || e === "htm") return "html";
  return "code";
}
function langOf(p) { return LANG_BY_EXT[extOf(p)] || null; }
function langExt(name) {
  switch (name) {
    case "javascript": return javascript();
    case "python": return python();
    case "json": return json();
    case "markdown": return markdown();
    case "html": return html();
    case "css": return css();
    case "yaml": return yaml();
    default: return null;
  }
}
function basename(p) { const i = String(p).lastIndexOf("/"); return i >= 0 ? p.slice(i + 1) : String(p); }
function sessId() { return localStorage.getItem("sf_session") || ""; }
function tabsKey() { const s = sessId(); return s ? (LS_TABS_S + s) : LS_TABS; }
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

class EditorHost {
  constructor(parent) { this.parent = parent; this.view = null; this.lang = new Compartment(); this.ro = new Compartment(); }
  mount(doc, langName, readOnly, onUpdate) {
    this.destroy();
    const exts = [
      lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(), history(),
      drawSelection(), dropCursor(), EditorState.allowMultipleSelections.of(true),
      indentOnInput(), syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      bracketMatching(), closeBrackets(), autocompletion(),
      rectangularSelection(), crosshairCursor(), highlightActiveLine(), highlightSelectionMatches(),
      foldGutter(),
      keymap.of([{ key: "Mod-s", run: () => { save(); return true; } },
        ...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap,
        ...foldKeymap, ...completionKeymap, indentWithTab]),
      oneDark,
      this.lang.of(langExt(langName) || []),
      this.ro.of(EditorState.readOnly.of(!!readOnly)),
    ];
    if (onUpdate) exts.push(EditorView.updateListener.of(onUpdate));
    this.view = new EditorView({ parent: this.parent, state: EditorState.create({ doc: doc || "", extensions: exts }) });
  }
  value() { return this.view ? this.view.state.doc.toString() : ""; }
  setValue(v) { if (this.view) this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: v || "" } }); }
  setLanguage(n) { if (this.view) this.view.dispatch({ effects: this.lang.reconfigure(langExt(n) || []) }); }
  setReadOnly(ro) { if (this.view) this.view.dispatch({ effects: this.ro.reconfigure(EditorState.readOnly.of(!!ro)) }); }
  focus() { if (this.view) this.view.focus(); }
  destroy() { if (this.view) { this.view.destroy(); this.view = null; } }
}

const state = { tabs: [], active: -1, host: null, preview: null, tabsEl: null, statusEl: null, toggleBtn: null, resizeEl: null, dock: null, root: "",
  mode: "dock", floatReady: false };   // JAG-453: window mode dock|float|full

const STYLE = `
#editorDock{position:relative;flex:0 0 auto;min-height:0;background:var(--bg2,#0f1320);
  border-left:1px solid var(--line,#26304a);display:flex;flex-direction:column;z-index:5;font-size:12px}
#editorDock[hidden]{display:none}
#editorDock .ed-resize{position:absolute;left:-3px;top:0;bottom:0;width:6px;cursor:col-resize;z-index:6;touch-action:none}
#editorDock .ed-head{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid var(--line,#26304a)}
#editorDock .ed-title{font-weight:600}
#editorDock .ed-status{flex:1;opacity:.7;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#editorDock .ed-tabs{display:flex;gap:4px;overflow-x:auto;padding:6px 8px;border-bottom:1px solid var(--line,#26304a)}
#editorDock .ed-tab{display:flex;gap:6px;align-items:center;padding:3px 8px;border:1px solid var(--line,#26304a);border-radius:6px;cursor:pointer;white-space:nowrap;font-family:monospace;font-size:11px}
#editorDock .ed-tab.active{border-color:var(--accent,#8b7bf0);background:rgba(139,123,240,.14)}
#editorDock .ed-tab .dirty{color:var(--warn,#e0b341)}
#editorDock .ed-tab .x{opacity:.55}
#editorDock .ed-body{flex:1;min-height:0;display:flex;flex-direction:row}
#editorDock .ed-tree{width:210px;flex:0 0 auto;overflow:auto;border-right:1px solid var(--line,#26304a);padding:6px;font-family:monospace;font-size:11px}
#editorDock .ed-tree[hidden]{display:none}
#editorDock .ed-tree-resize{flex:0 0 5px;width:5px;cursor:col-resize;background:transparent;touch-action:none}
#editorDock .ed-tree-resize:hover,#editorDock .ed-tree-resize.active{background:var(--accent,#8b7bf0)}
#editorDock .ed-tree[hidden]+.ed-tree-resize{display:none}
/* JAG-3xx: on TOUCH a 5px grip is impossible to hit and the 210px default tree eats
   most of the dock, so widen both grips and give the tree less room by default. */
@media (pointer:coarse){
#editorDock .ed-resize{width:14px;left:-7px}
#editorDock .ed-tree-resize{flex:0 0 14px;width:14px}
#editorDock .ed-tree{width:150px}
}
#editorDock .ed-main{flex:1;min-width:0;display:flex;flex-direction:column}
#editorDock .ed-trow{cursor:pointer;padding:2px 4px;border-radius:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#editorDock .ed-trow:hover{background:rgba(108,140,255,.12)}
#editorDock .ed-trow.active{background:rgba(139,123,240,.18)}
#editorDock .ed-host{flex:1;min-height:0;overflow:auto}
#editorDock .ed-host.hidden{display:none}
#editorDock .ed-preview{flex:1;min-height:0;overflow:auto;padding:12px;line-height:1.5}
#editorDock .ed-preview[hidden]{display:none}
#editorDock .ed-preview img{max-width:100%}
#editorDock .ed-preview iframe{width:100%;height:100%;border:0;background:#fff}
#editorDock .ed-preview .md h1,#editorDock .ed-preview .md h2{border-bottom:1px solid var(--line,#26304a);padding-bottom:4px}
#editorDock .ed-preview .md h1{color:#9db4ff}#editorDock .ed-preview .md h2{color:#a9e0c0}
#editorDock .ed-preview .md h3{color:#e0b341}
#editorDock .ed-preview .md code{background:rgba(255,255,255,.07);padding:1px 4px;border-radius:4px}
#editorDock .ed-preview .md pre{background:rgba(255,255,255,.05);padding:8px;border-radius:6px;overflow:auto}
#editorDock .ed-preview .md a{color:#7fb0ff}
#editorDock .ed-foot{display:flex;gap:6px;padding:8px 10px;border-top:1px solid var(--line,#26304a)}
#editorDock.ed-overlay{position:fixed;top:44px;right:0;bottom:0;height:auto;width:min(520px,92vw);z-index:40;box-shadow:-16px 0 40px rgba(0,0,0,.45)}
/* JAG-453: detachable editor — DOCK (default) ⇄ FLOAT ⇄ FULL. A Windows-style
   title bar: drag it to move (float), re-attach / fullscreen / close on the right
   (close turns red on hover), and a bottom-right grip to resize. */
#editorDock.ed-float{position:fixed;z-index:44;width:min(780px,92vw);height:min(640px,82vh);
  border:1px solid var(--line,#26304a);border-radius:10px;overflow:hidden;
  box-shadow:0 24px 60px rgba(0,0,0,.55)}
#editorDock.ed-full{position:fixed;z-index:44;left:0;top:0;right:0;bottom:0;width:auto;height:auto;
  border:0;border-radius:0;box-shadow:none}
#editorDock.ed-float .ed-resize,#editorDock.ed-full .ed-resize{display:none}
#editorDock.ed-float .ed-head{cursor:move;user-select:none}
#editorDock .ed-win{display:flex;align-items:center;gap:2px;margin-left:6px}
#editorDock .ed-wbtn{background:transparent;border:0;color:var(--txt,#e6edf7);width:26px;height:22px;border-radius:5px;
  cursor:pointer;font:inherit;font-size:12px;line-height:1;display:inline-flex;align-items:center;justify-content:center;padding:0}
#editorDock .ed-wbtn:hover{background:rgba(255,255,255,.13)}
#editorDock .ed-wbtn[hidden]{display:none}
#editorDock .ed-wbtn.ed-x:hover{background:#e81123;color:#fff}
#editorDock .ed-grip{position:absolute;right:0;bottom:0;width:18px;height:18px;z-index:7;display:none;
  cursor:nwse-resize;touch-action:none;
  background:linear-gradient(135deg,transparent 52%,rgba(255,255,255,.30) 52%,rgba(255,255,255,.30) 62%,transparent 62%,
    transparent 74%,rgba(255,255,255,.30) 74%,rgba(255,255,255,.30) 84%,transparent 84%)}
#editorDock.ed-float .ed-grip{display:block}
.ed-tab-note{color:var(--warn,#e0b341)}
#editorDock.ed-drop{outline:2px dashed var(--accent,#8b7bf0);outline-offset:-4px}
#edCtx{position:fixed;z-index:60;background:var(--toolbar-menu-bg,#0f172a);border:1px solid var(--line,#26304a);
  border-radius:.5rem;padding:4px;box-shadow:0 10px 30px rgba(0,0,0,.5);font-size:12px;min-width:160px}
#edCtx button{display:block;width:100%;text-align:left;background:transparent;border:0;color:var(--txt,#e6edf7);
  padding:6px 10px;border-radius:.35rem;cursor:pointer;font:inherit;font-size:12px}
#edCtx button:hover{background:rgba(108,140,255,.16)}
.ed-tab .tmp{color:var(--accent,#8b7bf0)}
.ed-tab.ext{border-style:dashed}
.ed-tab .ext-i{color:var(--warn,#e0b341);font-size:10px}
.ed-trow.flash{outline:1px solid var(--accent,#8b7bf0);background:rgba(139,123,240,.2)}
`;

function buildDock() {
  if ($id("editorDock")) return;
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);

  const dock = document.createElement("aside");
  dock.id = "editorDock";
  dock.hidden = true;
  dock.innerHTML = `
    <div class="ed-resize"></div>
    <div class="ed-grip" title="drag to resize"></div>
    <div class="ed-head"><span class="ed-title">Editor</span><span class="ed-status"></span>
      <button class="ed-files ghost" title="show/hide the file tree">🗂 files</button>
      <button class="ed-refresh ghost" title="reload the tree">↻</button>
      <span class="ed-win">
        <button class="ed-wbtn ed-winfloat" title="detach — open as a floating window">⇱</button>
        <button class="ed-wbtn ed-winmax" title="fullscreen — fill the browser" hidden>⛶</button>
        <button class="ed-wbtn ed-x" title="close (Esc)">✕</button>
      </span></div>
    <div class="ed-body">
      <div class="ed-tree"></div>
      <div class="ed-tree-resize" title="drag to resize the file tree"></div>
      <div class="ed-main">
        <div class="ed-tabs"></div>
        <div class="ed-host"></div>
        <div class="ed-preview" hidden></div>
      </div>
    </div>
    <div class="ed-foot">
      <button class="ghost ed-save">save</button>
      <button class="ghost ed-revert">revert</button>
      <button class="ghost ed-toggle" hidden>render</button>
    </div>`;
  const anchor = $id("resize-right") || $id("rail");
  if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(dock, anchor);
  else document.body.appendChild(dock);
  state.dock = dock;
  state.tabsEl = dock.querySelector(".ed-tabs");
  state.statusEl = dock.querySelector(".ed-status");
  state.host = new EditorHost(dock.querySelector(".ed-host"));
  state.preview = dock.querySelector(".ed-preview");
  state.toggleBtn = dock.querySelector(".ed-toggle");
  state.resizeEl = dock.querySelector(".ed-resize");
  state.mode = localStorage.getItem(LS_MODE) || "dock";
  state.floatReady = false;
  dock.classList.toggle("ed-float", state.mode === "float");
  dock.classList.toggle("ed-full", state.mode === "full");
  dock.querySelector(".ed-x").onclick = close;
  // JAG-453: detach ⇄ re-attach, and fullscreen (fills the BROWSER, not the screen).
  dock.querySelector(".ed-winfloat").onclick = () => _setMode(state.mode === "dock" ? "float" : "dock");
  dock.querySelector(".ed-winmax").onclick = () => _setMode(state.mode === "full" ? "float" : "full");
  _syncWinButtons();
  dock.querySelector(".ed-save").onclick = save;
  dock.querySelector(".ed-revert").onclick = revert;
  state.toggleBtn.onclick = toggleRender;
  state.treeEl = dock.querySelector(".ed-tree");
  state.treeEl.hidden = localStorage.getItem("sf_ed_tree") === "0";
  dock.querySelector(".ed-files").onclick = () => {
    const t = state.treeEl;
    t.hidden = !t.hidden;
    localStorage.setItem("sf_ed_tree", t.hidden ? "0" : "1");
    if (!t.hidden && !t.childElementCount) loadTree();
  };
  dock.querySelector(".ed-refresh").onclick = () => refreshAll();

  // JAG-159: drop a file from the OS into the dock -> open it as a temp tab.
  dock.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; dock.classList.add("ed-drop"); });
  dock.addEventListener("dragleave", (e) => { if (!dock.contains(e.relatedTarget)) dock.classList.remove("ed-drop"); });
  dock.addEventListener("drop", (e) => { e.preventDefault(); dock.classList.remove("ed-drop"); handleDrop(e.dataTransfer && e.dataTransfer.files); });
  // JAG-159: close the right-click menu on any outside click / Escape.
  document.addEventListener("click", (e) => { if (!$id("edCtx")) return; if (!(e.target.closest && e.target.closest("#edCtx"))) hideTreeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTreeMenu(); });

  // JAG-453: the docked width is applied by applyResponsive() (which routes by mode),
  // so it is NOT set here — an inline width would shadow the float/full geometry.
  // JAG-3xx: POINTER events, not mouse — a phone/tablet only fires pointerdown/move/up,
  // so the old mousedown drag made the grip dead on touch (the dock width could not be
  // changed at all on a mobile device).
  let dragging = false;
  const _dockMove = (e) => {
    if (!dragging) return;
    // JAG-369: never let the dock grow so wide that it shoves the inspector off-screen.
    // The app owns the panel widths + the chat floor and exports the cap; the drag is
    // bounded by it (and by the viewport) so the inspector stays put. Only the arrows
    // may hide a panel — a resize must not.
    const z = (typeof window._pageScale === "function") ? window._pageScale() : 1;
    const right = dock.getBoundingClientRect().right;
    const cap = Math.min(_vw() - 120, _dockMaxW());
    const w = Math.min(cap, Math.max(240, (right - e.clientX) / z));
    dock.style.width = w + "px";
    localStorage.setItem(LS_W, String(Math.round(w)));
  };
  const _dockUp = () => {
    if (!dragging) return;
    dragging = false;
    state.resizeEl.classList.remove("active");
    _notifyLayout();
  };
  state.resizeEl.addEventListener("pointerdown", (e) => {
    dragging = true;
    state.resizeEl.classList.add("active");
    try { state.resizeEl.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  });
  state.resizeEl.addEventListener("pointermove", _dockMove);
  state.resizeEl.addEventListener("pointerup", _dockUp);
  state.resizeEl.addEventListener("pointercancel", _dockUp);

  // JAG-252: drag the splitter between the file tree and the editor to give more
  // room to the file being read. Width is remembered per browser.
  const savedTree = parseInt(localStorage.getItem(LS_TREE_W) || "", 10);
  if (savedTree) state.treeEl.style.width = savedTree + "px";
  const treeResize = dock.querySelector(".ed-tree-resize");
  // JAG-3xx: pointer events so the splitter also works by touch — a finger never
  // produces the mousedown/mousemove pair the old code waited for, so on a phone the
  // file-tree pane could not be shrunk at all (it stayed at its 210px default).
  let treeDragging = false;
  const _treeMove = (e) => {
    if (!treeDragging) return;
    const left = state.treeEl.getBoundingClientRect().left;
    const w = Math.min(_vw() - 160, Math.max(70, e.clientX - left));
    state.treeEl.style.width = w + "px";
    localStorage.setItem(LS_TREE_W, String(w));
  };
  const _treeUp = () => {
    if (!treeDragging) return;
    treeDragging = false;
    treeResize.classList.remove("active");
  };
  treeResize.addEventListener("pointerdown", (e) => {
    treeDragging = true;
    treeResize.classList.add("active");
    try { treeResize.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  });
  treeResize.addEventListener("pointermove", _treeMove);
  treeResize.addEventListener("pointerup", _treeUp);
  treeResize.addEventListener("pointercancel", _treeUp);

  // JAG-453: in FLOAT mode the title bar drags the window and the bottom-right grip
  // resizes it; both persist to LS_POS so the window reopens where it was left.
  const head = dock.querySelector(".ed-head");
  const grip = dock.querySelector(".ed-grip");
  let winDrag = null, winResize = null;
  head.addEventListener("pointerdown", (e) => {
    if (state.mode !== "float") return;
    if (e.target.closest && e.target.closest("button")) return;
    const r = dock.getBoundingClientRect();
    winDrag = { x: e.clientX, y: e.clientY, left: r.left, top: r.top };
    try { head.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  });
  head.addEventListener("pointermove", (e) => {
    if (!winDrag) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = Math.min(Math.max(0, winDrag.left + (e.clientX - winDrag.x)), Math.max(0, vw - dock.offsetWidth));
    const top = Math.min(Math.max(0, winDrag.top + (e.clientY - winDrag.y)), Math.max(0, vh - 32));
    dock.style.left = left + "px"; dock.style.top = top + "px";
  });
  const _winUp = () => { if (winDrag) { winDrag = null; _saveFloatPos(); } };
  head.addEventListener("pointerup", _winUp);
  head.addEventListener("pointercancel", _winUp);
  grip.addEventListener("pointerdown", (e) => {
    if (state.mode !== "float") return;
    winResize = { x: e.clientX, y: e.clientY, w: dock.offsetWidth, h: dock.offsetHeight };
    try { grip.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault(); e.stopPropagation();
  });
  grip.addEventListener("pointermove", (e) => {
    if (!winResize) return;
    dock.style.width = Math.max(320, winResize.w + (e.clientX - winResize.x)) + "px";
    dock.style.height = Math.max(220, winResize.h + (e.clientY - winResize.y)) + "px";
  });
  const _gripUp = () => { if (winResize) { winResize = null; _saveFloatPos(); } };
  grip.addEventListener("pointerup", _gripUp);
  grip.addEventListener("pointercancel", _gripUp);

  window.addEventListener("resize", applyResponsive);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || dock.hidden) return;
    const modal = document.querySelector("#diffView:not([hidden]), #skillView:not([hidden])");
    if (modal) return;
    // JAG-453: Escape in FULL leaves fullscreen (back to float) — it does not close
    // the editor, which would be a surprising way to lose a maximised window.
    if (state.mode === "full") { _setMode("float"); return; }
    close();
  });
}

/* JAG-366: the LAYOUT viewport (clientWidth) — what the CSS media queries use — so
   the dock's overlay decision matches the real layout even when window.innerWidth
   is stale (device emulation / visual viewport / zoom). */
function _vw() { return document.documentElement.clientWidth || window.innerWidth; }
/* JAG-369: the widest the dock may be without shoving the inspector (#rail) off-screen.
   The app owns the panel widths and the chat floor, so it exports window._dockMaxW; fall
   back to a plain viewport bound only if it is missing (should never happen). */
function _dockMaxW() { return (typeof window._dockMaxW === "function") ? window._dockMaxW() : (_vw() - 120); }
/* JAG-3xx: the visible header height — a fixed overlay must start BELOW it. */
function _headerH() {
  const h = document.querySelector("header");
  const r = h && h.getBoundingClientRect();
  return (r && r.height > 0) ? Math.round(r.height) : 44;
}
/* JAG-3xx: how many px the bottom chrome (chat composer + mobile tab bar) occupies, so
   a fixed overlay can stop ABOVE it instead of covering buttons the user needs. */
function _bottomChromeH() {
  const vh = window.innerHeight || document.documentElement.clientHeight;
  let top = vh;
  for (const sel of ["#composer", "#tabbar"]) {
    const el = document.querySelector(sel);
    if (!el || getComputedStyle(el).display === "none") continue;
    const r = el.getBoundingClientRect();
    if (r.height > 0 && r.top < top) top = r.top;
  }
  const h = Math.round(vh - top);
  return (h > 0 && h < vh) ? h : 0;
}
function applyResponsive() {
  if (!state.dock) return;
  const d = state.dock;
  // JAG-453: geometry depends on the window mode. FLOAT/FULL take the dock OUT of the
  // flex row entirely (position:fixed), so the docked overlay/width rules must not run.
  if (state.mode !== "dock") {
    d.classList.remove("ed-overlay");
    if (state.mode === "full") {
      d.style.left = "0"; d.style.top = "0"; d.style.right = "0"; d.style.bottom = "0";
      d.style.width = ""; d.style.height = "";
      return;
    }
    if (!state.floatReady) { _applyFloatGeom(); state.floatReady = true; }
    else if (!d.hidden) _clampFloat();
    return;
  }
  state.floatReady = false;
  const overlay = _vw() < 1024;
  d.classList.toggle("ed-overlay", overlay);
  const saved = parseInt(localStorage.getItem(LS_W) || "420", 10);
  if (overlay) {
    // JAG-3xx: the fixed overlay ran top:44px -> bottom:0, so on a phone it covered
    // the chat composer (send) AND the whole bottom tab bar — those buttons looked
    // DEAD because the dock received every tap. Keep the dock between the real header
    // and the bottom chrome so both stay visible and tappable.
    // JAG-453: clear any float/full inline geometry so it cannot fight the CSS overlay.
    d.style.left = ""; d.style.right = ""; d.style.height = "";
    d.style.top = _headerH() + "px";
    d.style.bottom = _bottomChromeH() + "px";
    d.style.width = "";
  } else {
    d.style.top = ""; d.style.bottom = ""; d.style.left = ""; d.style.right = ""; d.style.height = "";
    d.style.width = Math.min(saved, _dockMaxW()) + "px";
  }
}

/* JAG-453: switch the editor between DOCK (default, in the app row), FLOAT (a movable,
   resizable window over the app) and FULL (fills the whole BROWSER viewport — not the
   OS screen, so the browser chrome stays). */
function _setMode(m) {
  const d = state.dock; if (!d) return;
  state.mode = m;
  localStorage.setItem(LS_MODE, m);
  d.style.cssText = "";                       // drop any previous mode's geometry
  d.classList.toggle("ed-float", m === "float");
  d.classList.toggle("ed-full", m === "full");
  d.classList.remove("ed-overlay");
  state.floatReady = false;
  _syncWinButtons();
  applyResponsive();
  _notifyLayout();
  // the dock/float/full switch changes the editor's box — let CodeMirror re-measure.
  if (state.host && state.host.view) state.host.view.requestMeasure();
}
/* The small Windows-style controls: the left one detaches / re-attaches, the middle
   one toggles fullscreen, the right one closes. */
function _syncWinButtons() {
  const d = state.dock; if (!d) return;
  const fb = d.querySelector(".ed-winfloat"), mb = d.querySelector(".ed-winmax");
  if (fb) {
    fb.textContent = state.mode === "dock" ? "⇱" : "⇲";
    fb.title = state.mode === "dock"
      ? "detach — open the editor as a floating window"
      : "re-attach to the WebUI (docked)";
  }
  if (mb) {
    mb.hidden = state.mode === "dock";
    mb.textContent = state.mode === "full" ? "❐" : "⛶";
    mb.title = state.mode === "full"
      ? "exit fullscreen (back to the floating window)"
      : "fullscreen — fill the browser";
  }
}
/* FLOAT geometry: restore the last saved position/size, else centre it under the header. */
function _applyFloatGeom() {
  const d = state.dock;
  let p = null;
  try { p = JSON.parse(localStorage.getItem(LS_POS) || "null"); } catch (e) { p = null; }
  const vw = window.innerWidth, vh = window.innerHeight;
  const w = Math.max(320, Math.min((p && p.w) || Math.min(780, Math.round(vw * 0.72)), vw - 16));
  const h = Math.max(220, Math.min((p && p.h) || Math.min(640, Math.round(vh * 0.82)), vh - 16));
  const left = (p && typeof p.left === "number") ? p.left : Math.round((vw - w) / 2);
  const top = (p && typeof p.top === "number") ? p.top : Math.round(_headerH() + 14);
  d.style.width = w + "px"; d.style.height = h + "px";
  d.style.left = left + "px"; d.style.top = top + "px";
  d.style.right = "auto"; d.style.bottom = "auto";
  if (!d.hidden) _clampFloat();
}
/* Keep a floating window on-screen (never fully above the top / off to the right). */
function _clampFloat() {
  const d = state.dock; if (!d) return;
  const r = d.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const left = Math.max(0, Math.min(r.left, vw - Math.max(80, r.width)));
  const top = Math.max(0, Math.min(r.top, vh - 32));
  d.style.left = left + "px"; d.style.top = top + "px";
}
function _saveFloatPos() {
  const d = state.dock;
  if (!d || state.mode !== "float") return;
  const r = d.getBoundingClientRect();
  try {
    localStorage.setItem(LS_POS, JSON.stringify({
      left: Math.round(r.left), top: Math.round(r.top),
      w: Math.round(r.width), h: Math.round(r.height),
    }));
  } catch (e) { /* ignore */ }
}

function activeTab() { return state.tabs[state.active] || null; }
function setStatus(m) { if (state.statusEl) state.statusEl.textContent = m || ""; }
function isCodeMode(t) { return t && (t.viewer === "code" || (t.viewer === "markdown" && t.mode === "code")); }

function syncActive() {
  const t = activeTab();
  if (t && isCodeMode(t) && state.host.view) {
    t.value = state.host.value();
    t.dirty = t.value !== t.saved;
  }
}

async function loadTree() {
  const box = state.treeEl;
  if (!box) return;
  box.innerHTML = '<div class="remaining">loading…</div>';
  const sid = localStorage.getItem("sf_session") || "";
  try {
    const d = await jget("/api/fs/list?session=" + encodeURIComponent(sid));
    if (d.error) { box.innerHTML = '<div class="remaining">' + esc(d.error) + "</div>"; return; }
    state.root = d.root || "";
    box.innerHTML = "";
    const root = document.createElement("div");
    root.className = "remaining";
    root.style.marginBottom = "4px";
    root.textContent = (d.root ? basename(d.root) : "workspace") + "/";
    box.appendChild(root);
    renderTree(box, d, 0);
    if (!d.count) box.insertAdjacentHTML("beforeend", '<div class="remaining">empty folder</div>');
  } catch (e) { box.innerHTML = '<div class="remaining">' + esc(e) + "</div>"; }
}

function renderTree(container, d, depth) {
  (d.dirs || []).forEach((dir) => {
    const row = document.createElement("div");
    row.className = "ed-trow";
    row.style.paddingLeft = (4 + depth * 12) + "px";
    row.textContent = "▸ 📁 " + dir.name;
    const kids = document.createElement("div");
    kids.hidden = true;
    let loaded = false;
    row.onclick = async () => {
      kids.hidden = !kids.hidden;
      row.textContent = (kids.hidden ? "▸" : "▾") + " 📁 " + dir.name;
      if (!kids.hidden && !loaded) {
        loaded = true;
        const sid = localStorage.getItem("sf_session") || "";
        try {
          const sub = await jget("/api/fs/list?session=" + encodeURIComponent(sid) + "&path=" + encodeURIComponent(dir.path));
          if (sub.error) kids.innerHTML = '<div class="remaining" style="padding-left:' + (16 + depth * 12) + 'px">' + esc(sub.error) + "</div>";
          else renderTree(kids, sub, depth + 1);
        } catch (e) { /* ignore */ }
      }
    };
    container.appendChild(row);
    container.appendChild(kids);
  });
  (d.files || []).forEach((f) => {
    const row = document.createElement("div");
    row.className = "ed-trow";
    row.style.paddingLeft = (16 + depth * 12) + "px";
    row.textContent = "📄 " + f.name;
    row.title = f.path;
    row.onclick = () => open(f.path);
    row.oncontextmenu = (e) => { e.preventDefault(); showTreeMenu(e.clientX, e.clientY, f.path); };
    container.appendChild(row);
  });
}

function _inWorkspace(path) {
  if (!state.root) return true;                       // unknown root -> never flag
  if (String(path).startsWith("untitled://")) return true;
  const root = state.root.replace(/\/+$/, "");
  return path === root || path.startsWith(root + "/");
}
/* JAG-282: an open tab shows its full path on hover and, if it lives OUTSIDE the
   workspace, a dashed border + a ⚠ marker. Right-click = copy path (like the tree). */
function renderTabs() {
  const el = state.tabsEl; if (!el) return;
  el.innerHTML = "";
  state.tabs.forEach((t, i) => {
    const temp = !!t.temp || String(t.path).startsWith("untitled://");
    const ext = !temp && !_inWorkspace(t.path);
    const b = document.createElement("div");
    b.className = "ed-tab" + (i === state.active ? " active" : "") + (ext ? " ext" : "");
    b.title = temp ? (t.path + "\n(temp — not saved on disk)")
                   : (t.path + (ext ? "\n⚠ outside the session workspace" : ""));
    const nm = document.createElement("span"); nm.className = "nm" + (t.temp ? " tmp" : ""); nm.textContent = basename(t.path);
    b.appendChild(nm);
    if (ext) { const w = document.createElement("span"); w.className = "ext-i"; w.textContent = "⚠"; b.appendChild(w); }
    if (t.dirty) { const d = document.createElement("span"); d.className = "dirty"; d.textContent = "●"; b.appendChild(d); }
    const x = document.createElement("span"); x.className = "x"; x.textContent = "✕";
    x.onclick = (e) => { e.stopPropagation(); closeTab(i); };
    b.appendChild(x);
    // JAG-494: clicking a tab activates it AND reveals the file in the tree
    // (the reveal action moved off the context menu onto the click itself).
    b.onclick = () => { activate(i); if (!temp && _inWorkspace(t.path)) revealInTree(t.path); };
    b.oncontextmenu = (e) => { e.preventDefault(); showTabMenu(e.clientX, e.clientY, i); };
    el.appendChild(b);
  });
}

function persistTabs() {
  try {
    // temp tabs (dragged-in files) are never persisted
    const paths = state.tabs.filter((t) => !t.temp).map((t) => t.path);
    localStorage.setItem(tabsKey(), JSON.stringify({ paths, active: state.active }));
  } catch (e) { /* ignore */ }
}

function showCode(show) {
  state.dock.querySelector(".ed-host").classList.toggle("hidden", !show);
  state.preview.hidden = show;
}

function renderActive() {
  const t = activeTab();
  if (!t) return;
  const code = isCodeMode(t);
  showCode(code);
  if (code) {
    state.host.mount(t.value, t.lang, t.readonly, onDocUpdate);
    state.host.setReadOnly(t.readonly);
    state.host.focus();
  } else if (t.viewer === "markdown") {
    const raw = t.value || "";
    const htm = window.marked ? window.marked.parse(raw) : esc(raw);
    const clean = window.DOMPurify ? window.DOMPurify.sanitize(htm) : esc(raw);
    state.preview.innerHTML = '<div class="md">' + clean + "</div>";
  } else if (t.viewer === "html") {
    state.preview.innerHTML = "";
    const ifr = document.createElement("iframe");
    ifr.setAttribute("sandbox", "");
    ifr.srcdoc = t.value || "";
    state.preview.appendChild(ifr);
  } else if (t.viewer === "image" || t.viewer === "pdf") {
    state.preview.innerHTML = "";
    const url = (t.temp && t.objectUrl)
      ? t.objectUrl
      : ("/api/fs/raw?path=" + encodeURIComponent(t.path) + (TOKEN() ? "&token=" + encodeURIComponent(TOKEN()) : "") + sessionQS());
    const node = document.createElement(t.viewer === "pdf" ? "iframe" : "img");
    node.src = url;
    if (t.viewer === "pdf") node.setAttribute("style", "width:100%;height:100%;border:0");
    state.preview.appendChild(node);
  } else {
    state.preview.innerHTML = '<div class="remaining">binary file — no preview (' + esc(t.size ? t.size + " B" : "") + ")</div>";
  }

  const d = state.dock;
  d.querySelector(".ed-save").disabled = !!t.readonly;
  d.querySelector(".ed-revert").disabled = !!t.readonly;
  state.toggleBtn.hidden = t.viewer !== "markdown";
  state.toggleBtn.textContent = t.mode === "code" ? "render" : "code";
  updateStatus();
}

function updateStatus() {
  const t = activeTab();
  if (!t) { setStatus(""); return; }
  const bits = [t.path];
  if (!t.temp && !_inWorkspace(t.path)) bits.push("⚠ outside the workspace");
  if (t.readonly) bits.push("read-only");
  if (t.dirty) bits.push("● modified");
  setStatus(bits.join(" · "));
}

function onDocUpdate(u) {
  if (!u.docChanged) return;
  const t = activeTab();
  if (!t) return;
  t.value = state.host.value();
  const wasDirty = t.dirty;
  t.dirty = t.value !== t.saved;
  if (wasDirty !== t.dirty) renderTabs();
  updateStatus();
}

async function open(path, opts) {
  if (!path) return;
  buildDock();
  const wantMode = opts && opts.mode;   // JAG-395: force a viewer mode (e.g. "code" for ROLE.md)
  const existing = state.tabs.findIndex((t) => t.path === path);
  if (existing >= 0) {
    if (wantMode) state.tabs[existing].mode = wantMode;
    activate(existing);
    if (existing === state.active) renderActive();   // activate() no-ops on the already-active tab
    show();
    return;
  }
  let d;
  try { d = await jget("/api/fs/read?path=" + encodeURIComponent(path) + sessionQS()); }
  catch (e) { show(); setStatus("error: " + e); return; }
  if (!d || d.error) { show(); setStatus(d && d.error ? d.error : "read error"); return; }
  const viewer = (d.binary && viewerFor(d.path) === "code") ? "binary" : viewerFor(d.path);
  const tab = {
    path: d.path, viewer,
    lang: langOf(d.path),
    mode: wantMode || "render",
    saved: d.text || "", value: d.text || "",
    dirty: false,
    readonly: !!d.truncated || viewer === "binary",
    size: d.size,
  };
  state.tabs.push(tab);
  state.active = state.tabs.length - 1;
  renderTabs();
  renderActive();
  persistTabs();
  show();
}

function activate(i) {
  if (i === state.active) return;
  syncActive();
  state.active = i;
  renderTabs();
  renderActive();
  persistTabs();
  show();
}

function closeTab(i) {
  const t = state.tabs[i];
  if (!t) return;
  if (t.dirty && !window.confirm('Close "' + basename(t.path) + '" with unsaved changes?')) return;
  if (i === state.active) syncActive();
  if (t.temp && t.objectUrl) { try { URL.revokeObjectURL(t.objectUrl); } catch (e) { /* ignore */ } }
  state.tabs.splice(i, 1);
  if (state.tabs.length === 0) {
    // JAG-252: persist the EMPTY tab set before hiding the dock. Without this
    // the closed file stayed in localStorage and reappeared on the next open.
    state.active = -1;
    persistTabs();
    close();
    return;
  }
  // JAG-295-fix: after splicing, tabs after `i` shift down. Closing a tab that
  // sits BEFORE the active one must move the active selection left by one, or the
  // editor jumps to the wrong file.
  if (i < state.active) state.active -= 1;
  else if (i === state.active) state.active = Math.min(i, state.tabs.length - 1);
  renderTabs();
  renderActive();
  persistTabs();
}

/* JAG-494: close every open file in the editor (one confirmation if any is
   dirty), then hide the dock since there is nothing left to show. */
function closeAllTabs() {
  if (!state.tabs.length) return;
  const dirty = state.tabs.filter((t) => t.dirty).length;
  if (dirty && !window.confirm("Close all " + state.tabs.length + " tabs? " + dirty + " have unsaved changes.")) return;
  state.tabs.forEach((t) => { if (t.temp && t.objectUrl) { try { URL.revokeObjectURL(t.objectUrl); } catch (e) { /* ignore */ } } });
  state.tabs = [];
  state.active = -1;
  persistTabs();
  close();
}

async function save() {
  const t = activeTab(); if (!t) { setStatus("no file open"); return; }
  if (t.readonly) { setStatus("file read-only"); return; }
  syncActive();
  try {
    const r = await jpost("/api/fs/write", { path: t.path, content: t.value, session: SESSION() });
    if (r.error) { setStatus("error: " + r.error); return; }
    t.saved = t.value; t.dirty = false;
    renderTabs(); updateStatus();
    setStatus("saved · " + r.bytes + " bytes");
  } catch (e) { setStatus("error: " + e); }
}

function revert() {
  const t = activeTab(); if (!t) return;
  t.value = t.saved;
  t.dirty = false;
  renderTabs();
  renderActive();
  setStatus("reverted");
}

function toggleRender() {
  const t = activeTab(); if (!t || t.viewer !== "markdown") return;
  syncActive();
  t.mode = t.mode === "code" ? "render" : "code";
  renderActive();
}

/* JAG-368: opening/closing the dock changes the row width, so the app must re-fit the
   side panels (and re-glue every grip) — otherwise the row can stay over-constrained
   and a panel border ends up off the screen where it cannot be dragged. */
function _notifyLayout() { try { if (window._settleHandles) window._settleHandles(); } catch (e) {} }
function show() {
  buildDock();
  state.dock.hidden = false;
  localStorage.setItem(LS_OPEN, "true");   // JAG-157: an explicit open sticks
  applyResponsive();
  if (state.treeEl && !state.treeEl.hidden && !state.treeEl.childElementCount) loadTree();
  _notifyLayout();
}
function close() {
  syncActive();
  if (state.dock) state.dock.hidden = true;
  localStorage.setItem(LS_OPEN, "false");
  _notifyLayout();
}
function toggle(e) {
  if (!$id("editorDock")) buildDock();
  if (state.dock.hidden) { if (!state.tabs.length) restoreTabs(); else show(); } else close();
}
/* JAG-157: open the editor by default — unless the user closed it on purpose. */
async function ensureOpen() {
  buildDock();
  if (localStorage.getItem(LS_OPEN) === "false") return;
  if (state.dock.hidden) await restoreTabs();
}
/* JAG-157: a session switch changes the workspace AND the tab set — reload both. */
async function onSessionChange() {
  syncActive();
  state.tabs = []; state.active = -1;
  if (state.host) state.host.destroy();
  if (state.preview) state.preview.hidden = true;
  buildDock();
  if (state.tabsEl) renderTabs();
  if (localStorage.getItem(LS_OPEN) === "false") return;
  await restoreTabs();
  if (state.treeEl) loadTree();
}

async function restoreTabs() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(tabsKey()) || "null"); } catch (e) { saved = null; }
  if (!saved || !Array.isArray(saved.paths) || !saved.paths.length) { show(); return; }
  for (const p of saved.paths.slice(0, 12)) {
    try {
      await open(p);
    } catch (e) { /* skip */ }
  }
  if (typeof saved.active === "number" && saved.active >= 0 && saved.active < state.tabs.length) {
    state.active = saved.active; renderTabs(); renderActive();
  }
  show();
}

function init() {
  // JAG-157: build the dock and open it (default) on the active session's folder.
  const start = () => { buildDock(); onSessionChange(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}

async function refresh(path) {
  const i = state.tabs.findIndex((t) => t.path === path);
  if (i < 0) { open(path); return; }
  try {
    const d = await jget("/api/fs/read?path=" + encodeURIComponent(path) + sessionQS());
    if (d && !d.error) {
      state.tabs[i].saved = d.text || "";
      state.tabs[i].value = d.text || "";
      state.tabs[i].dirty = false;
      renderTabs();
      if (state.active === i) renderActive();
    }
  } catch (e) { /* ignore */ }
}
/* JAG-160: the dock's reload button refreshes EVERYTHING — the tree plus the
   content of every open (non-temp) tab, re-read from disk. */
async function refreshAll() {
  syncActive();
  // JAG-295-fix: reloading re-reads every open tab from disk and overwrites the
  // in-memory buffer, silently discarding unsaved edits (closeTab already asks;
  // this path did not).
  const dirty = state.tabs.filter((t) => !t.temp && t.dirty);
  if (dirty.length && !window.confirm("Reload and discard unsaved changes in " + dirty.length + " file(s)?")) return;
  const paths = state.tabs.filter((t) => !t.temp).map((t) => t.path);
  await loadTree();
  for (const p of paths) { await refresh(p); }
  setStatus(paths.length ? ("reloaded · " + paths.length + " tab") : "tree reloaded");
}
function closePath(path) { const i = state.tabs.findIndex((t) => t.path === path); if (i >= 0) closeTab(i); }
function has(path) { return state.tabs.some((t) => t.path === path); }

/* JAG-159: right-click menu on a file row in the tree. */
function hideTreeMenu() { const m = $id("edCtx"); if (m) m.remove(); }
function showTreeMenu(x, y, path) {
  hideTreeMenu();
  const m = document.createElement("div");
  m.id = "edCtx";
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => { hideTreeMenu(); fn(); };
    m.appendChild(b);
  };
  mk("⧉ copy path", () => copyPath(path));
  mk("📄 open in editor", () => open(path));
  mk("⇩ download", () => downloadPath(path));
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
  m.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
}
/* JAG-282: right-click on an editor TAB — copy its path / name, reveal it in the
   tree, download or close. Mirrors the file-tree menu so the two behave alike. */
function showTabMenu(x, y, i) {
  const t = state.tabs[i]; if (!t) return;
  hideTreeMenu();
  const m = document.createElement("div");
  m.id = "edCtx";
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => { hideTreeMenu(); fn(); };
    m.appendChild(b);
  };
  const temp = !!t.temp || String(t.path).startsWith("untitled://");
  if (temp) {
    mk("⧉ copy name", () => copyPath(basename(t.path)));
  } else {
    mk("⧉ copy path", () => copyPath(t.path));
    mk("⧉ copy name", () => copyPath(basename(t.path)));
    // JAG-494: "reveal in file tree" is gone from the menu — it now runs on the
    // tab click itself. Kept only the out-of-workspace warning for clarity.
    if (!_inWorkspace(t.path)) mk("⚠ outside the workspace", () => {});
    mk("⇩ download", () => downloadPath(t.path));
  }
  mk("✕ close tab", () => closeTab(i));
  mk("✕✕ close all", () => closeAllTabs());
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
  m.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
}
/* Reveal a path in the file tree: show the pane, (re)load it, then flash the row.
   Root-level files (the usual agent output) are found directly; deeper ones need
   the folders expanded, so we also fall back to a basename match. */
async function revealInTree(path) {
  if (!state.treeEl) return;
  state.treeEl.hidden = false;
  localStorage.setItem("sf_ed_tree", "1");
  if (!state.treeEl.childElementCount) await loadTree();
  const rows = Array.from(state.treeEl.querySelectorAll(".ed-trow"));
  let hit = rows.find((r) => r.title === path);
  if (!hit) { const base = basename(path); hit = rows.find((r) => r.textContent.trim().endsWith(base)); }
  if (hit) {
    hit.scrollIntoView({ block: "center" });
    hit.classList.add("flash");
    setTimeout(() => hit.classList.remove("flash"), 1400);
  }
}
function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) { /* ignore */ }
  ta.remove();
}
function copyPath(path) {
  const done = () => setStatus("path copied ✓ " + path);
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(path).then(done, () => { fallbackCopy(path); done(); });
      return;
    }
  } catch (e) { /* fall through */ }
  fallbackCopy(path); done();
}
function downloadPath(path) {
  const url = "/api/fs/raw?path=" + encodeURIComponent(path) + (TOKEN() ? "&token=" + encodeURIComponent(TOKEN()) : "") + sessionQS();
  window.open(url, "_blank");
}
/* JAG-159: drop from the OS -> temp tab (the browser does not expose the path). */
function handleDrop(files) {
  if (!files || !files.length) return;
  Array.from(files).slice(0, 5).forEach((f) => {
    if ((f.type || "").startsWith("image/")) openTempImage(f.name, URL.createObjectURL(f));
    else f.text().then((t) => openTemp(f.name, t)).catch(() => openTemp(f.name, ""));
  });
}
function openTemp(name, text) {
  buildDock();
  const p = "untitled://" + name;
  const i = state.tabs.findIndex((t) => t.path === p);
  if (i >= 0) { activate(i); show(); return; }
  const tab = { path: p, viewer: viewerFor(name), lang: langOf(name), mode: "render",
                saved: text || "", value: text || "", dirty: false, readonly: true,
                size: (text || "").length, temp: true };
  state.tabs.push(tab); state.active = state.tabs.length - 1;
  renderTabs(); renderActive(); show();
  setStatus("dragged file · temporary (not saved)");
}
function openTempImage(name, url) {
  buildDock();
  const p = "untitled://" + name;
  const i = state.tabs.findIndex((t) => t.path === p);
  if (i >= 0) { activate(i); show(); return; }
  const tab = { path: p, viewer: "image", lang: null, mode: "render", saved: "", value: "",
                dirty: false, readonly: true, objectUrl: url, temp: true };
  state.tabs.push(tab); state.active = state.tabs.length - 1;
  renderTabs(); renderActive(); show();
  setStatus("dragged image · temporary");
}

window.SparkEditor = {
  open: (p, opts) => { open(p, opts); },
  save,
  refresh,
  refreshAll,
  closePath,
  has,
  close,
  toggle,
  isOpen: () => !!$id("editorDock") && !$id("editorDock").hidden,
  restore: restoreTabs,
  ensureOpen,
  onSessionChange,
};

init();

export { open, close, toggle };
