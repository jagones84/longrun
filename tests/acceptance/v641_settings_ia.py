#!/usr/bin/env python3
"""v641 — Settings: one place per subject, prose in the tooltip, one type scale.

Operator, verbatim: "idagnostics mettilo on top", "che sta roba delle rules? ah
ma quello è l'improvement results", "frasi ridondanti … falle vedere on mouse
over", "che vuol dire mcp env files … quanti file ci sono", "togli mio nome
metti solo @jagones84", "purged rimane lì a vita".

Contract:
  A) Diagnostics is the FIRST Settings category.
  B) Info credits the handle only (`@jagones84` → github), values stay dynamic.
  C) The memory manager lives in Improvements, not in Rules.
  D) Tools & approvals: the long FULL/exclusive/nucleus prose is a TOOLTIP; the
     visible labels are short.
  E) Constructed Settings cards: no "Structured settings" heading, `help` is a
     tooltip, save + Automate share ONE row (`set-acts` / `.set-t`).
  F) Hooks: no intro paragraph (title tooltip), source folded into the header.
  G) MCP: the panel states the file read order once.
  H) Rules: the uploaded-file list shows G/P as a label, never glued to a path.
  I) Memory: idle state prints no kind ledger, and purge/forget/add answer with a
     toast instead of a permanent status line.

Run: python tests/acceptance/v641_settings_ia.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v641_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
SETTINGS = src("src", "longrun", "core", "settings.py")

# ---- A. order ----------------------------------------------------------------
m = re.search(r"const SETTINGS_CATS = \[(.*?)\n\];", UI, re.S)
cats = re.findall(r'\[\s*"([a-z]+)"\s*,', m.group(1)) if m else []
check("A1 Diagnostics is the first category", bool(cats) and cats[0] == "diagnostics", cats[:3])
check("A2 Info is still last", bool(cats) and cats[-1] == "info", cats[-1:])

# ---- B. Info -----------------------------------------------------------------
check("B1 the author is the handle, linked to GitHub",
      '>@jagones84</a>' in UI and "Giovanni J. Agones" not in UI
      and "https://github.com/jagones84" in UI)
check("B2 the values still come from the live self report (no hardcoded home)",
      'pick("repo_path", "repo")' in UI and 'pick("data_dir", "data")' in UI
      and "/home/jagones" not in UI)

# ---- C. memory moved ---------------------------------------------------------
check("C1 the memory manager is inside Improvements",
      UI.index('id="memQuery"') < UI.index('data-cat="rules"'))
check("C2 opening Improvements loads it",
      'if (typeof loadMemories === "function") loadMemories();' in UI)
check("C3 Rules no longer loads the memory panel", 'loadRules(); loadMemories();' not in UI)

# ---- D. tools prose -> tooltip ----------------------------------------------
check("D1 the FULL/exclusive/nucleus rules live in a title",
      'class="set-t" title="FULL = never ask for ordinary tools.' in UI)
check("D2 they are no longer a visible paragraph",
      '<div class="remaining" style="margin-bottom:8px"><b>FULL</b>' not in UI)
check("D3 the category policy explanation is a tooltip too",
      'class="set-t" title="Click a policy to cycle AUTO' in UI)
check("D4 the origin sections are one short line",
      '</b> (" + count + ")</summary>' in UI)

# ---- E. constructed cards ----------------------------------------------------
check("E1 no 'Structured settings' heading",
      "Structured settings" not in UI)
check("E2 the section help is a tooltip",
      "'<div class=\"set-t\"' + (sec.help ? ' title=\"' + _attr(sec.help) + '\"' : \"\")" in UI)
check("E3 save and Automate share one row", 'acts.appendChild(auto)' in UI
      and ".set-acts { display: flex;" in UI)

# ---- F. hooks ----------------------------------------------------------------
check("F1 the intro paragraph is gone", "Deterministic commands run before or after tool calls. A <b>PreToolUse</b>" not in UI)
check("F2 the rule survives in the title",
      'title="Deterministic commands run before/after tool calls' in UI)
check("F3 the source folded into the header line", "overlay wins" in UI and "source: <code>" not in UI)

# ---- G. MCP ------------------------------------------------------------------
check("G1 the read order is stated once", "read order → <code>config/mcp_clients.yaml</code>" in UI)
check("G2 the env card says what it is, not which panel owns what",
      '"title": "Env files · ${VAR} lookup"' in SETTINGS
      and "The clients themselves are managed by Settings" not in SETTINGS)

# ---- H. rules paths ----------------------------------------------------------
check("H1 no scope letter glued to a path", 'files.push("G " + f)' not in UI and '_rf("G", f)' in UI)

# ---- I. memory status --------------------------------------------------------
check("I1 the idle state prints no kind ledger",
      'Object.keys(kinds).map(k => k + ": " + kinds[k])' not in UI)
check("I2 purge answers with a toast, not a permanent line",
      'toast("purged " + ((r && r.removed) || 0), "ok")' in UI)
check("I3 forget answers with a toast too",
      'toast("memory deleted ("' in UI)

print("\nv641: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
