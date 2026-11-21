/* Marketplace page (ES module) — browse and install plugins, skills, MCP servers
   and connectors.
   The catalogue is DATA: GET /api/market/catalog returns digest-pinned entries.
   A skill/plugin card shows the sha256 it will be verified against; an entry with
   no digest is browsable and its Install button is disabled, with the reason in
   the tooltip. Nothing installs silently: every button is an explicit POST.
   Installed state is a RECORD (GET /api/market/installed) over the stores that
   already own each object — this page never claims to be their owner. */

const KIND_ICON = { plugin: "\u25C8", skill: "\u2726", mcp: "\u26AF", connector: "\u21BB", matrix: "\u25C7" };
const KIND_LABEL = { plugin: "Plugin", skill: "Skill", mcp: "MCP server", connector: "Connector",
                     matrix: "Matrix module" };
/* The five sections, in a fixed order. A plugin is first because it is the
   COMPOSITE (skills + MCP servers); `matrix` is last because it is the only kind
   that ships inside the harness and can never be installed. */
const KIND_ORDER = ["plugin", "skill", "mcp", "connector", "matrix"];
const COLLAPSE_KEY = "lrmkt.collapsed";

const state = {
  kind: "all", q: "", category: "", source: "", manage: false,
  items: [], stats: {}, sources: [], installed: [], errors: [], audit: null,
  pluginStates: {},
  online: [], onlineFor: "", onlineSource: "clawhub", job: null, loading: false,
  local: [],
};
const PAGE_SIZE = 300;

function el(id) { return document.getElementById(id); }

function esc(s) {
  if (window.esc) return window.esc(s);
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function toast(msg, kind) {
  if (window.toast) window.toast(msg, kind);
}

function shortDigest(sha) {
  const s = String(sha || "");
  return s ? s.slice(0, 12) + "\u2026" : "";
}

function installedIds() {
  const out = {};
  (state.installed || []).forEach(r => { out[r.id] = r; });
  return out;
}

/* ── provenance + sections ──────────────────────────────────────────────── */

/* The label comes from the backend (`market.origin_label`) — one vocabulary. */
function originBadge(origin, label, extra) {
  const title = "catalogue: " + (origin || "unknown") + (extra ? " \u00b7 " + extra : "");
  return `<span class="mkt-origin" data-origin="${esc(origin || "")}" title="${esc(title)}">${esc(label || "Unknown")}</span>`;
}

function collapsed() {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "[]")); }
  catch (_) { return new Set(); }
}

function persistCollapsed(set) {
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(Array.from(set))); } catch (_) {}
}

function sourceBreakdown(rows) {
  const m = {};
  rows.forEach(i => { const k = i.origin_label || "Unknown"; m[k] = (m[k] || 0) + 1; });
  return Object.keys(m).sort((a, b) => m[b] - m[a])
    .map(k => esc(k) + " " + m[k]).join(" \u00b7 ");
}

/* A sync is a point-in-time copy: say how old it is, and when it went stale. */
function ageText(s) {
  if (!s) return "";
  if (!s.at) return "never synced";
  const sec = Number(s.age_seconds || 0);
  let t = "just now";
  if (sec >= 86400) t = Math.floor(sec / 86400) + "d ago";
  else if (sec >= 3600) t = Math.floor(sec / 3600) + "h ago";
  else if (sec >= 60) t = Math.floor(sec / 60) + "m ago";
  return "synced " + t + (s.stale ? " \u2014 stale, sync to refresh" : "") +
    " \u00b7 " + Number(s.items || 0) + " entries";
}

function paintSources() {
  const sel = el("mktSource");
  if (sel) {
    (state.sources || []).forEach(s => {
      const opt = Array.from(sel.options).find(o => o.value === s.id);
      if (opt) opt.textContent = s.label + (s.items ? " \u00b7 " + s.items : "");
    });
  }
  /* The SELECTED adapter's own cost wording, straight from the backend — the
     page never invents a price label for a catalogue or a server. */
  const s = (state.sources || []).find(x => sel && x.id === sel.value);
  const n = el("mktSyncAge");
  if (n) {
    n.textContent = s ? ageText(s) : "";
    n.classList.toggle("mkt-warn", !!(s && s.stale));
    if (s && s.cost) n.title = s.cost;
  }
  const c = el("mktCost");
  if (c) {
    c.textContent = (s && s.cost) ? s.cost
      : "Catalogues are free \u2014 a server may still need your own key.";
  }
}

/* One collapsible macro-area (W3C APG disclosure: heading → button + panel).
   "Recommended" uses the same helper, so every fold in the page behaves the same. */
