/* Marketplace page (ES module) — browse and install plugins, skills, MCP servers
   and connectors.
   The catalogue is DATA: GET /api/market/catalog returns digest-pinned entries.
   A skill/plugin card shows the sha256 it will be verified against; an entry with
   no digest is browsable and its Install button is disabled, with the reason in
   the tooltip. Nothing installs silently: every button is an explicit POST.
   Installed state is a RECORD (GET /api/market/installed) over the stores that
   already own each object — this page never claims to be their owner. */

const KIND_ICON = { plugin: "\u25C8", skill: "\u2726", mcp: "\u26AF", connector: "\u21BB" };
const KIND_LABEL = { plugin: "Plugin", skill: "Skill", mcp: "MCP server", connector: "Connector" };
/* The four macro-areas, in a fixed order. A connector is an MCP server that needs
   a key, so it is its own section: the install path and the gate differ. */
const KIND_ORDER = ["plugin", "skill", "mcp", "connector"];
const COLLAPSE_KEY = "lrmkt.collapsed";

const state = {
  kind: "all", q: "", category: "", manage: false, items: [], stats: {},
  sources: [], installed: [], errors: [], audit: null,
};

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
  const n = el("mktSyncAge");
  if (!n) return;
  const s = (state.sources || []).find(x => sel && x.id === sel.value);
  n.textContent = s ? ageText(s) : "";
  n.classList.toggle("mkt-warn", !!(s && s.stale));
}

/* One collapsible macro-area (W3C APG disclosure: heading → button + panel).
   "Recommended" uses the same helper, so every fold in the page behaves the same. */
function sectionHtml(key, label, rows, have, shut, note) {
  if (!rows.length) return "";
  const open = !shut.has(key);
  const id = "mkt-sec-" + key;
  const src = sourceBreakdown(rows) + (note ? " \u00b7 " + note : "");
  return `<h3 class="mkt-sect-h"><button class="mkt-sect-btn" type="button"
      data-kind="${esc(key)}" aria-expanded="${open ? "true" : "false"}"
      aria-controls="${id}" title="${open ? "collapse" : "expand"} ${esc(label)}">
      <span class="mkt-chev" aria-hidden="true">${open ? "\u25BE" : "\u25B8"}</span>
      <span>${esc(label)}</span>
      <span class="mkt-sect-n">${rows.length}</span>
    </button></h3>
    <div class="mkt-sec-body" id="${id}"${open ? "" : " hidden"}>
      <div class="mkt-src">${src}</div>
      <div class="mkt-grid">${rows.map(i => card(i, have)).join("")}</div>
    </div>`;
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
  else if (item.kind === "skill" || item.kind === "plugin") bits.push("no digest \u2014 not installable");
  const badge = originBadge(item.origin, item.origin_label,
    (item.source && (item.source.url || item.source.path)) ||
    (item.license ? "license " + item.license : ""));
  const reason = item.installable ? "" : (item.sha256 ? "not installable" : "this entry carries no sha256");
  const why = item.present ? "ships with longrun" : "already installed \u2014 see Manage";
  const act = mine
    ? `<button class="ghost" disabled title="${esc(why)}">Installed</button>`
    : `<button class="ghost mkt-install" data-id="${esc(item.id)}" ${item.installable ? "" : "disabled"}
         title="${esc(reason || "install " + item.title)}">Install</button>`;
  return `<article class="mkt-card" data-kind="${esc(item.kind)}">
    <div class="mkt-ico" aria-hidden="true">${icon}</div>
    <div class="mkt-body">
      <div class="mkt-name">${esc(item.title)}</div>
      <div class="mkt-desc">${esc(item.description || KIND_LABEL[item.kind] || "")}</div>
      <div class="mkt-meta" title="${esc(bits.join(" \u00b7 "))}">${badge} ${esc(bits.join(" \u00b7 ") || KIND_LABEL[item.kind] || "")}</div>
    </div>
    <div class="mkt-act">${act}</div>
  </article>`;
}

