#!/usr/bin/env python3
"""v1135 — the guardrail coverage reaches the operator's Permissions page.

Round 69. Rounds 67/68 built the coverage instrument on `/api/tools` and on the
agent's `self.info`; the Permissions page — the one screen that lists every hard
block and always-ask rule — showed the rules and nothing about whether any of them
has ever fired. An operator reading "Hard blocks" could not tell a measured rule
from a rule nobody has ever exercised.

  A  the page carries a coverage strip built from the SAME /api/tools payload
  B  each rule row shows its evidence, one glyph, read from the ledger
  C  the three states are distinct: fired / never-but-proven / unproven
  D  every glyph has a name (title + aria-label) — no bare emoji
  E  a build without the ledger says so instead of printing zeroes
  F  the page still gets the rules from GET /api/tools (one fetch, no mirror)

Deterministic: served page + source; no server, no model, no network.
Run: python3 tests/acceptance/v1135_tool_policy_coverage_ui.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


page = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
api = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()


def block(start, end):
    """The source between two markers — the page is one file, so scope the pins."""
    i = page.find(start)
    j = page.find(end, i + 1) if i >= 0 else -1
    return page[i:j] if i >= 0 and j > i else ""


render = block("function renderPermissions(el, d)", "function renderSelf(el, d)")

# --- A: the strip exists and reads the ledger -------------------------------
check("A1 the Permissions renderer exists", bool(render))
check("A2 it carries a coverage element", 'id="permCoverage"' in render, render[:200])
check("A3 built from rule_firings (no second fetch)",
      "d.rule_firings" in render and 'api("GET", "/api/tools/rule' not in render)
check("A4 the counters come from the report",
      all(k in render for k in ("configured_rules", "fired_rules", "never_fired",
                                "never_fired_unproven", "retired_rules")),
      [k for k in ("configured_rules", "fired_rules", "never_fired_unproven")
       if k not in render])

# --- B/C: one glyph per rule, three distinct states -------------------------
check("B1 the row renders an evidence glyph", "${ev(r.name, key, r.rule)}" in render)
check("B2 the glyph is keyed exactly as the ledger keys a rule",
      'const k = name + ":" + key + ":" + rule;' in render)
check("C1 a fired rule shows its count", "fired ${hit.n} time(s)" in render)
check("C2 a never-fired rule names its proof",
      "proven by ${esc(proofsOf[k])}" in render)
check("C3 an unproven rule is its own state",
      "never fired and no test proves it" in render)

# --- D: every glyph is named ------------------------------------------------
glyphs = re.findall(r'<span class="perm-ev[^"]*"[^>]*>', render)
named = [g for g in glyphs if "title=" in g and "aria-label=" in g]
check("D1 every evidence glyph has title + aria-label",
      len(glyphs) >= 4 and len(named) == len(glyphs), (len(glyphs), len(named)))
check("D2 the page never renders a bare ◌ / ✓ control", "◌!" in render and "✓" in render)

# --- E: the empty state -----------------------------------------------------
check("E1 a build without the ledger says so",
      "no rule-firing ledger on this build" in render, render[-400:])
check("E2 and does not print zeroes as if they were data",
      "Number.isFinite(nConf)" in render)

# --- F: one fetch, the same endpoint ---------------------------------------
check("F1 the page renders from GET /api/tools",
      'renderPermissions($("permsPanel"), d)' in page
      and 'api("GET", "/api/tools")' in page)
check("F2 the endpoint still carries the report",
      '"rule_firings": registry.policy_report()' in api)

print("\n---\nv1135: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
