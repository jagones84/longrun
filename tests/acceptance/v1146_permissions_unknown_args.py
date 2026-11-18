#!/usr/bin/env python3
"""v1146 — the Permissions page shows the other half of the ledger (round 80).

`policy_report()` has two halves: the rules that fired (`firings`) and the calls that
carried an argument their tool does not declare (`unknown_args`, the R4 staging).
The page rendered only the first, so 14 recorded events — the evidence that decides
whether the unknown-argument refusal may ship — were invisible on the operator's
permissions surface (measured 2026-11-18).

Contract:
  A the block reads the SAME `/api/tools` payload (`rule_firings.unknown_args`), no
    second fetch and no mirror
  B the ledger key is split on `:unknown_arg:` into tool + recorded message
  C rows are sorted by count, and the section is a collapsed <details> (no page growth)
  D the copy states the call RAN (staged, not refused) and that an entry naming a
    field the tool accepts today is history
  E an absent/empty ledger renders nothing — no empty reserved block
  F at most ten rows are printed, the rows that name a call survive the cap, and
    the remainder counts what is actually hidden
  G the block sits between the always-ask card and "Add a rule"
  H `/api/tools` really carries the half

Deterministic: reads the two source files, no server, no browser, no model.
Run: python3 tests/acceptance/v1146_permissions_unknown_args.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_results = []


def check(name, ok, detail=""):
    _results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
_start = _ui.index("function renderPermissions")
_end = _ui.index("\nfunction ", _start + 10)
_render = _ui[_start:_end]
_api = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()

# ---- A) one source ----------------------------------------------------------
check("A1 the block reads the payload already in hand",
      "cov.unknown_args" in _render and "Object.entries(" in _render)
check("A2 no second fetch was added",
      'api("GET", "/api/tools/rule' not in _render
      and 'api("GET","/api/tools/rule' not in _render)
check("A3 it is the rule_firings half",
      'const cov = (d && d.rule_firings) || {};' in _render)

# ---- B) the key is split, not guessed --------------------------------------
check("B1 the key is split on its own marker",
      'k.indexOf(":unknown_arg:")' in _render, "split marker missing")
check("B2 both halves survive",
      'k.slice(0, at)' in _render and 'k.slice(at + ":unknown_arg:".length)' in _render)

# ---- C) bounded, collapsed, sorted ----------------------------------------
check("C1 rows are busiest first", "b.n - a.n" in _render)
check("C2 the section is a <details>, not another row",
      "<details class=\"card perm-card\">" in _render
      and "staged, not refused</summary>" in _render)
check("C3 the summary carries the count",
      "${unArg.length} undeclared-argument event(s)" in _render)

# ---- D) the copy is true ---------------------------------------------------
check("D1 it says the call RAN, not that it was blocked",
      "a call that <b>ran</b>" in _render and "the argument is dropped" in _render)
check("D2 it names the staging decision",
      "decide whether the" in _render and "unknown-argument refusal may ship" in _render)
check("D3 it says a learned field is history, not a defect",
      "a field the tool accepts today is history" in _render)

# ---- E) the empty state ----------------------------------------------------
check("E1 an empty ledger renders no block",
      'const unArgBlock = !unArg.length ? "" :' in _render)

# ---- F) the page cannot grow without bound, and the cap keeps the evidence ---
check("F1 at most ten rows are printed",
      "unArg.filter(u => u.sample)" in _render and ".slice(0, 10)" in _render)
check("F2 a row that names a call is selected first, not sliced away",
      "unArg.filter(u => u.sample)\n    .concat(unArg.filter(u => !u.sample)).slice(0, 10)" in _render)
check("F3 the remainder counts what is actually hidden",
      "unArg.length - unShown.length" in _render and "unShown.length" in _render)
check("F4 the rows are rendered from the selection", "${unShown.map(u =>" in _render)

# ---- G) placement ----------------------------------------------------------
_i_ask = _render.index("Always ask · reaches you even in FULL")
_i_block = _render.index("${unArgBlock}")
_i_add = _render.index("Add a rule")
check("G1 the block sits after the always-ask card and before Add a rule",
      _i_ask < _i_block < _i_add, (_i_ask, _i_block, _i_add))

# ---- H) the backend really serves it ---------------------------------------
check("H1 /api/tools sends policy_report() as rule_firings",
      '"rule_firings": registry.policy_report()' in _api)
_py = open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"), encoding="utf-8").read()
check("H2 policy_report returns the unknown-argument half",
      '"unknown_args": unknown' in _py)

print("---")
_passed = sum(_results)
print("%d/%d PASS" % (_passed, len(_results)))
sys.exit(0 if _passed == len(_results) else 1)
