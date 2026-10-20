#!/usr/bin/env python3
"""v452 — JAG-451 UI/knowledge round: subagents failover picker, skills provenance,
org-chart -> Agents-panel focus, and session-scoped knowledge retrieval.

Operator feedback pinned here:
  1) "failover model shall also be selectable with menus. LIMITS graphics is horrible."
  2) "self-evolving skills ... are they marked as self-generated clearly in the
     Skills panel and separated from the normal folder?"
  3) "clicking (single click) in the Control tab to an agent in the ORG CHART shall
     also open it and highlight in the AGENTS panel so the user is ready to edit it."
  4) "why uses pdf tools to analyze the pdf if it was embedded in the session DB?"

Contract:
  A) SUBAGENTS UI — failover is a menu picker (not a comma text box); LIMITS uses a grid.
  B) SKILLS       — list_skills flags `auto` (skills/created); the panel badges +
                    separates self-generated / built-in / user.
  C) ORG CHART    — a single click also focuses (highlights + scrolls) the agent in
                    the Agents table.
  D) SESSION KB   — the `knowledge` tool searches the SESSION notebook first (then
                    global), and the model is told an attached doc is already indexed.

Deterministic, no model, no server. Run: python3 tests/acceptance/v452_ui_kb_round.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


idx = read("webui", "index.html")
orbit = read("src", "longrun", "orbit", "web", "orbit.html")
skills_src = read("src", "longrun", "memory", "skills.py")
tools_src = read("src", "longrun", "tools", "tools.py")
reg_src = read("src", "longrun", "tools", "registry.py")
api_src = read("src", "longrun", "core", "api_v02.py")
improve_src = read("src", "longrun", "util", "improve.py")
agent_src = read("src", "longrun", "agent", "agent.py")
toolsyaml = read("config", "tools.yaml")


# ---- A) subagents single fallback picker + limits grid ----------------------
check("A1 one fallback dropdown replaces the chips and add button",
      'id="subFallbackPick"' in idx and 'id="subFallbacksList"' not in idx
      and 'data-call="subAddFallback"' not in idx and 'id="subFallbacks"' not in idx)
check("A2 choosing a fallback saves it automatically, with None as the empty value",
      "fallbackPick.onchange" in idx and "None — no fallback" in idx
      and "function subAddFallback" not in idx and "function subRenderFallbacks" not in idx)
check("A3 saving writes the selected zero-or-one fallback list",
      "fallbacks: (_subFallbacks || [])" in idx and "_subFallbacks = ref ? [ref] : []" in idx)
check("A4 LIMITS uses the sub-limits grid (not the ugly hrow)",
      ".sub-limits {" in idx and 'class="sub-limits"' in idx
      and 'class="hrow"' not in idx.split('data-cat="subagents"')[1].split("sw-cat")[0])
# JS syntax guard: a `(a-b) =>` arrow param (arithmetic in the binding) is invalid
# JS and kills the WHOLE single-script UI. Caught live in Chrome, never by the
# static string checks — so pin it here (no node on the box, so a regex guard).
check("A5 no arrow-function parameter is an arithmetic expression",
      not re.search(r"\([A-Za-z_$][\w$.]*\s*[-+*/]\s*[A-Za-z_$][\w$.]*\)\s*=>", idx),
      (re.search(r"\([A-Za-z_$][\w$.]*\s*[-+*/]\s*[A-Za-z_$][\w$.]*\)\s*=>", idx) or [""])[0])


# ---- B) skills provenance --------------------------------------------------
check("B1 list_skills flags auto-generated skills",
      '"auto": cat == "created"' in skills_src)
check("B2 the panel badges + separates self-generated skills",
      "sk-badge" in idx and "sk-auto" in idx
      and 'section("auto", "Self-generated"' in idx and "sk-core" in idx and "sk-user" in idx)
# JAG-511: nothing under skills/<category>/ is a harness built-in — it ships in the
# repo but is operator-added content. The panel calls it "registered"; only the
# machine-made buckets keep a generated label, and Matrix is its own section.
check("B3 the summary counts self-generated vs matrix vs uploaded vs registered",
      "self-generated · " in idx and "registered" in idx and "matrix" in idx
      and 'sk-core">built-in' not in idx)


# ---- C) org chart -> Agents panel focus ------------------------------------
check("C1 AgentsView has a focusAgent() that expands the team group",
      "focusAgent(sid)" in orbit and "this.closed.delete(id)" in orbit)
check("C2 it highlights + scrolls to the row",
      "_applyFocus()" in orbit and "classList.add(\"rowsel\")" in orbit
      and "scrollIntoView" in orbit)
check("C3 the rowsel style exists",
      "tr.rowsel" in orbit)
check("C4 a single org-chart click also focuses the agent in the Agents panel",
      "this.agents.focusAgent(a.session)" in orbit)


# ---- D) session-scoped knowledge retrieval --------------------------------
check("D1 the knowledge tool searches the session notebook first",
      "session=sid,\n                        include_text=True)" in tools_src
      and "sid = str(run_id or \"\").strip() or None" in tools_src
      and "session must match the current chat" in tools_src)
check("D2 it falls back to a global search when the session has no hit",
      "if not res.get(\"results\"):" in tools_src
      and "kb.search(query, None, k=k, kind=args.get(\"kind\"), include_text=True)" in tools_src)
check("D3 an explicit notebook still wins",
      "res = kb.search(query, notebook, k=k, kind=args.get(\"kind\"), include_text=True)" in tools_src)
check("D4 the tool schema says chat attachments are session-indexed and must not be re-added",
      "auto-indexed" in reg_src and "session notebook" in reg_src
      and "do not" in reg_src.lower() and "read_source" in reg_src)
check("D5 the attach preamble tells the model to use the knowledge tool",
      "ALREADY indexed into THIS session's knowledge" in idx
      and 'action":"search"' in idx)


# ---- E) subagents auto-save + Tools & approvals ----------------------------
check("E1 the useless 'save subagents' button is gone (auto-save)",
      'data-call="saveSubagents"' not in idx and "function subSaveSoon" in idx
      and "setTimeout(() => saveSubagents(false)" in idx)
check("E2 the category is renamed Tools & approvals",
      '["tools", "Tools & approvals"]' in idx and "Tools &amp; approvals" in idx
      and '["tools", "Tool policy"]' not in idx)
check("E3 the panel renders an approval-by-category card",
      "Approval by category" in idx and 'data-kind="' in idx and "KINDS.map" in idx)
check("E4 cycling a category posts approvals.kinds",
      "{ approvals: { kinds: { [b.dataset.kind]: next } } }" in idx)
check("E5 the backend accepts approvals.kinds (validated)",
      'body["approvals"].get("kinds")' in api_src
      and 'v in ("auto", "required", "denied")' in api_src)
check("E6 config ships the category defaults",
      "kinds:" in toolsyaml and "skills:" in toolsyaml and "proposals:" in toolsyaml)
check("E7 improve exposes approval_kind()",
      "def approval_kind(name)" in improve_src
      and "approvals" in improve_src)
check("E8 the loop honours memory + skills policy; the tool honours proposals",
      'improve_mod.approval_kind("memory")' in agent_src
      and 'improve_mod.approval_kind("skills")' in agent_src
      and 'improve.approval_kind("proposals")' in tools_src)
check("E9 skills=AUTO runs the verify+promote pipeline; DENIED skips",
      "evolve=(k_skills == \"auto\")" in agent_src
      and "def mine_once(note=\"\", evolve=False)" in improve_src)

# Behavioral: approval_kind reads approvals.kinds from the registry config.
try:
    from longrun.util import improve as _imp
    from longrun.tools import registry as _reg
    _orig_lc = _reg.load_config
    _reg.load_config = lambda reload=False: {"approvals": {"kinds": {"skills": "denied", "proposals": "auto"}}}
    try:
        check("E10 approval_kind reads the configured category policy",
              _imp.approval_kind("skills") == "denied"
              and _imp.approval_kind("proposals") == "auto"
              and _imp.approval_kind("unknown") == "")
    finally:
        _reg.load_config = _orig_lc
except Exception as e:  # noqa: BLE001
    check("E10 approval_kind reads the configured category policy", False, str(e))


print("---")
ok = sum(results)
print("\nv452: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