function sectionHtml(key, label, rows, have, shut, note, total) {
  if (!rows.length) return "";
  const open = !shut.has(key);
  const id = "mkt-sec-" + key;
  const src = sourceBreakdown(rows) + (note ? " \u00b7 " + note : "");
  const count = (total && total > rows.length) ? rows.length + " of " + total : String(rows.length);
  return `<h3 class="mkt-sect-h"><button class="mkt-sect-btn" type="button"
      data-kind="${esc(key)}" aria-expanded="${open ? "true" : "false"}"
      aria-controls="${id}" title="${open ? "collapse" : "expand"} ${esc(label)}">
      <span class="mkt-chev" aria-hidden="true">${open ? "\u25BE" : "\u25B8"}</span>
      <span>${esc(label)}</span>
      <span class="mkt-sect-n">${count}</span>
    </button></h3>
    <div class="mkt-sec-body" id="${id}"${open ? "" : " hidden"}>
      <div class="mkt-src">${src}</div>
      <div class="mkt-grid">${rows.map(i => card(i, have)).join("")}</div>
    </div>`;
}

/* ── packages found on this machine (Trae / Claude / OpenClaw) ──────────── */

function localSection() {
  const rows = state.local || [];
  if (!rows.length) return "";
  return `<h3 class="mkt-sect-h"><span class="mkt-sect-static">Found on this machine \u00b7 ${rows.length}</span></h3>
    <div class="mkt-src">Plugins installed for another harness, converted to their skills and MCP
      servers. Installing one also enables its MCP servers and verifies them (a connector
      waits for its key). A code plugin contributes only its skills: the JavaScript part is
      named as ignored.</div>
    <div class="mkt-grid">${rows.map(localCard).join("")}</div>`;
}

function shortHome(p) {
  return String(p || "").replace(/^\/(?:home|Users)\/[^/]+/, "~");
}

function localCard(p) {
  const bad = !!p.error;
  const members = (p.members || []).map(m => m.kind + ":" + m.name).join(", ");
  const ignored = (p.ignored || []).length ? " \u00b7 ignored: " + p.ignored.join(", ") : "";
  const base = String(p.path || "").replace(/\/+$/, "").split("/").pop() || p.path || "";
  const where = shortHome(p.path);
  const tip = [p.path].concat(p.notes || []).join(" \u2014 ");
  const meta = bad ? `${p.format} \u00b7 ${where}` : `${p.format} \u00b7 ${members || "\u2014"}${ignored}`;
  return `<article class="mkt-card" data-kind="plugin">
    <div class="mkt-ico" aria-hidden="true">${bad ? "\u25CB" : KIND_ICON.plugin}</div>
    <div class="mkt-body">
      <div class="mkt-name" title="${esc(tip)}">${esc(p.title || p.name || base)}</div>
      <div class="mkt-desc">${esc(bad ? p.error : (p.description || members || ""))}</div>
      <div class="mkt-meta" title="${esc(tip)}">${esc(meta)}</div>
    </div>
    <div class="mkt-act">${bad
      ? `<span class="mkt-warn" title="code plugins have no portable member">not portable</span>`
      : `<button class="ghost mkt-import-local" data-path="${esc(p.path)}"
           title="convert and install this package">Import</button>`}</div>
  </article>`;
}

/* ── render ─────────────────────────────────────────────────────────────── */

