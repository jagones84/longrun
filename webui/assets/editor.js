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

const state = { tabs: [], active: -1, host: null, preview: null, tabsEl: null, statusEl: null, toggleBtn: null, resizeEl: null, dock: null, root: "" };

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
    <div class="ed-head"><span class="ed-title">Editor</span><span class="ed-status"></span>
      <button class="ed-files ghost" title="show/hide the file tree">🗂 files</button>
      <button class="ed-refresh ghost" title="reload the tree">↻</button>
      <button class="ed-x ghost" title="close (Esc)">✕</button></div>
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
  dock.querySelector(".ed-x").onclick = close;
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

  const saved = parseInt(localStorage.getItem(LS_W) || "", 10);
  if (saved) dock.style.width = Math.min(saved, _dockMaxW()) + "px";
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
  window.addEventListener("resize", applyResponsive);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || dock.hidden) return;
    const modal = document.querySelector("#diffView:not([hidden]), #skillView:not([hidden])");
    if (!modal) close();
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
  const overlay = _vw() < 1024;
  state.dock.classList.toggle("ed-overlay", overlay);
  const saved = parseInt(localStorage.getItem(LS_W) || "420", 10);
  if (overlay) {
    // JAG-3xx: the fixed overlay ran top:44px -> bottom:0, so on a phone it covered
    // the chat composer (send) AND the whole bottom tab bar — those buttons looked
    // DEAD because the dock received every tap. Keep the dock between the real header
    // and the bottom chrome so both stay visible and tappable.
    state.dock.style.top = _headerH() + "px";
    state.dock.style.bottom = _bottomChromeH() + "px";
    state.dock.style.width = "";
  } else {
    state.dock.style.top = "";
    state.dock.style.bottom = "";
    state.dock.style.width = Math.min(saved, _dockMaxW()) + "px";
  }
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
    b.onclick = () => activate(i);
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
    if (_inWorkspace(t.path)) mk("🔎 reveal in file tree", () => revealInTree(t.path));
    else mk("⚠ outside the workspace", () => {});
    mk("⇩ download", () => downloadPath(t.path));
  }
  mk("✕ close tab", () => closeTab(i));
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
