#!/usr/bin/env python3
"""v646 — Settings ▸ Subagents: no prose, the explanation is the hover.

Operator, verbatim: "in menu subagents troppo scritte sui models e failover son
self esplicativi scemo anche LIMITS scrivi … servono già appare col mouse over
che serve scrivere cose inutili????????? vale per tutta la webui mi sono rotto".

Contract:
  A) the opening prose card is gone — the isolation rule is the heading's tooltip;
  B) "Model & failover" carries the routing/failover explanation as a tooltip, and
     the visible labels are just the field names;
  C) "Limits" carries the config paths as a tooltip; no footnote paragraph;
  D) "Role briefs" has no subtitle line;
  E) the live status line stays EMPTY until something is actually saved/refused;
  F) every control is still bound to its live value (nothing lost);
  G) the swarm cross-link survives (one chip in the heading, not a paragraph).

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v646_subagents_density.py
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = _read("webui", "index.html")
start = UI.index('<div class="sw-cat" data-cat="subagents"')
PANEL = UI[start:UI.index('<div class="sw-cat"', start + 10)]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("A1 the opening prose card is gone", 'id="subCtxNote"' not in UI)
check("A2 the isolation rule survives as the heading tooltip",
      'title="A subagent does NOT share' in PANEL
      and "This panel only CONFIGURES the engine" in PANEL)
check("B1 the failover explanation is a tooltip on the section",
      'title="Optional model tried when the primary fails' in PANEL)
check("B2 the field labels are just the field names",
      ">fallback model</div>" in PANEL and "— optional; default is none" not in PANEL)
check("B3 the 'one source of truth' paragraph is gone",
      "No duplicate model/fallback controls live in Models" not in PANEL)
check("C1 the config paths are a tooltip on Limits",
      'title="depth → config/tools.yaml' in PANEL)
check("C2 no footnote paragraph under the limits", "parallel agents write <code>" not in PANEL)
check("D1 Role briefs has no subtitle line",
      ">Role briefs</h2>" in PANEL and "— the standing instruction a delegation can attach" not in PANEL)
check("E1 the status line starts empty",
      '<div class="remaining u-mt4" id="subFallbackNote"></div>' in PANEL)
check("E2 no prose is printed into it on load",
      '"None = no fallback. Choosing a model saves it immediately."' not in UI
      and '"None = no fallback."' not in UI)
check("E3 a save still answers", '"saved ✓ (auto)"' in UI)
for fid in ("subModel", "subFallbackPick", "subDepth", "subParallel", "subRunning",
            "subNewRole", "subRolesBox", "subResult"):
    check("F1 control still bound: " + fid, ('id="%s"' % fid) in PANEL)
check("F2 the live config path is appended to the tooltip",
      "hd.title.replace(/\\s*config:.*$/, \"\")" in UI)
check("G1 the swarm cross-link is one chip in the heading",
      'data-call="gotoOrchestrate"' in PANEL)
check("G2 the panel holds no leftover prose paragraph",
      len([m for m in re.findall(r'<div class="remaining[^"]*">([^<]{60,})</div>', PANEL)]) == 0,
      re.findall(r'<div class="remaining[^"]*">([^<]{60,})</div>', PANEL))

print("---")
ok = sum(results)
print("\nv646: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