function card(item, have) {
  const rec = have[item.id];
  const mine = rec || item.present;
  const icon = KIND_ICON[item.kind] || "\u25CB";
  const bits = [];
  if (item.publisher) bits.push(esc(item.publisher));
  if (item.version) bits.push("v" + esc(item.version));
  if (item.updated) bits.push("updated " + esc(item.updated));
  if (item.sha256) bits.push("sha256 " + esc(shortDigest(item.sha256)));
  else if (item.kind === "skill") bits.push("no digest \u2014 not installable");
  let memberTip = "";
  if (item.kind === "plugin") {
    /* A plugin has no artifact of its own: what it WILL install is its members.
       The card's meta line is one clamped row, so only the COUNT is printed and
       the breakdown lives in the tooltip — never clipped text as the only copy. */
    const MEMBER_NOUN = { skill: ["skill", "skills"], mcp: ["MCP server", "MCP servers"],
                          connector: ["connector", "connectors"] };
    const members = item.members || [];
    const byKind = {};
    members.forEach(m => { byKind[m.kind] = (byKind[m.kind] || 0) + 1; });
    memberTip = Object.keys(byKind).map(k => {
      const noun = MEMBER_NOUN[k] || [k, k + "s"];
      return byKind[k] + " " + noun[byKind[k] > 1 ? 1 : 0];
    }).join(" \u00b7 ");
    bits.push(members.length + (members.length === 1 ? " member" : " members"));
  }
  const badge = originBadge(item.origin, item.origin_label,
    (item.source && (item.source.url || item.source.path)) ||
    (item.license ? "license " + item.license : ""));
  const reason = item.installable ? "" : (item.kind === "plugin"
    ? "a member is missing its digest or its server \u2014 not installable"
    : (item.sha256 ? "not installable" : "this entry carries no sha256"));
  const why = item.present ? "ships with longrun" : "already installed \u2014 see Manage";
  const act = mine
    ? `<button class="ghost" disabled title="${esc(why)}">Installed</button>`
    : `<button class="ghost mkt-install" data-id="${esc(item.id)}" ${item.installable ? "" : "disabled"}
         title="${esc(reason || "install " + item.title)}">Install</button>`;
  const info = infoBtn(item);
  return `<article class="mkt-card" data-kind="${esc(item.kind)}" data-item="${esc(item.id)}">
    <div class="mkt-ico" aria-hidden="true">${icon}</div>
    <div class="mkt-body">
      <div class="mkt-name">${esc(item.title)}</div>
      <div class="mkt-desc">${esc(item.description || KIND_LABEL[item.kind] || "")}</div>
      <div class="mkt-meta" title="${esc(bits.join(" \u00b7 ") + (memberTip ? " \u00b7 " + memberTip : ""))}">${badge} ${esc(bits.join(" \u00b7 ") || KIND_LABEL[item.kind] || "")}</div>
    </div>
    <div class="mkt-act">${info}${act}</div>
  </article>`;
}

/* The detail opener — the keyboard path to the copy the card clamps (the card
   itself is clickable too). A name here, per WebUI graphics rule 2. */
function infoBtn(item) {
  return `<button class="ghost mkt-open" data-item-open="${esc(item.id)}"
    aria-label="full description and source of ${esc(item.title)}"
    title="full description \u00b7 source page">\u24D8</button>`;
}

function manageRow(rec, st) {
  const meta = [rec.publisher, rec.version && "v" + rec.version, rec.sha256 && ("sha256 " + shortDigest(rec.sha256)),
    rec.installed && ("installed " + String(rec.installed).slice(0, 10)), rec.source]
    .filter(Boolean).map(esc).join(" \u00b7 ");
  const badge = originBadge(rec.origin, rec.origin_label, rec.source || rec.target || "");
  const flag = rec.update_available
    ? `<span class="mkt-warn" title="a newer entry exists in the catalogue">update available</span>`
    : (rec.in_catalog ? "" : `<span class="mkt-warn" title="this item is no longer in any catalogue">not in catalogue</span>`);
  /* A plugin's members ARE what it installed: name them (and say which ones this
     install created) so the operator can trace a skill or server back to its plugin.
     The meta row is one clamped line, so the count is printed and the detail is the tooltip. */
  const members = rec.members || [];
  const memberTip = members.map(m => `${m.kind}:${m.name}` + (m.created ? "" : " (already there)"))
    .join(" \u00b7 ");
  const memberBits = (rec.kind === "plugin" && members.length)
    ? members.length + (members.length === 1 ? " member" : " members") : "";
  /* Installed is not READY: a member that was not started (or has no key) is a
     fact about the plugin, so it belongs on the row, with the owner's reason. */
  const live = rec.kind === "plugin" ? (st || null) : null;
  const readyBits = live ? (live.ready ? `ready ${live.live}/${live.total}`
    : `not ready ${live.live}/${live.total}`) : "";
  const offTip = (live && !live.ready)
    ? (live.members || []).filter(m => m.state !== "ready")
      .map(m => `${m.kind}:${m.name} \u2014 ${m.state}` + (m.error ? " (" + m.error + ")" : ""))
      .join(" \u00b7 ")
    : "";
  const line = [meta, readyBits, memberBits].filter(Boolean).join(" \u00b7 ");
  const remTip = rec.kind === "plugin"
    ? "uninstall: removes this record AND the skills/MCP servers it created"
    : "remove the record; the " + (rec.kind === "skill" ? "skill" : "server") +
      " itself stays in its own panel";
  const upd = rec.update_available
    ? `<button class="ghost mkt-update" data-id="${esc(rec.id)}"
         title="reinstall from the catalogue; the digest is verified again">Update</button>`
    : "";
  return `<article class="mkt-card">
    <div class="mkt-ico" aria-hidden="true">${KIND_ICON[rec.kind] || "\u25CB"}</div>
    <div class="mkt-body">
      <div class="mkt-name">${esc(rec.name || rec.id)} ${flag}</div>
      <div class="mkt-desc">${esc(KIND_LABEL[rec.kind] || rec.kind)}${rec.enabled === false ? " \u00b7 disabled" : ""}${live && !live.ready ? " \u00b7 not ready" : ""}</div>
      <div class="mkt-meta" title="${esc([line, offTip, memberTip].filter(Boolean).join(" \u00b7 "))}">${badge} ${esc(line)}</div>
    </div>
    <div class="mkt-act">
      ${upd}
      <button class="ghost mkt-remove" data-id="${esc(rec.id)}"
        data-files="${rec.kind === "plugin" ? "1" : ""}" title="${esc(remTip)}">Remove</button>
    </div>
  </article>`;
}

