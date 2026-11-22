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

  function save(key, st, persist) {
    memory[key] = st;
    if (persist === false) return;
    try { localStorage.setItem(KEYPREFIX + key, JSON.stringify(st)); } catch (e) {}
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }

  /* The team option list — ONE spec for both pages (2026-11-22). The Sessions rail and
     the deck's AGENTS table used to build it in their own document; the shape (ALL,
     No team, then the teams by their number, symbol + name + member count) lives here so
     the two scopes cannot disagree. A caller passes its own team list. */
  function teamOptions(list) {
    return [{id: "ALL", label: "ALL teams"}, {id: "__none__", label: "No team"}].concat(
      (list || []).slice().sort(function (a, b) { return (a.n || 0) - (b.n || 0); })
        .map(function (t) {
          var members = Array.isArray(t.members) ? " (" + t.members.length + ")" : "";
          return {id: t.id,
                  label: (t.symbol ? t.symbol + " " : "") + (t.name || t.id) + members};
        }));
  }

  /* The panel markup exists in this one place: the pages never carry a copy.
     ROUND 173: the visible `.fs-l` word is not a <label for>, so axe flagged both selects
     as `label-title-only` — a title is not a name. Each control now carries an aria-label
     (the visible word stays the sighted label). */
  function panelHtml(ids) {
    return '<div class="fs-row"><span class="fs-l">team</span>' +
        '<select class="inp fs-inp" id="' + ids.team + '" data-fs="team" aria-label="team" ' +
        'title="scope the list: one team, the strays (No team), or everything"></select></div>' +
      '<div class="fs-row"><span class="fs-l">sort</span>' +
        '<select class="inp fs-inp" id="' + ids.sort + '" data-fs="sort" aria-label="sort" title="order of the rows">' +
          SORTS.map(function (s) { return '<option value="' + s.id + '">' + esc(s.label) + "</option>"; }).join("") +
        "</select>" +
        '<button type="button" class="fs-dir" id="' + ids.dir + '" data-fs="dir" aria-pressed="false" ' +
        'aria-label="sort direction" title="descending">\u2193</button></div>' +
      '<div class="fs-row fs-toggles">' +
        '<label class="fs-chk" title="hide the rows with no content yet (no messages / no prompt)">' +
          '<input type="checkbox" id="' + ids.hideEmpty + '" data-fs="hideEmpty"> hide empty</label>' +
        '<label class="fs-chk" title="only the rows with a turn in flight">' +
          '<input type="checkbox" id="' + ids.running + '" data-fs="running"> running only</label>' +
      "</div>";
  }

  /* The WebUI scales the ROOT with CSS `zoom` (`_uiZoom`, JAG-359): a rect arrives in
     VISUAL px while `left`/`top` are laid out in CSS px, so placing a body-level popup
     with the raw rect drifts by the zoom — at 125% it can leave the viewport entirely
     (measured 2026-11-22 on the composer's context card: top 1364 on a 1279px window).
     The deck has no root zoom, so this returns 1 there. */
  function pageZoom() {
    try {
      var z = parseFloat(getComputedStyle(document.documentElement).zoom);
      return isFinite(z) && z > 0 ? z : 1;
    } catch (e) { return 1; }
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
    /* ROUND 175: no `aria-controls` on this button. It named the dialog by id and axe's
       `aria-valid-attr-value` reported a CRITICAL incomplete on every run — while the
       panel was closed the idref had no node, and while open axe still could not resolve
       it. `aria-haspopup` + `aria-expanded` already say what opens and whether it is
       open; the third attribute added a claim nobody could verify. */

    function dirty() {
      return st.team !== DEFAULTS.team || st.hideEmpty || st.running ||
             st.sort !== DEFAULTS.sort || st.dir !== DEFAULTS.dir;
    }
    function paint() {
      dirBtn.textContent = st.dir === "asc" ? "\u2191" : "\u2193";
      dirBtn.setAttribute("aria-pressed", st.dir === "asc" ? "true" : "false");
      dirBtn.setAttribute("aria-label", st.dir === "asc" ? "sort direction: ascending" : "sort direction: descending");
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
    function commit() { save(key, st, !opts.noPersist); paint(); if (opts.onChange) opts.onChange(st); }

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
      var z = pageZoom();
      var r = btn.getBoundingClientRect();
      var vw = window.innerWidth / z, vh = window.innerHeight / z;
      var pw = pop.offsetWidth, ph = pop.offsetHeight;
      pop.style.left = Math.max(8, Math.min(r.left / z, vw - pw - 8)) + "px";
      pop.style.top = Math.max(8, Math.min(r.bottom / z + 4, vh - ph - 8)) + "px";
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
        save(key, st, !opts.noPersist);
        paint();
      }
    };
  }

  window.FilterSort = {SORTS: SORTS, DEFAULTS: DEFAULTS, load: load, get: get, save: save,
                       mount: mount, teamOptions: teamOptions};

  /* ------------------------------------------------------------------ *
   * ThemedSelect — ONE themed popup for EVERY native <select>.
   *
   * 2026-11-22 ROUND 175 (operator: *"ci sono menu in mobile mode che si aprono senza
   * tema grafico, sono bianche … esempio jobs assign to nel pannellone agents jobs …
   * controllali tutti gli spawning menus, devono essere in linea col tema"*). A native
   * <select> opens an OS-drawn list: `color-scheme` styles it on desktop Chrome but not
   * in every mobile browser/WebView, where the list is WHITE whatever the page theme is
   * (measured: every select in both documents computes `color-scheme: dark` and a themed
   * box, so the white surface can only be the UA popup). The control stays a real
   * <select> — the value, the label, the `change` contract and the keyboard/AT surface are
   * unchanged — and only its POPUP is ours, drawn with the page tokens.
   *
   * One implementation for both pages: this file is loaded by the WebUI and by the deck.
   * Auto-installed, because a menu that forgets to opt in is exactly the defect above.
   * ------------------------------------------------------------------ */
  var _ts = {sel: null, pop: null, list: null, items: [], at: -1, openedBy: null, openedAt: 0, press: null, ateClick: 0};

  function _tsEsc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function _tsPhone() {
    try { return window.matchMedia && window.matchMedia("(max-width: 640px)").matches; }
    catch (e) { return false; }
  }
  function _tsClose(refocus) {
    var st = _ts;
    if (st.pop) st.pop.remove();
    if (st.sel) st.sel.setAttribute("aria-expanded", "false");
    var was = st.sel;
    st.sel = null; st.pop = null; st.list = null; st.items = []; st.at = -1;
    st.openedBy = null; st.press = null;
    if (refocus && was) { try { was.focus({preventScroll: true}); } catch (e) {} }
  }
  function _tsPaint() {
    var st = _ts; if (!st.pop) return;
    st.items.forEach(function (el, i) {
      var on = i === st.at;
      el.classList.toggle("on", on);
      el.setAttribute("aria-selected", on ? "true" : "false");
      if (on) {
        if (st.list) st.list.setAttribute("aria-activedescendant", el.id);
        try { el.scrollIntoView({block: "nearest"}); } catch (e) {}
      }
    });
  }
  /* Anchored under the control, flipped up and clamped — the rect is in VISUAL px,
     which is what a body-level popup needs even when the page carries a zoom. */
  function _tsPlace(sel, pop) {
    if (!sel || !pop) return;
    var z = pageZoom();
    var r = sel.getBoundingClientRect();
    var vw = window.innerWidth / z, vh = window.innerHeight / z;
    /* never wider than the menu's own cap: a full-width toolbar select would otherwise
       stretch a one-word list across the page (min-width beats max-width in CSS). */
    pop.style.minWidth = Math.min(420, Math.max(150, Math.round(r.width / z))) + "px";
    var pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left / z), Math.max(8, vw - pw - 8));
    var top = r.bottom / z + 4;
    if (top + ph > vh - 8) top = Math.max(8, r.top / z - ph - 4);
    pop.style.left = Math.round(left) + "px";
    pop.style.top = Math.round(top) + "px";
  }
  function _tsOpen(sel) {
    if (!sel || sel.disabled || sel.multiple || sel.size > 1) return;
    _tsClose(false);
    var opts = [].slice.call(sel.options || []);
    if (!opts.length) return;
    var pop = document.createElement("div");
    pop.className = "ts-pop" + (_tsPhone() ? " sheet" : "");
    /* The floating surface is a DIALOG that CONTAINS the listbox: a body-level listbox is
       content outside every landmark (axe `region`, measured 2026-11-22 on the phone and
       the desktop decks), and a dialog is the same anatomy the FilterSort sheet uses. */
    pop.setAttribute("role", "dialog");
    var name = sel.getAttribute("aria-label") || sel.title || "choose";
    pop.setAttribute("aria-label", name);
    pop.innerHTML = '<div class="ts-list" role="listbox" tabindex="-1" aria-label="' + _tsEsc(name) + '">'
      + opts.map(function (o, i) {
        return '<div class="ts-opt' + (i === sel.selectedIndex ? " on" : "") + '" role="option"'
          + ' id="tsOpt' + i + '" aria-selected="' + (i === sel.selectedIndex) + '"'
          + ' data-i="' + i + '" title="' + _tsEsc(o.textContent) + '">'
          + _tsEsc(o.textContent) + "</div>";
      }).join("") + "</div>";
    document.body.appendChild(pop);
    var at = sel.selectedIndex < 0 ? 0 : sel.selectedIndex;
    _ts.sel = sel; _ts.pop = pop;
    _ts.list = pop.querySelector(".ts-list");
    _ts.items = [].slice.call(pop.querySelectorAll(".ts-opt"));
    _ts.at = at;
    sel.setAttribute("aria-haspopup", "listbox");
    sel.setAttribute("aria-expanded", "true");
    if (!_tsPhone()) _tsPlace(sel, pop);
    _tsPaint();
    try { (_ts.list || pop).focus({preventScroll: true}); } catch (e) {}
  }
  function _tsPick(i) {
    var sel = _ts.sel; if (!sel) return;
    if (i >= 0 && i < sel.options.length && sel.selectedIndex !== i) {
      sel.selectedIndex = i;
      sel.dispatchEvent(new Event("input", {bubbles: true}));
      sel.dispatchEvent(new Event("change", {bubbles: true}));
    }
    _tsClose(true);
  }
  function _tsMove(step) {
    var st = _ts; if (!st.pop || !st.items.length) return;
    st.at = (st.at + step + st.items.length) % st.items.length;
    _tsPaint();
  }
  /* ROUND 176 (operator: *"the filter in the agents panel … disappears immediately after
     the menu is loaded"*): a real press fires `pointerdown` (opens) and then `click` on the
     SAME select, and the click handler read that as "a second click = cancel" — so every
     mouse open closed itself in the same gesture (the probe that opened it dispatched
     `pointerdown` alone and never saw this). `_ts.openedBy/at` mark the press that opened
     the list; the click that closes that gesture is swallowed ONCE, a later click still
     cancels. */
  function _tsOpenedByPointer(sel) { _ts.openedBy = sel; _ts.openedAt = Date.now(); }
  function _tsEatOpeningClick(sel) {
    if (_ts.openedBy !== sel) return false;
    _ts.openedBy = null;
    return Date.now() - _ts.openedAt < 600;
  }
  document.addEventListener("pointerdown", function (e) {
    var sel = e.target && e.target.closest && e.target.closest("select");
    if (!sel || sel.disabled || sel.multiple || sel.size > 1) return;
    e.preventDefault();
    if (_ts.sel === sel) { _tsClose(true); return; }   // a second tap is a cancel
    _tsOpen(sel);
    _tsOpenedByPointer(sel);
  }, true);
  /* A second click on the OPEN control is a cancel, never a native popup. */
  document.addEventListener("click", function (e) {
    var sel = e.target && e.target.closest && e.target.closest("select");
    if (!sel) return;
    if (_ts.sel === sel) {
      e.preventDefault();
      if (_tsEatOpeningClick(sel)) return;   // the click of the press that opened it
      _tsClose(true);
      return;
    }
    if (_ts.sel) { e.preventDefault(); _tsOpen(sel); _tsOpenedByPointer(sel); }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (!_ts.pop) {
      var sel = e.target && e.target.closest && e.target.closest("select");
      if (!sel || sel.disabled || sel.multiple) return;
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault(); _tsOpen(sel);
        if (e.key === "ArrowUp") { _ts.at = _ts.items.length - 1; _tsPaint(); }
      }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); _tsClose(true); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); _tsMove(e.key === "ArrowDown" ? 1 : -1); return; }
    if (e.key === "Home") { e.preventDefault(); _ts.at = 0; _tsPaint(); return; }
    if (e.key === "End") { e.preventDefault(); _ts.at = _ts.items.length - 1; _tsPaint(); return; }
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); _tsPick(_ts.at); return; }
    /* first-letter jump, the one native nicety worth keeping in a long list */
    if (e.key && e.key.length === 1) {
      var ch = e.key.toLowerCase();
      for (var k = 1; k <= _ts.items.length; k++) {
        var i = (_ts.at + k) % _ts.items.length;
        if ((_ts.items[i].textContent || "").toLowerCase().indexOf(ch) === 0) {
          e.preventDefault(); _ts.at = i; _tsPaint(); return;
        }
      }
    }
  }, true);
  document.addEventListener("pointerdown", function (e) {
    if (!_ts.pop) return;
    if (_ts.pop.contains(e.target)) return;   // inside the popup: never close
    var sel = e.target && e.target.closest && e.target.closest("select");
    if (sel && sel === _ts.sel) return;
    _tsClose(false);
  });
  /* ROUND 184 (operator: *"the jobs panel assign to menu is weird, it doesn't scroll,
     it disappears as touched, I can't select who I want. At least in mobile mode"*).
     The pick used to happen on `pointerdown`: a FINGER's touchdown is also the start of
     a scroll, so the row under the thumb was chosen and the menu closed before the list
     could move. Measured on a 390x844 touch screen with the deck's real roster (98
     assignees): a drag selected "Frontend Developer · A16" and closed the popup.
     The press is only REMEMBERED now; the pick happens on `pointerup` when the press did
     not travel (a scroll), and the click that follows it on the same element is eaten so
     it cannot reach the form behind the closed sheet. A click with NO pointer stream
     (assistive tech) still selects. */
  document.addEventListener("pointerdown", function (e) {
    _ts.ateClick = 0;   // a new press: any pending click-through guard is stale
    if (!_ts.pop || !_ts.pop.contains(e.target)) return;
    var opt = e.target && e.target.closest && e.target.closest(".ts-opt");
    _ts.press = opt ? {opt: opt, x: e.clientX, y: e.clientY} : null;
  }, true);
  document.addEventListener("pointerup", function (e) {
    if (!_ts.pop || !_ts.pop.contains(e.target)) return;
    var opt = e.target && e.target.closest && e.target.closest(".ts-opt");
    var p = _ts.press; _ts.press = null;
    if (!opt) return;
    if (p && (Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y)) > 8) return;  // a scroll
    e.preventDefault();
    _ts.ateClick = Date.now();
    _tsPick(Number(opt.dataset.i));
  }, true);
  document.addEventListener("click", function (e) {
    if (_ts.ateClick && Date.now() - _ts.ateClick < 400) {
      _ts.ateClick = 0;
      e.preventDefault(); e.stopPropagation();
      return;
    }
    if (!_ts.pop || !_ts.pop.contains(e.target)) return;
    var opt = e.target && e.target.closest && e.target.closest(".ts-opt");
    if (!opt) return;
    e.preventDefault();
    _tsPick(Number(opt.dataset.i));
  }, true);
  /* ROUND 176 (operator: *"the filter in the agents panel … disappears immediately after
     the menu is loaded"*): the popup used to CLOSE on any scroll — and `_tsPaint()` scrolls
     the chosen row into view while opening, so the very first open closed itself wherever a
     scrollable ancestor existed (the deck's panel). The list now follows its control on
     scroll instead of vanishing; the phone sheet does not move. */
  window.addEventListener("scroll", function () {
    if (!_ts.pop || !_ts.sel || _tsPhone()) return;
    _tsPlace(_ts.sel, _ts.pop);
  }, true);
  window.addEventListener("resize", function () {
    if (!_ts.pop || !_ts.sel) return;
    /* ROUND 184: the phone sheet is anchored by CSS, and a mobile browser fires
       `resize` while its URL bar collapses — closing there made the menu vanish as the
       operator touched it. Nothing to place again, so keep it. */
    if (_tsPhone()) return;
    _tsPlace(_ts.sel, _ts.pop);
  });

  window.ThemedSelect = {open: _tsOpen, close: _tsClose};
})();
