#!/usr/bin/env python3
"""v1268 — a long themed <select> carries a filter field (round 185).

Operator, 2026-11-22: *"Assign to shall have the search bar to filter agents, see other
menus in the webui for ref. Also I can't see agents maybe e.g. a54?"* — the deck's
"assign to…" lists the whole roster (97 agents + the placeholder = 98 rows) and could
only be walked by eye.

Measured on the real deck (`/orbit?embed=1&panel=jobs`, 390x844, touch): open the select
→ `.ts-search` present and focused, 98 rows; type "a54" → 1 visible row,
"Head of Longrun Testing · A54"; tap it → `#jobTo` value "A54". Type "zzzz" → 0 rows and
the "no match" line; clear, type "head" → the same row; Enter picks it and closes. A
2-option select (`#jobScope`) opens with NO filter field.

Contract pinned here:
  A  a list longer than 10 rows gets the filter; a short one never does
  B  the match is a case-insensitive substring of the row text AND its value (so "a54"
     finds "Head of Longrun Testing · A54")
  C  hidden rows leave `vis`: arrows/Enter only touch what the operator can see, and the
     pick still writes the ORIGINAL option index (no off-by-filter)
  D  with the filter focused, letters type into it; only navigation keys are intercepted
  E  the empty state says so instead of showing a blank list
  F  the field wears the page tokens and the head sticks while the list scrolls
  G  a phone gets a 40px field

Deterministic and offline: pins on filtersort.js / filtersort.css.
Run: python3 tests/acceptance/v1268_assign_select_search.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8") as f:
    FS = f.read()
with open(os.path.join(REPO, "webui", "assets", "filtersort.css"), encoding="utf-8") as f:
    CSS = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


OPEN = between(FS, "function _tsOpen(sel) {", "function _tsFilter(")
FILTER = between(FS, "function _tsFilter(q) {", "function _tsPick(")
KEYS = FS[FS.rfind('document.addEventListener("keydown", function (e) {'):]
KEYS = KEYS[:KEYS.find("}, true);")]

# ---- A: when the field exists ----------------------------------------------
check("A1 the threshold is one constant (a short list stays bare)",
      "var SEARCH_MIN = 10;" in FS and "opts.length > SEARCH_MIN" in FS)
check("A2 the filter is a real field inside the pinned head",
      '<div class="ts-head"><input class="ts-search" type="text"' in OPEN
      and 'aria-label="filter options"' in OPEN and "autocomplete=\"off\"" in OPEN)
check("A3 the caret goes into the field (a filter you must click first is not one)",
      "(_ts.search || _ts.list || pop).focus(" in OPEN)

# ---- B: what a query matches ----------------------------------------------
check("B1 rows carry their value, so an id finds a row labelled by name",
      "data-v=\"' + _tsEsc(o.value || \"\") + '\"" in OPEN)
check("B2 the match is a case-insensitive substring of text OR value",
      "el.textContent.toLowerCase().indexOf(needle) >= 0" in FILTER
      and "String(el.dataset.v || \"\").toLowerCase().indexOf(needle) >= 0" in FILTER
      and "toLowerCase()" in FILTER)

# ---- C: only the visible rows are navigable -------------------------------
check("C1 a query rebuilds `vis` from the visible rows",
      "st.vis = st.items.filter(function (el) { return !el.hidden; });" in FILTER)
check("C2 the arrows wrap over `vis`, not over every row",
      "st.vis.length" in between(FS, "function _tsMove(step) {", "/* ROUND 176")
      and "st.items.length" not in between(FS, "function _tsMove(step) {", "/* ROUND 176"))
check("C3 the pick still writes the ORIGINAL option index (no off-by-filter)",
      "var on = _ts.vis[_ts.at];" in KEYS
      and "_tsPick(Number(on.dataset.i));" in KEYS
      and "_tsPick(_ts.at)" not in FS)
check("C4 Home/End and the first-letter jump follow the visible rows",
      "var i = (_ts.at + k) % _ts.vis.length;" in KEYS
      and "_ts.vis[i].textContent" in KEYS)

# ---- D: typing in the field ------------------------------------------------
check("D1 letters belong to the field while it holds the focus",
      "classList.contains(\"ts-search\")" in KEYS
      and "if (inSearch) {" in KEYS and "return;" in KEYS)
check("D2 Enter in the field picks the highlighted visible row",
      "var cur = _ts.vis[_ts.at];" in KEYS and "_tsPick(Number(cur.dataset.i));" in KEYS)
check("D3 Escape still closes and arrows still walk",
      'if (e.key === "Escape") { e.preventDefault(); _tsClose(true); return; }' in KEYS
      and "_tsMove(e.key === \"ArrowDown\" ? 1 : -1)" in KEYS)

# ---- E: no silent empty list ----------------------------------------------
check("E1 an empty result says so",
      '<div class="ts-empty" hidden>no match</div>' in OPEN
      and "if (st.empty) st.empty.hidden = st.vis.length > 0;" in FS
      and ".ts-empty {" in CSS)

# ---- F/G: the surface ------------------------------------------------------
_HEAD = between(CSS, ".ts-head {", "}")
_SEARCH = between(CSS, ".ts-search {", "}")
check("F1 the head sticks while the list scrolls",
      "position: sticky;" in _HEAD and "background: var(--menubg" in _HEAD)
check("F2 the field wears the page tokens, never a hard-coded white",
      "background: var(--panel" in _SEARCH and "color: var(--txt" in _SEARCH
      and "#fff" not in _SEARCH and "white" not in _SEARCH.lower())
check("F3 the hidden rows really are gone (the `vis` truth is painted too)",
      ".ts-opt[hidden] { display: none; }" in CSS)
_SHEET = between(CSS, "@media (max-width: 640px) {", "}\n\n/* A phone gets")
check("G1 a phone gets a 40px filter field",
      ".ts-pop.sheet .ts-search { height: 40px;" in CSS)

print("---\nv1268: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