function render() {
  const body = el("mktBody");
  if (!body) return;
  if (state.manage) {
    const rows = state.installed || [];
    const a = state.audit || {};
    const drift = Number(a.drift || 0);
    const banner = drift
      ? `<div class="mkt-sect"><span class="mkt-warn">${drift} installed record(s) disagree with their owner</span></div>` +
        `<div class="mkt-empty">${(a.rows || []).filter(r => r.state !== "ok")
          .map(r => esc(r.id) + " \u2014 " + esc(r.state) + (r.detail ? " (" + esc(r.detail) + ")" : "")).join("<br>")}</div>`
      : "";
    body.innerHTML = banner + (rows.length
      ? `<div class="mkt-sect">Installed \u00b7 ${rows.length}</div><div class="mkt-grid">${rows.map(r => manageRow(r, state.pluginStates[r.id])).join("")}</div>`
      : `<div class="mkt-empty">Nothing installed from the catalogue yet.</div>`);
    return;
  }
  if (!state.items.length) {
    const filtered = !!(state.source || state.category || state.q);
    const why = (state.errors || []).length
      ? `<div class="mkt-empty">No catalogue could be read:<br>${state.errors.map(esc).join("<br>")}</div>`
      : filtered
        ? `<div class="mkt-empty">Nothing matches these filters${state.source ? " in " + esc(state.source) : ""}.<br>
             Clear the search, the category or the catalogue chip to see everything.</div>`
        : `<div class="mkt-empty">The catalogue is empty.<br>
           Add a source URL in <code>config/market.yaml</code>, or create
           <code>data/market/catalog.json</code>.</div>`;
    body.innerHTML = why;
    return;
  }
  const have = installedIds();
  const matched = Number(state.stats.matched || state.items.length);
  const byKind = state.stats.by_kind || {};
  let html = matched > state.items.length
    ? `<div class="mkt-sect">Showing ${state.items.length} of ${matched} \u2014 use search or a category to narrow</div>`
    : "";
  const featured = state.items.filter(i => i.featured);
  const rest = state.items.filter(i => !i.featured);
  const shut = collapsed();
  if (featured.length) {
    html += sectionHtml("recommended", "Recommended", featured, have, shut, "");
  }
  if (state.local.length && (state.kind === "plugin" || state.kind === "all")) {
    html += localSection();
  }
  const kinds = state.kind === "all" ? KIND_ORDER : [state.kind];
  kinds.forEach(kind => {
    const rows = rest.filter(i => i.kind === kind);
    // Featured cards live in the "Recommended" section above, not twice in the
    // grid; say so, or the section count looks smaller than the catalogue.
    const rec = featured.filter(i => i.kind === kind).length;
    const total = Math.max(0, Number(byKind[kind] == null ? rows.length + rec : byKind[kind]) - rec);
    html += sectionHtml(kind, KIND_LABEL[kind] || kind, rows, have, shut,
                        rec ? `+${rec} in Recommended` : "", total);
  });
  if (state.online.length && !state.manage && onlineKindMatches()) {
    html += `<h3 class="mkt-sect-h"><span class="mkt-sect-static">Online \u00b7 ` +
      esc(state.onlineSource === "clawhub" ? "ClawHub" : "MCP Registry") +
      ` \u00b7 ${state.online.length}</span></h3>` +
      `<div class="mkt-grid">${state.online.map(onlineCard).join("")}</div>`;
  }
  if (matched > state.items.length) {
    html += `<div class="mkt-more"><button class="ghost" id="mktMore" type="button"
      title="read the next page of the catalogue">Load more (${state.items.length} of ${matched})</button></div>`;
  }
  body.innerHTML = html;
}

