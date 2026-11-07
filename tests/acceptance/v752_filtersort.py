#!/usr/bin/env python3
"""v752 — ONE filter+sort control, shared by the Sessions rail and the Control
AGENTS table.

Operator: "per le sessioni deve esserci un sort/filter come quello del AGENTS panel
in Control page (no duplicare codice) … quel bottone deve sortare … the filter is
unique, a sort filter on control page shall do the same on session panel. so just
two icons in the two pages sessions and control for the same identical things in
the backend."

Contract:
  A) the spec (filters, sort modes, natural direction), the state, its persistence
     and the panel MARKUP live in exactly one file: webui/assets/filtersort.js.
     Both pages load it and neither carries a copy of the panel or of the mode list.
  B) the Sessions rail's funnel opens that panel: team scope · sort key + direction
     · hide empty · running only. #hide-empty stays the rail's effective value.
  C) the Control toolbar's two labelled selects are gone; one icon opens the same
     panel, whose generated ids still are #teamSel / #agSort (renderTeams and the
     agent table keep reading them).
  D) both pages apply the same keys and the same direction semantics.

Run: python tests/acceptance/v752_filtersort.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


JS = src("webui", "assets", "filtersort.js")
CSS = src("webui", "assets", "filtersort.css")
UI = src("webui", "index.html")
ORBIT = src("src", "longrun", "orbit", "web", "orbit.html")

# ---- A. one definition ---------------------------------------------------------
check("A1 both pages load the one module and its one stylesheet",
      '<script src="/assets/filtersort.js"></script>' in UI
      and '<script src="/assets/filtersort.js"></script>' in ORBIT
      and '<link rel="stylesheet" href="/assets/filtersort.css">' in UI
      and '<link rel="stylesheet" href="/assets/filtersort.css">' in ORBIT)
check("A2 the panel markup exists only in the module",
      'data-fs="team"' in JS and 'data-fs="sort"' in JS and 'data-fs="dir"' in JS
      and 'data-fs="hideEmpty"' in JS and 'data-fs="running"' in JS
      and "data-fs=" not in UI and "data-fs=" not in ORBIT)
check("A3 the sort-mode labels exist only in the module",
      "latest update" in JS
      and "latest update" not in UI and "latest update" not in ORBIT
      and "leadership first (org)" in JS
      and "leadership first (org)" not in UI and "leadership first (org)" not in ORBIT)
check("A4 the panel look is the shared stylesheet, not page CSS",
      ".fs-pop {" in CSS and ".fs-pop {" not in UI and ".fs-pop {" not in ORBIT)
check("A5 one mount per page (no second copy of the control)",
      UI.count("FilterSort.mount({") == 1 and ORBIT.count("FilterSort.mount({") == 1
      and "window.FilterSort = {" in JS)

# ---- B. Sessions rail ----------------------------------------------------------
check("B1 the rail icon opens the shared panel (id + pressed state kept)",
      'id="hideEmptyBtn" aria-pressed="false"' in UI
      and 'key: "sessions", button: btn' in UI)
# v851 (accessibility): the same input gained an aria-label; pin the ELEMENT and
# assert it is a hidden checkbox instead of one exact attribute order.
_HIDE_EMPTY = re.search(r'<input\b[^>]*\bid="hide-empty"[^>]*>', UI)
_HIDE_EMPTY_TAG = _HIDE_EMPTY.group(0) if _HIDE_EMPTY else ""
check("B2 the rail keeps #hide-empty as its effective hide-empty value",
      'type="checkbox"' in _HIDE_EMPTY_TAG
      and re.search(r"(?:^|\s)hidden(?:\s|/?>|$)", _HIDE_EMPTY_TAG)
      and 'cb.checked = !!st.hideEmpty;' in UI
      and "const hideEmpty = $(\"hide-empty\") ? $(\"hide-empty\").checked : false;" in UI)
check("B3 the rail applies team scope and running-only from the shared state",
      'const fs = window.FilterSort ? FilterSort.get("sessions")' in UI
      and "inScope(s)" in UI and "!fs.running || !!runningSessions[s.id]" in UI)
check("B4 the rail applies the shared sort keys with one direction rule",
      "_SESS_SORT" in UI and 'const _mul = fs.dir === "asc" ? 1 : -1;' in UI
      and all(k in UI for k in ("updated:", "name:", "role:", "model:",
                                "team:", "id:", "running:", "leader:")))
check("B5 the stored drag order is a SORT MODE, not a silent override",
      'const _manual = fs.sort === "manual";' in UI
      and 'const _stored = (g) => (_manual ? (_sidebarOrder.sessions[g] || []) : []);' in UI
      and "s => s.id, _sessSort, true)" in UI)

# ---- C. Control AGENTS table ---------------------------------------------------
check("C1 the Control toolbar carries ONE icon, not two labelled selects",
      'id="agFilterBtn"' in ORBIT
      and 'id="teamSel"' not in ORBIT and 'id="agSort"' not in ORBIT
      and '<span class="lbl">scope</span>' not in ORBIT
      and '<span class="lbl">sort</span>' not in ORBIT)
check("C2 the panel still generates #teamSel / #agSort (existing readers intact)",
      'team: "teamSel", sort: "agSort", dir: "agDir"' in ORBIT
      and '$("teamSel")' not in ORBIT and '$("agSort")' not in ORBIT)
check("C3 the board reads the panel state (no local mode list, no local defaults)",
      'key: "agents", button: $("agFilterBtn")' in ORBIT
      and "this.fs.get()" in ORBIT
      and 'defaults: { sort: "leader", dir: "asc" }' in ORBIT)
check("C4 status filters hide a void prompt and a non-running turn",
      "const keepStatus = (a) => (!fs.hideEmpty || a.prompt_chars !== 0)" in ORBIT
      and "(!fs.running || running.has(a.session))" in ORBIT)
check("C5 the scope list has ONE writer (renderTeams feeds the panel only)",
      "this.fs.refreshTeams();" in ORBIT and "this.team = this.fs.get().team;" in ORBIT
      and 'sel.innerHTML = \'<option value="ALL">ALL teams' not in ORBIT)

# ---- D. identical vocabulary ---------------------------------------------------
KEYS = ("updated", "leader", "name", "role", "model", "team", "id", "running")
check("D1 both pages implement exactly the module's sort keys",
      all(('id: "%s"' % k) in JS for k in KEYS)
      and all(k in UI and k in ORBIT for k in KEYS))
check("D2 both pages apply the same direction semantics",
      'fs.dir === "asc" ? 1 : -1' in UI and 'this.dir === "asc" ? 1 : -1' in ORBIT)
check("D3 one persisted state family, one key per list",
      'KEYPREFIX = "longrun.fs."' in JS
      and 'key: "sessions"' in UI and 'key: "agents"' in ORBIT)

# ---- E. manual mode: the reported "some sessions stay out of the sort" --------
# Operator (2026-10-31): a group dragged once kept its stored order, so the chosen
# sort never reached those rows. The stored order is now one MORE sort mode: any
# other key ignores it, and a drop switches to it.
check("E1 the module offers the drag order as one more sort mode",
      'id: "manual", label: "manual (drag order)"' in JS)
check("E2 the rail reads the stored order ONLY in manual mode (one reader)",
      UI.count("_sidebarOrder.sessions[") == 1
      and 'const _stored = (g) => (_manual ? (_sidebarOrder.sessions[g] || []) : []);' in UI)
check("E3 the Control table reads the stored order ONLY in manual mode",
      'const manual = this.sort === "manual";' in ORBIT
      and "manual ? ((this._order.sessions || {})[g.id] || []) : []" in ORBIT)
check("E4 dropping a row switches BOTH pages to the manual mode",
      '_sessFs.setSilent({ sort: "manual" })' in UI
      and 'this.fs.setSilent({ sort: "manual" })' in ORBIT
      and "if (this.onManualOrder) this.onManualOrder();" in ORBIT)

print("\nv752: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
