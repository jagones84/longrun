#!/usr/bin/env python3
"""v508 — Settings/WebUI round: compact editor chrome, provenance, live feedback (JAG-511).

Locked here (all STATIC — deterministic, no browser, no network):
  * the docked editor header is a compact two-row block (eyebrow + window buttons,
    then the path + tree buttons) instead of one wrapping row that ate the top of
    the dock on a 320px panel;
  * skills are grouped in COLLAPSIBLE provenance sections and nothing under
    skills/<category>/ is labelled "built-in" — it is "registered", while Matrix is
    its own section and the two machine buckets keep the generated label;
  * the tools panel states each tool's ORIGIN (built-in / MCP / matrix) and nests
    the namespaces under one collapsible section per origin;
  * Memory search falls back to the semantic index and says which mode answered;
  * "review with LLM" shows a live elapsed clock and cannot be double-started;
  * the Subagents "add role" bar sits ABOVE the list, and the zip installer is one
    row (picker · name · install);
  * the Models panel explains that routing.yaml is the DEFAULT per role (not a
    duplicate of the composer picker or Settings ▸ Subagents).
Run: python3 tests/acceptance/v508_settings_ui_round.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    IDX = f.read()
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    EDITOR = f.read()
with open(os.path.join(REPO, "src", "longrun", "core", "settings.py"), encoding="utf-8") as f:
    SETTINGS = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn(src, head, tail):
    """The body of a function, from `head` up to `tail` (both substrings)."""
    try:
        return src.split(head, 1)[1].split(tail, 1)[0]
    except IndexError:
        return ""


# --- A: compact editor chrome ------------------------------------------------
check("A1 the header is built as two explicit rows",
      'class="ed-hrow"' in EDITOR and EDITOR.count('class="ed-hrow"') == 2, "")
check("A2 the 9px eyebrow keeps the title out of the path's width",
      "letter-spacing:.14em;text-transform:uppercase" in EDITOR
      and "#editorDock .ed-title{font-size:9px" in EDITOR, "")
check("A3 the tree buttons lost their word labels and kept their titles",
      'class="ed-files ghost" title="show/hide the file tree">🗂</button>' in EDITOR, "")
check("A4 tabs and footer are tighter than before",
      "overflow-x:auto;padding:3px 6px;border-bottom" in EDITOR
      and "gap:6px;padding:4px 8px;border-top" in EDITOR, "")

# --- B: provenance in Skills -------------------------------------------------
SK = _fn(IDX, "function renderSkills()", "async function loadSkills")
check("B1 skills use collapsible sections with persisted open state",
      'det.className = "sk-sec"' in SK and "longrun:skillSections" in SK
      and SK.count("det.open = open") == 1, "")
check("B2 four buckets, Matrix separate from self-generated",
      'section("auto", "Self-generated"' in SK and 'section("matrix", "Matrix"' in SK
      and 'section("local", "Uploaded"' in SK and 'section("core", "Registered"' in SK, "")
check("B3 no skill is labelled built-in any more",
      "sk-core\" >built-in" not in SK and 'sk-core">built-in' not in SK
      and "sk-core\">registered" in SK, "")

# --- C: provenance in Tools --------------------------------------------------
TOOLS = _fn(IDX, "function renderTools(el, d)", "el.querySelectorAll(\"button[data-pol]\")")
check("C1 every tool row shows its origin badge",
      "const ORIGIN_BADGE" in TOOLS and "originBadge(t)" in TOOLS
      and "sk-mcp" in TOOLS and "sk-matrix" in TOOLS, "")
check("C2 namespaces are nested under one collapsible section per origin",
      "ORIGIN_SECTIONS" in TOOLS and 'class="tg-origin"' in TOOLS
      and "longrun:toolOrigins" in TOOLS, "")
check("C3 the three origins are named",
      '"nucleus", "Built-in"' in TOOLS and '"mcp", "MCP · external servers"' in TOOLS
      and '"matrix", "Matrix"' in TOOLS, "")

# --- D: memory search actually searches --------------------------------------
MEM = _fn(IDX, "async function loadMemories()", "function memKindsInit")
check("D1 a keyword miss is retried against the semantic index",
      "semantic=1" in MEM and "mode = \"semantic\"" in MEM, "")
check("D2 the status line names the mode that answered",
      '" match · " + mode' in MEM, "")

# --- E: review-with-LLM feedback --------------------------------------------
REV = _fn(IDX, "async function runImprovementReview()", "async function loadImprovement")
check("E1 the button is locked for the duration (no double run)",
      "btn.disabled = true" in REV and "if (btn && btn.disabled) return;" in REV, "")
check("E2 a live elapsed clock is painted every second",
      "setInterval(() => paint(" in REV and "elapsed" in REV, "")
check("E3 a failure is reported, not swallowed",
      "review failed" in REV and "toast(\"backlog review failed\"", "")

# --- F: Subagents + zip layout ----------------------------------------------
SUB = _fn(IDX, '<div class="sw-cat" data-cat="subagents"', '<div class="sw-cat" data-cat="knowledge"')
check("F1 the add-role bar precedes the role list",
      SUB.find('id="subNewRole"') != -1 and SUB.find('id="subNewRole"') < SUB.find('id="subRolesBox"'), "")
ZIP = _fn(IDX, "<h2>Install from zip</h2>", "<h2>Skills · installed</h2>")
check("F2 the zip installer is one row ending in the install button",
      ZIP.find('id="skillZip"') < ZIP.find("installSkillZip")
      and ZIP.count("data-call=\"installSkillZip\"") == 1, "")

# --- G: routing.yaml is explained, not duplicated ----------------------------
check("G1 the routing section says it is the per-role DEFAULT",
      "THE DEFAULTS for every session" in SETTINGS
      and "composer's model picker" in SETTINGS, "")
check("G2 the Models panel points at the composer + Subagents",
      "The composer's model dropdown overrides the chat role for ONE session" in IDX
      and "Settings ▸ Subagents" in IDX, "")

# --- H: the Hooks panel states what is ACTUALLY loaded (JAG-512) -------------
check("H1 the hooks panel carries a live block wired to GET /api/hooks",
      'id="hooksLive"' in IDX and "async function loadHooksLive()" in IDX
      and 'api("GET", "/api/hooks")' in IDX, "")
check("H2 the loader is called when the category opens",
      'else if (name === "hooks") { loadHooksLive(); }' in IDX, "")
check("H3 it says which file wins (overlay vs shipped)",
      "hooks.overlay" in IDX and "the <b>WebUI overlay</b> replaces the shipped list" in IDX, "")
check("H4 it names the block contract in the panel text",
      "exiting <b>2</b> blocks the call" in IDX, "")
check("H5 the runtime sub-agent depth is flagged as the same key as Subagents",
      "Same key as Subagents ▸ Limits" in IDX, "")

print("---")
ok = sum(results)
print("\nv508: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