/* An online row is a PREVIEW: no digest is pinned yet, so it is imported first. */
function onlineCard(item) {
  const badge = originBadge("online", "Online");
  const bits = [item.publisher, item.version && "v" + item.version, item.license]
    .filter(Boolean).map(esc).join(" \u00b7 ");
  return `<article class="mkt-card" data-kind="${esc(item.kind)}" data-item="${esc(item.id)}">
    <div class="mkt-ico" aria-hidden="true">${KIND_ICON[item.kind] || "\u25CB"}</div>
    <div class="mkt-body">
      <div class="mkt-name">${esc(item.title)}</div>
      <div class="mkt-desc">${esc(item.description || "")}</div>
      <div class="mkt-meta" title="found online \u2014 not in the local catalogue yet">${badge} ${bits}</div>
    </div>
    <div class="mkt-act">${infoBtn(item)}<button class="ghost mkt-import-remote"
      data-source="${esc(state.onlineSource)}" data-slug="${esc(item.name)}"
      title="download it once, pin its digest, then install it">Import</button></div>
  </article>`;
}

function onlineKindMatches() {
  const kind = state.onlineSource === "clawhub" ? "skill" : "mcp";
  return state.kind === "all" || state.kind === kind;
}

function renderChips(cats, counts) {
  const box = el("mktChips");
  if (!box) return;
  const c = counts || {};
  /* "All" is the SCOPE total (before the category filter), not the current page:
     sums the per-area counts, which are computed on the same scope. */
  const scopeTotal = Object.keys(c).length
    ? Object.values(c).reduce((a, b) => a + Number(b || 0), 0)
    : Number(state.stats.matched || 0);
  const all = ["All"].concat(cats || []);
  box.innerHTML = all.map(name => {
    const on = (name === "All" && !state.category) || name === state.category;
    const n = name === "All" ? scopeTotal : Number(c[name] || 0);
    return `<button class="mkt-chip" data-cat="${name === "All" ? "" : esc(name)}"
      aria-pressed="${on ? "true" : "false"}">${esc(name)}` +
      (n ? ` <b class="mkt-n">${n}</b>` : "") + "</button>";
  }).join("");
}

/* The catalogue FILTER (not the sync selector): one chip per origin. */
function renderSources() {
  const box = el("mktSources");
  if (!box) return;
  const opts = [{ origin: "", label: "All sources" },
                { origin: "bundled", label: "Bundled" },
                { origin: "imported:mcp-registry", label: "MCP Registry" },
                { origin: "imported:clawhub", label: "ClawHub" },
                { origin: "local", label: "Your catalogue" }];
  box.innerHTML = opts.map(o => `<button class="mkt-chip" data-source="${esc(o.origin)}"
    aria-pressed="${o.origin === state.source ? "true" : "false"}">${esc(o.label)}</button>`).join("");
}

