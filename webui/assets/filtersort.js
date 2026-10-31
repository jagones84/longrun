/* FilterSort — ONE filter+sort panel for the two lists that show the same
   objects: the Sessions rail (webui/index.html) and the AGENTS table of the
   Control deck (src/longrun/orbit/web/orbit.html).

   Why a shared module: the operator asked for the SAME control on both pages
   ("due icone … per le stesse identiche cose"), and the project rule forbids two
   truths. So the spec (which filters, which sort modes, their natural
   direction), the state, its persistence and the panel markup live HERE only.
   A page supplies three things and nothing else:
     · the icon button that opens the panel,
     · where the panel is mounted,
     · onChange(state) — how the list reacts.

   The state is the single source of the *requested* view:
     {sort, dir, team, hideEmpty, running}
   Sort/filter are applied client-side; they never replace the drag order
   (webui/assets/dragsort.js + /api/sidebar/order) — a dragged row stays where
   the operator put it and the sort is the FALLBACK for everything else.

   Persistence: localStorage `longrun.fs.<key>`, one key per list
   ("sessions", "agents"). No backend object is introduced: this is a view
   preference of THIS browser, exactly like the previous hide-empty checkbox. */
(function () {
  "use strict";

  /* dir = the natural direction for that key, so switching key resets the
     arrow to the direction a human expects (Excel autofilter behaviour). */
  var SORTS = [
    {id: "updated", label: "latest update", dir: "desc"},
    {id: "leader", label: "leadership first (org)", dir: "asc"},
    {id: "name", label: "name (A\u2192Z)", dir: "asc"},
    {id: "role", label: "role", dir: "asc"},
    {id: "model", label: "model", dir: "asc"},
    {id: "team", label: "team", dir: "asc"},
    {id: "id", label: "agent id (A1, A2, \u2026)", dir: "asc"},
    {id: "running", label: "running first", dir: "asc"},
    /* The operator's own drag order (the shared sidebar-order store). It is a sort
       mode, not a hidden override: while any other key is chosen the stored order
       is ignored, so a sort always reaches EVERY row; a drag switches to this mode
       (the panel shows it), so the row just moved stays where it was put. */
    {id: "manual", label: "manual (drag order)", dir: "asc"}
  ];
  var DEFAULTS = {sort: "updated", dir: "desc", team: "ALL", hideEmpty: false, running: false};
  var KEYPREFIX = "longrun.fs.";
  var memory = {};   // key -> state (survives a storage failure)

  function naturalDir(id) {
    for (var i = 0; i < SORTS.length; i++) if (SORTS[i].id === id) return SORTS[i].dir;
    return "asc";
  }

  function load(key, seed) {
    var base = {};
    Object.keys(DEFAULTS).forEach(function (k) { base[k] = DEFAULTS[k]; });
    Object.keys(seed || {}).forEach(function (k) { if (seed[k] !== undefined) base[k] = seed[k]; });
    var st = {sort: base.sort, dir: base.dir, team: base.team,
              hideEmpty: base.hideEmpty, running: base.running};
    try {
      var raw = localStorage.getItem(KEYPREFIX + key);
      if (raw) {
        var got = JSON.parse(raw) || {};
        if (typeof got.sort === "string" && SORTS.some(function (s) { return s.id === got.sort; })) st.sort = got.sort;
        if (got.dir === "asc" || got.dir === "desc") st.dir = got.dir;
        if (typeof got.team === "string") st.team = got.team;
        st.hideEmpty = got.hideEmpty === true;
        st.running = got.running === true;
      }
    } catch (e) { /* private mode / corrupt value: fall back to the defaults */ }
    memory[key] = st;
    return st;
  }

  function get(key) { return memory[key] || load(key); }

  function save(key, st) {
    memory[key] = st;
    try { localStorage.setItem(KEYPREFIX + key, JSON.stringify(st)); } catch (e) {}
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }

  /* The panel markup exists in this one place: the pages never carry a copy. */
  function panelHtml(ids) {
    return '<div class="fs-row"><span class="fs-l">team</span>' +
        '<select class="inp fs-inp" id="' + ids.team + '" data-fs="team" ' +
        'title="scope the list: one team, the strays (No team), or everything"></select></div>' +
      '<div class="fs-row"><span class="fs-l">sort</span>' +
        '<select class="inp fs-inp" id="' + ids.sort + '" data-fs="sort" title="order of the rows">' +
          SORTS.map(function (s) { return '<option value="' + s.id + '">' + esc(s.label) + "</option>"; }).join("") +
        "</select>" +
        '<button type="button" class="fs-dir" id="' + ids.dir + '" data-fs="dir" aria-pressed="false" ' +
        'title="descending">\u2193</button></div>' +
      '<div class="fs-row fs-toggles">' +
        '<label class="fs-chk" title="hide the rows with no content yet (no messages / no prompt)">' +
          '<input type="checkbox" id="' + ids.hide + '" data-fs="hideEmpty"> hide empty</label>' +
        '<label class="fs-chk" title="only the rows with a turn in flight">' +
          '<input type="checkbox" id="' + ids.running + '" data-fs="running"> running only</label>' +
      "</div>";
  }

  /* mount(opts) -> handle
       opts.key        localStorage namespace ("sessions" | "agents")
       opts.button     the icon button that toggles the panel
       opts.host       element the panel is appended to (default body)
       opts.ids        element ids of the panel controls (page-specific, so the
                       existing bindings on #teamSel / #agSort keep working)
       opts.teams      optional () -> [{id,label}]; when present THIS module owns
                       the team option list (the rail has no other writer)
       opts.defaults   optional seed for an empty localStorage (per list)
       opts.onChange   (state) -> void, called on every user change
       opts.panelId    id of the panel element */
  function mount(opts) {
    var key = opts.key, btn = opts.button;
    if (!btn) return null;
    var host = opts.host || document.body;
    var ids = {team: "fsTeam", sort: "fsSort", dir: "fsDir",
               hideEmpty: "fsHideEmpty", running: "fsRunning"};
    Object.keys(opts.ids || {}).forEach(function (k) { ids[k] = opts.ids[k]; });
    var st = load(key, opts.defaults);

    var pop = document.createElement("div");
    pop.className = "fs-pop";
    pop.id = opts.panelId || ("fsPop-" + key);
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "filter and sort");
    pop.innerHTML = panelHtml(ids);
    host.appendChild(pop);

    var teamSel = pop.querySelector('[data-fs="team"]');
    var sortSel = pop.querySelector('[data-fs="sort"]');
    var dirBtn = pop.querySelector('[data-fs="dir"]');
    var hideCb = pop.querySelector('[data-fs="hideEmpty"]');
    var runCb = pop.querySelector('[data-fs="running"]');

    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-controls", pop.id);

    function dirty() {
      return st.team !== DEFAULTS.team || st.hideEmpty || st.running ||
             st.sort !== DEFAULTS.sort || st.dir !== DEFAULTS.dir;
    }
    function paint() {
      dirBtn.textContent = st.dir === "asc" ? "\u2191" : "\u2193";
      dirBtn.setAttribute("aria-pressed", st.dir === "asc" ? "true" : "false");
      dirBtn.title = st.dir === "asc" ? "ascending \u2014 click for descending"
                                      : "descending \u2014 click for ascending";
      sortSel.value = st.sort;
      hideCb.checked = !!st.hideEmpty;
      runCb.checked = !!st.running;
      btn.setAttribute("aria-pressed", dirty() ? "true" : "false");
    }
    /* clamp=true: the caller knows the real team list (a data refresh), so an
       unknown stored team falls back to ALL. clamp=false: teams may not be
       loaded yet — keep the stored choice, only mirror what the select shows. */
    function fillTeams(clamp) {
      if (!opts.teams) {
        var known = false;
        for (var i = 0; i < teamSel.options.length; i++) if (teamSel.options[i].value === st.team) known = true;
        teamSel.value = known ? st.team : (teamSel.options.length ? teamSel.options[0].value : "");
        return;
      }
      var list = opts.teams() || [];
      var sig = list.map(function (t) { return t.id; }).join("|");
      if (teamSel.dataset.sig !== sig) {
        teamSel.dataset.sig = sig;
        teamSel.innerHTML = list.map(function (t) {
          return '<option value="' + esc(t.id) + '">' + esc(t.label) + "</option>";
        }).join("");
      }
      if (clamp && list.length && !list.some(function (t) { return t.id === st.team; })) {
        st.team = DEFAULTS.team;
        save(key, st);
      }
      teamSel.value = st.team;
    }
    function commit() { save(key, st); paint(); if (opts.onChange) opts.onChange(st); }

    teamSel.onchange = function () { st.team = teamSel.value; commit(); };
    sortSel.onchange = function () {
      st.sort = sortSel.value;
      st.dir = naturalDir(st.sort);   // a new key starts in its natural direction
      commit();
    };
    dirBtn.onclick = function () { st.dir = st.dir === "asc" ? "desc" : "asc"; commit(); };
    hideCb.onchange = function () { st.hideEmpty = hideCb.checked; commit(); };
    runCb.onchange = function () { st.running = runCb.checked; commit(); };

    function place() {
      var r = btn.getBoundingClientRect();
      pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + "px";
      pop.style.top = Math.max(8, Math.min(r.bottom + 4, window.innerHeight - pop.offsetHeight - 8)) + "px";
    }
    function open(on) {
      pop.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) { fillTeams(true); place(); }
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      open(pop.hidden);
    });
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("pointerdown", function (e) {
      if (pop.hidden) return;
      if (pop.contains(e.target) || btn.contains(e.target)) return;
      open(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) open(false);
    });
    window.addEventListener("resize", function () { if (!pop.hidden) place(); });

    fillTeams(false);
    paint();
    return {
      state: st,
      get: function () { return st; },
      open: function () { open(true); },
      close: function () { open(false); },
      refreshTeams: function () { fillTeams(true); paint(); },
      setSilent: function (patch) {   // a page-owned normalisation, no onChange
        Object.keys(patch || {}).forEach(function (k) { if (patch[k] !== undefined) st[k] = patch[k]; });
        save(key, st);
        paint();
      }
    };
  }

  window.FilterSort = {SORTS: SORTS, DEFAULTS: DEFAULTS, load: load, get: get, save: save, mount: mount};
})();
