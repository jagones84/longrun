#!/usr/bin/env python3
"""v850 — the lot-H audits are VISIBLE in the Settings panels (no second fetch).

The three blocks already travel in payloads the panels fetch (`/api/rules`,
`/api/tools`, `/api/skills`); before this test the WebUI ignored them, so the
operator could only see the advice through curl. Every check below pins a STATIC
fact of `webui/index.html` against the real backend surface, so a refactor that
drops the rendering — or re-introduces a second endpoint — fails here.

  A) rules doctor: a card that stays hidden while the corpus is clean;
  B) tools: the footprint is a button over the SAME payload, list on click;
  C) skills: the discovery suffix is read from the same fetch as the cache;
  D) each panel issues exactly ONE request for its own data;
  E) the backend keys and the functions behind them still exist.

Deterministic, no live model, no network, no server.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
API = _read("src", "longrun", "core", "api_v02.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _slice(src, start, end):
    i = src.find(start)
    j = src.find(end, i + 1) if i >= 0 else -1
    return src[i:j] if i >= 0 and j > i else ""


# --- A: rules doctor ---------------------------------------------------------
load_rules = _slice(HTML, "async function loadRules()", "async function saveRules(")
check("A1 the doctor card exists and starts hidden",
      'id="rulesDoctorCard" hidden' in HTML and 'id="rulesDoctor"' in HTML, "")
check("A2 it reads the audit from the SAME payload",
      "const _a = d.audit || {};" in load_rules, "")
check("A3 a clean corpus renders nothing",
      "_dc.hidden = !_n;" in load_rules, "")
check("A4 findings are listed with scope/file/line",
      'f.file || "") + (f.line ? ":" + f.line : "")' in load_rules, "")

# --- B: tool footprint -------------------------------------------------------
render_tools = _slice(HTML, "function renderTools(el, d) {", "el.querySelectorAll(\"button[data-pol]\")")
check("B1 the footprint button is built from d.footprint",
      "const _fp = (d && d.footprint) || null;" in render_tools
      and 'data-footprint' in render_tools, "")
check("B2 the list is collapsed until clicked, and says so to a screen reader",
      'id="toolsFootprint" class="card" hidden' in render_tools
      and "box.hidden = true" in render_tools
      and 'aria-expanded="false"' in render_tools
      and "setAttribute(\"aria-expanded\", \"true\")" in render_tools, "")
check("B3 the cost is the real index character count",
      "never_used_index_chars" in render_tools and "never_used" in render_tools, "")

# --- C: skill discovery ------------------------------------------------------
load_skills = _slice(HTML, "async function loadSkills()", "async function openSkillInEditor(")
check("C1 discovery comes from the cache fetch, not a second call",
      "_skillsDiscovery = d.discovery || null;" in load_skills, "")
check("C2 the summary shows never-opened and missing descriptions",
      "_skillsDiscovery.never_opened" in HTML and "_skillsDiscovery.missing_description" in HTML, "")

# --- D: one request per panel ------------------------------------------------
for label, block, needle in (
        ("rules", load_rules, 'api("GET", "/api/rules'),
        ("skills", load_skills, 'api("GET", "/api/skills')):
    check("D1 %s panel fetches its data exactly once" % label,
          block.count(needle) == 1, block.count(needle))

# --- E: the backend surface is still the same --------------------------------
check("E1 /api/rules still carries the audit",
      'st["audit"] = _RULES.audit(ws=ws)' in API, "")
check("E2 /api/tools still carries the footprint",
      '"footprint": registry.footprint()' in API, "")
check("E3 /api/skills still carries the discovery block",
      '"discovery": disc' in API, "")
RULES = _read("src", "longrun", "memory", "rules.py")
REG = _read("src", "longrun", "tools", "registry.py")
SKL = _read("src", "longrun", "memory", "skills.py")
check("E4 the three functions exist",
      "def audit(ws=None, max_bytes=None):" in RULES
      and "def footprint(days=30, now=None):" in REG
      and "def discovery(samples=None, limit=5):" in SKL, "")

print("\n%d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
