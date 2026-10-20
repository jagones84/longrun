/* fsfind.js — JAG-501: ONE keyboard search for every file/folder browser.
 *
 * The workspace picker, the file-attach picker and the editor's file tree all
 * need the same thing: type a fragment, jump to a deep folder/file without
 * clicking through every level. They used to each roll their own (and none of
 * them could search), so this module owns the whole behaviour:
 *
 *   findPaths(q, opts)        -> GET /api/fs/find (server walks the tree)
 *   bindSearch(input, listEl) -> input handling + ↑/↓/Enter/Escape + rows
 *
 * `bindSearch` is DOM-agnostic: the caller supplies the input, the container
 * that shows the hits, and a `render` callback for one hit. index.html uses it
 * through `window.FsFind` (classic script), editor.js imports it directly.
 */

const TOKEN = () => {
  try { return localStorage.getItem("sf_token") || ""; } catch (e) { return ""; }
};
const SESSION = () => {
  try { return localStorage.getItem("sf_session") || ""; } catch (e) { return ""; }
};

/** Search the workspace tree. Never throws: returns {error} on failure. */
export async function findPaths(q, opts) {
  const o = opts || {};
  const term = String(q || "").trim();
  if (!term) return { results: [], count: 0 };
  const qs = new URLSearchParams({ q: term, kind: o.kind || "any",
                                   limit: String(o.limit || 60) });
  if (o.session || SESSION()) qs.set("session", o.session || SESSION());
  if (o.base) qs.set("path", o.base);
  if (o.root) qs.set("root", o.root);
  const headers = TOKEN() ? { Authorization: "Bearer " + TOKEN() } : {};
  try {
    const r = await fetch("/api/fs/find?" + qs.toString(), { headers });
    return await r.json();
  } catch (e) {
    return { error: String(e), results: [], count: 0 };
  }
}

/**
 * Bind a keyboard search to an input + a hit container.
 *
 * opts.base    start folder for the walk (default: the session workspace)
 * opts.kind    "dir" | "file" | "any"
 * opts.limit   max hits (default 60)
 * opts.onPick  (hit) => void          -- Enter / click
 * opts.onEmpty () => void             -- the query was cleared (restore the list)
 * opts.onResults (hits) => void       -- fresh hits arrived (hide the normal list)
 * opts.render  (hit, i, active) => Element   -- one row (optional)
 * opts.empty   text when nothing matches (optional)
 *
 * Returns a controller: { run(), clear(), hits(), hi() }.
 */
export function bindSearch(input, listEl, opts) {
  const o = opts || {};
  const state = { hits: [], hi: -1, seq: 0, timer: null };

  const renderRow = (hit, i, active) => {
    if (typeof o.render === "function") return o.render(hit, i, active);
    const b = document.createElement("button");
    b.className = "ghost ff-row" + (active ? " hl" : "");
    b.style.cssText = "display:block;width:100%;text-align:left";
    b.textContent = (hit.dir ? "📁 " : "📄 ") + (hit.rel || hit.name);
    b.title = hit.path;
    return b;
  };

  const paint = () => {
    listEl.innerHTML = "";
    if (!state.hits.length) {
      listEl.innerHTML = '<div class="remaining">' + (o.empty || "no match") + "</div>";
      return;
    }
    state.hits.forEach((h, i) => {
      const el = renderRow(h, i, i === state.hi);
      el.onclick = () => { if (typeof o.onPick === "function") o.onPick(h); };
      listEl.appendChild(el);
    });
    const act = listEl.children[state.hi];
    if (act && act.scrollIntoView) act.scrollIntoView({ block: "nearest" });
  };

  const run = async () => {
    const q = input.value.trim();
    if (!q) { state.hits = []; state.hi = -1; if (typeof o.onEmpty === "function") o.onEmpty(); return; }
    const seq = ++state.seq;
    const d = await findPaths(q, o);
    if (seq !== state.seq) return;
    state.hits = d.results || [];
    state.hi = state.hits.length ? 0 : -1;
    if (typeof o.onResults === "function") o.onResults(state.hits);
    paint();
  };

  input.addEventListener("input", () => {
    clearTimeout(state.timer);
    state.timer = setTimeout(run, 160);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!state.hits.length) return;
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      state.hi = (state.hi + step + state.hits.length) % state.hits.length;
      paint();
    } else if (e.key === "Enter") {
      if (state.hi >= 0 && state.hits[state.hi]) {
        e.preventDefault();
        if (typeof o.onPick === "function") o.onPick(state.hits[state.hi]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      input.value = "";
      state.hits = []; state.hi = -1;
      if (typeof o.onEmpty === "function") o.onEmpty();
    }
  });

  return {
    run,
    clear() { input.value = ""; state.hits = []; state.hi = -1; },
    hits: () => state.hits,
    hi: () => state.hi,
  };
}

/* The classic inline script in index.html cannot `import`; expose the same
   implementation on window so there is still exactly ONE copy. */
if (typeof window !== "undefined") window.FsFind = { findPaths, bindSearch };
