#!/usr/bin/env python3
"""v1004 — selecting a session must never empty My Artifacts, and the rules say how to verify.

Operator: *"if i put this session disappear the artifacts!!! all counted zero. BUG! please write in
the project rules general way to verify after coding"*.

Root cause: `382b945` made the page's second view a SCOPE (`This session`), so when the chosen
session had written nothing the whole page — counters, chips, cards — went to zero. A narrowing
control must FILTER one population, never swap the data set, and a zero must name itself and
offer the way back.

Locked here:
  E1 one population, one route (the workspace; no per-session data set on the page);
  E2 the session select is built from the rows on screen, never a hand-written list;
  E3 the empty state names the active filter and carries a one-click way back;
  E4 the chips and the counter describe the FILTERED set, so a zero is a fact about the filter;
  E5 choosing a session repaints the same list (no reload, nothing disappears);
  E6 the project rules carry the general verification protocol, and the Workflow line points at it;
  E7 `UserPrompts.md` carries the app-wide rule (a view never empties itself).

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1004_session_filter_and_verify_protocol.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


ui = read("webui/index.html")
rules = read(".trae/rules/project_rules.md")
ups = read("UserPrompts.md")


def block(start, length=2200):
    i = ui.find(start)
    return ui[i:i + length] if i >= 0 else ""


load = block("async function loadArtifacts()")
render = block("function renderArtifacts()", 3600)

check("E1 one population: the loader always asks for the workspace",
      'new URLSearchParams({ limit: "500", scope: "workspace", workspace: _art.ws })' in load
      and 'qs.set("session", sessionId)' not in load)
check("E2 the session select is built from the rows on screen",
      'id="artSess"' in ui and "function _artSessPaint()" in ui
      and "_art.all.forEach(a => { seen[a.session" in ui
      and 'opts.push(["__none__", "not written by a session"])' in ui)
check("E3 the empty state names the filter and offers the way back",
      "has not written an artifact in this workspace" in ui
      and 'data-clear-sess="1"' in ui and "show every session" in ui
      and '_art.sess = ""; renderArtifacts();' in ui)
check("E4 the chips and the counter describe the filtered set",
      "const inSess = _art.all.filter(_artSessMatch);" in render
      and 'const rows = [["all", "All", inSess.length]]' in render
      and '_art.sess ? " · " + _artSessLabel() : ""' in render)
check("E5 choosing a session repaints the same list (no reload, nothing disappears)",
      'ss.onchange = () => { _art.sess = ss.value; renderArtifacts(); };' in ui
      and "loadArtifacts()" not in block("const ss = $(\"artSess\")", 400))
check("E5b the old scope switch is gone (one vocabulary, no dead object)",
      "artScopeAll" not in ui and "artScopeSession" not in ui and "_art.scope" not in ui)

# --- the protocol the operator asked to have written down -------------------
check("E6 the rules carry the general verification protocol",
      "## Verification after coding — the general protocol (2026-11-14)" in rules
      and all(("%d. **" % n) in rules for n in range(1, 8)))
check("E6b the Workflow line points at it instead of describing a second time",
      'What\n"verified" MEANS is §Verification after coding' in rules.replace("  ", " ")
      or "MEANS is §Verification after coding" in rules)
check("E6c the protocol names the two states that broke this week",
      "visual pixels inside a zoomed page" in rules and "emptied the whole page" in rules)
check("E7 UserPrompts carries the app-wide rule",
      "## 5. Lists, filters and empty states" in ups
      and "a view never empties itself" in ups
      and "5.1" in ups and "5.2" in ups and "5.3" in ups and "5.4" in ups
      and "implement §1–§5 literally" in ups)

print("---")
passed = sum(RESULTS)
print("v1004: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