function setTabs() {
  document.querySelectorAll("#mktTabs .mkt-tab").forEach(t => {
    const k = t.getAttribute("data-kind");
    const on = state.manage ? k === "manage" : k === state.kind;
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
}

/* ── data ───────────────────────────────────────────────────────────────── */

async function load(opts) {
  const append = !!(opts && opts.append);
  const body = el("mktBody");
  if (body && !state.items.length) body.innerHTML = `<div class="mkt-empty">loading the catalogue\u2026</div>`;
  const offset = append ? state.items.length : 0;
  const qs = ["limit=" + PAGE_SIZE, "offset=" + offset];
  if (!state.manage && state.kind !== "all") qs.push("kind=" + encodeURIComponent(state.kind));
  if (state.q) qs.push("q=" + encodeURIComponent(state.q));
  if (state.category) qs.push("category=" + encodeURIComponent(state.category));
  if (state.source) qs.push("source=" + encodeURIComponent(state.source));
  let cat = {}, inst = {}, aud = {}, srcs = {};
  try { cat = await window.api("GET", "/api/market/catalog" + (qs.length ? "?" + qs.join("&") : "")); }
  catch (e) { cat = { ok: false, errors: [String(e)] }; }
  try { inst = await window.api("GET", "/api/market/installed"); } catch (_) { inst = {}; }
  try { srcs = await window.api("GET", "/api/market/sources"); } catch (_) { srcs = {}; }
  if (state.manage) {
    try { aud = await window.api("GET", "/api/market/audit"); } catch (_) { aud = {}; }
  }
  const page = (cat && cat.items) || [];
  state.items = append ? state.items.concat(page) : page;
  state.stats = (cat && cat.stats) || {};
  state.errors = (cat && cat.errors) || [];
  state.installed = (inst && inst.installed) || [];
  state.pluginStates = (inst && inst.states) || {};
  state.sources = (srcs && srcs.sources) || [];
  state.audit = aud || null;
  state.local = [];
  if (!state.manage && (state.kind === "plugin" || state.kind === "all")) {
    try {
      const sc = await window.api("GET", "/api/market/plugin-scan");
      state.local = (sc && sc.packages) || [];
    } catch (_) { state.local = []; }
  }
  render();
  renderChips((cat && cat.categories) || [], state.stats.category_counts || {});
  renderSources();
  paintSources();
  setTabs();
  const n = el("mktCount");
  if (n) n.textContent = state.manage
    ? `${state.installed.length} installed`
    : `${Number(state.stats.matched || state.items.length)} item${state.items.length === 1 ? "" : "s"}`;
  // Online breadth: only for a real query, and never for the Manage view.
  if (!state.manage && state.q.trim().length >= 2) {
    await remoteSearch();
    render();
  } else if (state.online.length) {
    state.online = [];
    state.onlineFor = "";
    render();
  }
}

/* A live search against the selected adapter. Rows are PREVIEWS (no digest). */
async function remoteSearch() {
  const q = state.q.trim();
  const key = q + "|" + state.onlineSource;
  if (q.length < 2 || state.onlineFor === key) return;
  let res = {};
  try {
    res = await window.api("GET", "/api/market/remote?source=" +
      encodeURIComponent(state.onlineSource) + "&q=" + encodeURIComponent(q));
  } catch (_) { res = {}; }
  state.online = (res && res.items) || [];
  state.onlineFor = key;
}

async function install(id, overwrite) {
  let res = {};
  try { res = await window.api("POST", "/api/market/install", { id, overwrite: !!overwrite }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) toast(`installed ${res.name || id}`, "ok");
  else toast((res && res.error) || "install failed", "err");
  await load();
}

async function importLocal(path, btn) {
  if (btn) btn.disabled = true;
  let res = {};
  try { res = await window.api("POST", "/api/market/plugin-import", { path: path }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) toast(`imported ${res.name || path}`, "ok");
  else toast((res && res.error) || "import failed", "err");
  await load();
}

/* An ONLINE row: download it once, pin its digest, write it into that source's
   group, then install it through the same path every catalogue entry uses. */
async function importRemote(source, slug, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "importing\u2026"; }
  let res = {};
  try { res = await window.api("POST", "/api/market/import-remote", { source, slug }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (btn) { btn.disabled = false; btn.textContent = "Import"; }
  if (res && res.ok) toast(`imported ${res.name || slug}`, "ok");
  else toast((res && res.error) || "import failed", "err");
  await load();
}

async function remove(id, files) {
  let res = {};
  try {
    res = await window.api("DELETE", "/api/market/installed/" + encodeURIComponent(id)
      + (files ? "?files=1" : ""));
  }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) toast(files ? `uninstalled ${id}` : `removed ${id}`, "ok");
  else toast((res && res.error) || "remove failed", "err");
  await load();
}

/* ── the detail: the copy whole, plus the publisher's page ──────────────── */

/* A catalogue row clamps its description to two lines (`-webkit-line-clamp`), which
   is right for scanning and useless for deciding. The detail is the reading surface:
   the SAME `item.description` (the catalogue copy, never re-summarised here), every
   field the entry carries, and the origin page when one is published. The link is
   rendered only for http(s) — a remote registry is untrusted input. */
function _httpUrl(u) { return /^https?:\/\//i.test(String(u || "")); }

function _hostOf(u) {
  try { return new URL(u).host.replace(/^www\./, ""); }
  catch (_) { return String(u || ""); }
}

function _itemById(id) {
  return (state.items || []).find(i => i.id === id)
    || (state.online || []).find(i => i.id === id) || null;
}

function _row(label, value) {
  return value ? `<dt>${esc(label)}</dt><dd>${value}</dd>` : "";
}

function _serverLine(item) {
  const s = item.server || {};
  if (Array.isArray(s.command) && s.command.length) return `<code>${esc(s.command.join(" "))}</code>`;
  if (s.url) return `<code>${esc(s.url)}</code>`;
  return "";
}

function _srcBlock(item) {
  const home = String(item.homepage || "");
  const dl = String((item.source || {}).url || "");
  const path = String((item.source || {}).path || "");
  const parts = [];
  if (_httpUrl(home)) {
    parts.push(`<a href="${esc(home)}" target="_blank" rel="noopener noreferrer"
      title="open the publisher's page in a new tab">origin page \u2197 ${esc(_hostOf(home))}</a>`);
  }
  if (_httpUrl(dl) && dl !== home) {
    parts.push(`<a href="${esc(dl)}" target="_blank" rel="noopener noreferrer"
      title="the artifact this install downloads \u2014 not a page">artifact \u2197</a>`);
  }
  if (path) parts.push(`<span class="mkt-dlg-note">local: ${esc(shortHome(path))}</span>`);
  if (!parts.length) parts.push(`<span class="mkt-dlg-note">no source page published</span>`);
  return `<div class="mkt-dlg-src">${parts.join("")}</div>`;
}

let _dlgReturn = null;

function closeDetail() {
  const back = el("mktDetailBack"), win = el("mktDetailWin");
  if (back) back.remove();
  if (win) win.remove();
  const back2 = _dlgReturn;
  _dlgReturn = null;
  if (back2 && back2.focus) { try { back2.focus(); } catch (_) {} }
}

function openDetail(id) {
  const item = _itemById(id);
  if (!item) return;
  closeDetail();
  _dlgReturn = document.activeElement;
  const desc = String(item.description || "");
  const members = (item.members || []).length
    ? `<dt>members</dt><dd><ul class="mkt-dlg-mem">` + item.members.map(m =>
        `<li>${esc((KIND_LABEL[m.kind] || m.kind) + ": " + (m.title || m.name))}</li>`).join("") + `</ul></dd>`
    : "";
  const meta = [
    _row("publisher", item.publisher ? esc(item.publisher) : ""),
    _row("version", item.version ? "v" + esc(item.version) : ""),
    _row("kind", esc(KIND_LABEL[item.kind] || item.kind)),
    _row("category", esc(item.upstream_category || item.category || "")),
    _row("license", item.license ? esc(item.license) : ""),
    _row("downloads", item.downloads != null ? esc(String(item.downloads)) : ""),
    _row("updated", item.updated ? esc(item.updated) : ""),
    _row("size", item.bytes ? esc(String(item.bytes) + " bytes") : ""),
    _row("digest", item.sha256 ? `<code>${esc(item.sha256)}</code>` : ""),
    _row("server", _serverLine(item))
  ].join("") + members;
  const back = document.createElement("div");
  back.className = "smback";
  back.id = "mktDetailBack";
  back.setAttribute("data-mktclose", "1");
  const win = document.createElement("div");
  win.className = "smodal";
  win.id = "mktDetailWin";
  win.setAttribute("role", "dialog");
  win.setAttribute("aria-modal", "true");
  win.setAttribute("aria-labelledby", "mktDlgTitle");
  win.innerHTML = `<div class="pick-hd mkt-dlg-hd">
      <div class="mkt-ico" aria-hidden="true">${KIND_ICON[item.kind] || "\u25CB"}</div>
      <b id="mktDlgTitle">${esc(item.title)}</b>
      ${originBadge(item.origin, item.origin_label, "")}
      <button type="button" class="ghost mkt-dlg-x" data-mktclose="1"
        aria-label="close the details" title="close (Esc)">\u2715</button>
    </div>
    <div class="mkt-dlg-body">
      <div class="mkt-dlg-desc"${desc ? "" : ' data-empty="1"'}>${esc(desc || "No description was published for this entry.")}</div>
      <dl class="mkt-dlg-meta">${meta}</dl>
      ${_srcBlock(item)}
    </div>`;
  document.body.append(back, win);
  const x = win.querySelector(".mkt-dlg-x");
  if (x) x.focus();
}

/* ── wiring ─────────────────────────────────────────────────────────────── */

let _searchTimer = null;

function wire() {
  const tabs = el("mktTabs");
  if (tabs && !tabs.dataset.wired) {
    tabs.dataset.wired = "1";
    tabs.addEventListener("click", ev => {
      const t = ev.target.closest(".mkt-tab");
      if (!t) return;
      const k = t.getAttribute("data-kind");
      if (k === "manage") { state.manage = true; }
      else { state.manage = false; state.kind = k; }
      setTabs();
      load();
    });
  }
  const chips = el("mktChips");
  if (chips && !chips.dataset.wired) {
    chips.dataset.wired = "1";
    chips.addEventListener("click", ev => {
      const c = ev.target.closest(".mkt-chip");
      if (!c) return;
      state.category = c.getAttribute("data-cat") || "";
      load();
    });
  }
  /* The CATALOGUE filter (not the sync selector): one chip per origin. */
  const srcs = el("mktSources");
  if (srcs && !srcs.dataset.wired) {
    srcs.dataset.wired = "1";
    srcs.addEventListener("click", ev => {
      const c = ev.target.closest(".mkt-chip");
      if (!c) return;
      state.source = c.getAttribute("data-source") || "";
      load();
    });
  }
  const search = el("mktSearch");
  if (search && !search.dataset.wired) {
    search.dataset.wired = "1";
    search.addEventListener("input", () => {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => { state.q = search.value.trim(); load(); }, 250);
    });
  }
  const body = el("mktBody");
  if (body && !body.dataset.wired) {
    body.dataset.wired = "1";
    body.addEventListener("click", ev => {
      // The card scans, the detail reads: a click anywhere but its buttons opens it.
      const op = ev.target.closest("[data-item-open]");
      if (op) { ev.preventDefault(); openDetail(op.getAttribute("data-item-open")); return; }
      const cardEl = ev.target.closest(".mkt-card[data-item]");
      if (cardEl && !ev.target.closest("button,a")) {
        openDetail(cardEl.getAttribute("data-item")); return;
      }
      const sec = ev.target.closest(".mkt-sect-btn");
      if (sec) {
        const k = sec.getAttribute("data-kind");
        const set = collapsed();
        if (set.has(k)) set.delete(k); else set.add(k);
        persistCollapsed(set);
        render();
        return;
      }
      const ins = ev.target.closest(".mkt-install");
      if (ins && !ins.disabled) { install(ins.getAttribute("data-id")); return; }
      const imp = ev.target.closest(".mkt-import-remote");
      if (imp) {
        importRemote(imp.getAttribute("data-source"), imp.getAttribute("data-slug"), imp);
        return;
      }
      const loc = ev.target.closest(".mkt-import-local");
      if (loc && !loc.disabled) { importLocal(loc.getAttribute("data-path"), loc); return; }
      const more = ev.target.closest("#mktMore");
      if (more) { more.disabled = true; load({ append: true }); return; }
      const upd = ev.target.closest(".mkt-update");
      if (upd) { install(upd.getAttribute("data-id"), true); return; }
      const rem = ev.target.closest(".mkt-remove");
      if (rem) remove(rem.getAttribute("data-id"), !!rem.getAttribute("data-files"));
    });
  }
  const sel = el("mktSource");
  if (sel && !sel.dataset.wired) {
    sel.dataset.wired = "1";
    sel.addEventListener("change", paintSources);
  }
}

function toggleManage(force) {
  state.manage = force === undefined ? !state.manage : !!force;
  setTabs();
  load();
}

function reload() { return load(); }

/* Pull an external marketplace into the catalogue (POST /api/market/sync).
   A full registry pass is minutes, not seconds: the server runs ONE background
   job and this polls its progress. Nothing installs by itself, and a skill's
   digest is pinned by the sync — a failed pass keeps the previous copy. */
async function syncSource() {
  const sel = el("mktSource");
  const source = (sel && sel.value) || "mcp-registry";
  const btn = el("mktSync");
  const age = el("mktSyncAge");
  if (btn) { btn.disabled = true; btn.textContent = "importing\u2026"; }
  let res = {};
  try { res = await window.api("POST", "/api/market/sync", { source, background: 1 }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (!res || !res.ok) {
    if (btn) { btn.disabled = false; btn.textContent = "\u21E3 import"; }
    toast((res && res.error) || "import failed", "err");
    await load();
    return;
  }
  let job = res.job || {};
  const deadline = Date.now() + 15 * 60 * 1000;
  while (job.running && Date.now() < deadline) {
    if (age) age.textContent = "importing " + Number(job.rows_seen || 0) +
      " \u00b7 page " + Number(job.pages || 0);
    await new Promise(r => setTimeout(r, 2000));
    try { job = (await window.api("GET", "/api/market/sync/status")).job || {}; }
    catch (_) { break; }
  }
  if (btn) { btn.disabled = false; btn.textContent = "\u21E3 import"; }
  if (job.error) toast("import failed: " + job.error, "err");
  else if (job.running) toast("import still running \u2014 reload in a while", "err");
  else toast("imported " + Number(job.items || 0) + " item(s) from " + source +
             (Number(job.skipped || 0) ? ", " + job.skipped + " skipped" : "") +
             (job.capped ? " \u2014 item budget reached, the mirror holds the first "
               + Number(job.items || 0) : ""), "ok");
  await load();
}

/* The dialog is created on demand and appended to <body>, so its own events are
   delegated: ✕/backdrop close it, Escape closes it, and nothing else changes. */
document.addEventListener("click", ev => {
  if (ev.target.closest && ev.target.closest("[data-mktclose]")) {
    ev.preventDefault(); closeDetail();
  }
});
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape" && el("mktDetailWin")) {
    ev.preventDefault(); ev.stopPropagation(); closeDetail();
  }
});

wire();

window.LRMkt = { load, reload, toggleManage, openDetail, closeDetail,
  get state() { return state; } };
/* data-call reaches only GLOBALS, so the two page buttons are published here. */
window.mktManage = () => toggleManage();
window.mktReload = () => {
  state.q = ""; state.category = ""; state.source = "";
  const s = el("mktSearch"); if (s) s.value = "";
  load();
};
window.mktSync = () => syncSource();