function manageRow(rec) {
  const meta = [rec.publisher, rec.version && "v" + rec.version, rec.sha256 && ("sha256 " + shortDigest(rec.sha256)),
    rec.installed && ("installed " + String(rec.installed).slice(0, 10)), rec.source]
    .filter(Boolean).map(esc).join(" \u00b7 ");
  const badge = originBadge(rec.origin, rec.origin_label, rec.source || rec.target || "");
  const flag = rec.update_available
    ? `<span class="mkt-warn" title="a newer entry exists in the catalogue">update available</span>`
    : (rec.in_catalog ? "" : `<span class="mkt-warn" title="this item is no longer in any catalogue">not in catalogue</span>`);
  const upd = rec.update_available
    ? `<button class="ghost mkt-update" data-id="${esc(rec.id)}"
         title="reinstall from the catalogue; the digest is verified again">Update</button>`
    : "";
  return `<article class="mkt-card">
    <div class="mkt-ico" aria-hidden="true">${KIND_ICON[rec.kind] || "\u25CB"}</div>
    <div class="mkt-body">
      <div class="mkt-name">${esc(rec.name || rec.id)} ${flag}</div>
      <div class="mkt-desc">${esc(KIND_LABEL[rec.kind] || rec.kind)}${rec.enabled === false ? " \u00b7 disabled" : ""}</div>
      <div class="mkt-meta" title="${meta}">${badge} ${meta}</div>
    </div>
    <div class="mkt-act">
      ${upd}
      <button class="ghost mkt-remove" data-id="${esc(rec.id)}" title="remove the record (files stay unless you ask)">Remove</button>
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
      ? `<div class="mkt-sect">Installed \u00b7 ${rows.length}</div><div class="mkt-grid">${rows.map(manageRow).join("")}</div>`
      : `<div class="mkt-empty">Nothing installed from the catalogue yet.</div>`);
    return;
  }
  if (!state.items.length) {
    const why = (state.errors || []).length
      ? `<div class="mkt-empty">No catalogue could be read:<br>${state.errors.map(esc).join("<br>")}</div>`
      : `<div class="mkt-empty">The catalogue is empty.<br>
           Add a source URL in <code>config/market.yaml</code>, or create
           <code>data/market/catalog.json</code>.</div>`;
    body.innerHTML = why;
    return;
  }
  const have = installedIds();
  const matched = Number(state.stats.matched || state.items.length);
  let html = matched > state.items.length
    ? `<div class="mkt-sect">Showing ${state.items.length} of ${matched} \u2014 use search or a category to narrow</div>`
    : "";
  const featured = state.items.filter(i => i.featured);
  const rest = state.items.filter(i => !i.featured);
  const shut = collapsed();
  if (featured.length) {
    html += sectionHtml("recommended", "Recommended", featured, have, shut, "");
  }
  const kinds = state.kind === "all" ? KIND_ORDER : [state.kind];
  kinds.forEach(kind => {
    const rows = rest.filter(i => i.kind === kind);
    // Featured cards live in the "Recommended" section above, not twice in the
    // grid; say so, or the section count looks smaller than the catalogue.
    const rec = featured.filter(i => i.kind === kind).length;
    html += sectionHtml(kind, KIND_LABEL[kind] || kind, rows, have, shut,
                        rec ? `+${rec} in Recommended` : "");
  });
  body.innerHTML = html;
}

function renderChips(cats) {
  const box = el("mktChips");
  if (!box) return;
  const all = ["All"].concat(cats || []);
  box.innerHTML = all.map(c => {
    const on = (c === "All" && !state.category) || c === state.category;
    return `<button class="mkt-chip" data-cat="${c === "All" ? "" : esc(c)}"
      aria-pressed="${on ? "true" : "false"}">${esc(c)}</button>`;
  }).join("");
}

function setTabs() {
  document.querySelectorAll("#mktTabs .mkt-tab").forEach(t => {
    const k = t.getAttribute("data-kind");
    const on = state.manage ? k === "manage" : k === state.kind;
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
}

/* ── data ───────────────────────────────────────────────────────────────── */

async function load() {
  const body = el("mktBody");
  if (body && !state.items.length) body.innerHTML = `<div class="mkt-empty">loading the catalogue\u2026</div>`;
  const qs = ["limit=500"];
  if (!state.manage && state.kind !== "all") qs.push("kind=" + encodeURIComponent(state.kind));
  if (state.q) qs.push("q=" + encodeURIComponent(state.q));
  if (state.category) qs.push("category=" + encodeURIComponent(state.category));
  let cat = {}, inst = {}, aud = {}, srcs = {};
  try { cat = await window.api("GET", "/api/market/catalog" + (qs.length ? "?" + qs.join("&") : "")); }
  catch (e) { cat = { ok: false, errors: [String(e)] }; }
  try { inst = await window.api("GET", "/api/market/installed"); } catch (_) { inst = {}; }
  try { srcs = await window.api("GET", "/api/market/sources"); } catch (_) { srcs = {}; }
  if (state.manage) {
    try { aud = await window.api("GET", "/api/market/audit"); } catch (_) { aud = {}; }
  }
  state.items = (cat && cat.items) || [];
  state.stats = (cat && cat.stats) || {};
  state.errors = (cat && cat.errors) || [];
  state.installed = (inst && inst.installed) || [];
  state.sources = (srcs && srcs.sources) || [];
  state.audit = aud || null;
  render();
  renderChips((cat && cat.categories) || []);
  paintSources();
  setTabs();
  const n = el("mktCount");
  if (n) n.textContent = state.manage
    ? `${state.installed.length} installed`
    : `${Number(state.stats.matched || state.items.length)} item${state.items.length === 1 ? "" : "s"}`;
}

async function install(id, overwrite) {
  let res = {};
  try { res = await window.api("POST", "/api/market/install", { id, overwrite: !!overwrite }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) toast(`installed ${res.name || id}`, "ok");
  else toast((res && res.error) || "install failed", "err");
  await load();
}

async function remove(id) {
  let res = {};
  try { res = await window.api("DELETE", "/api/market/installed/" + encodeURIComponent(id)); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) toast(`removed ${id}`, "ok");
  else toast((res && res.error) || "remove failed", "err");
  await load();
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
      const upd = ev.target.closest(".mkt-update");
      if (upd) { install(upd.getAttribute("data-id"), true); return; }
      const rem = ev.target.closest(".mkt-remove");
      if (rem) remove(rem.getAttribute("data-id"));
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
   The catalogue stays a file: a sync WRITES data/market/imported.json, and the
   page re-reads it through the same route as everything else. Nothing installs
   by itself, and a skill's digest was pinned by the sync. */
async function syncSource() {
  const sel = el("mktSource");
  const source = (sel && sel.value) || "mcp-registry";
  const btn = el("mktSync");
  if (btn) { btn.disabled = true; btn.textContent = "syncing\u2026"; }
  let res = {};
  try { res = await window.api("POST", "/api/market/sync", { source }); }
  catch (e) { res = { ok: false, error: String(e) }; }
  if (btn) { btn.disabled = false; btn.textContent = "\u21E3 sync"; }
  if (res && res.ok) {
    const skipped = Number(res.error_count || 0);
    toast(`synced ${source}: ${res.items} item(s)` + (skipped ? `, ${skipped} skipped` : ""), "ok");
  } else {
    toast((res && res.error) || "sync failed", "err");
  }
  await load();
}

wire();

window.LRMkt = { load, reload, toggleManage, get state() { return state; } };
/* data-call reaches only GLOBALS, so the two page buttons are published here. */
window.mktManage = () => toggleManage();
window.mktReload = () => { state.q = ""; const s = el("mktSearch"); if (s) s.value = ""; state.category = ""; load(); };
window.mktSync = () => syncSource();
