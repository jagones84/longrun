#!/usr/bin/env python3
"""v198 — skills/tools AWARENESS (deterministic, no model).

Proves the chat system prompt actually tells the model:
  A) WHICH tools it has (registry block) and that only enabled ones are callable;
  B) WHICH skills are installed (name + one-line description) and that the body
     loads on demand via the `skills` tool;
  C) that it must SCAN the list and LOAD a matching skill before solving;
  D) how it answers capability questions (from the prompt / `self`, not shell);
  E) how to reach MCP tools (<client>__<tool>).

Run:  python3 tests/v198_skills_tools_awareness.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-198-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.memory import skills  # noqa: E402
from longrun.tools import tools  # noqa: E402

# Keep prompt construction deterministic; this acceptance test covers the local
# registry and must not start configured external MCP clients.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sp = _srv._system_prompt(None)

# ---- A: tools are declared ----
# JAG-513: the prompt no longer DUMPS the registry; it carries the discovery
# contract (`self {action:"tools"}`) plus the enabled NAMES, grouped.
check("A1 prompt carries the tool-discovery contract",
      "Tool discovery" in sp and 'action:"tools"' in sp, "")
names = [t["name"] for t in registry.catalog()]
check("A2 a `self` tool exists (self-knowledge)", "self" in names or "self.info" in names, str(names)[:140])
check("A3 a `skills` tool exists", "skills" in names or "skills.list" in names, str(names)[:140])
check("A4 registry block lists the enabled names, grouped by namespace",
      "fs{" in sp and "shell{" in sp, "")

# ---- B: skills known WITHOUT a discovery round-trip ----
check("B1 skills policy present", "installed skill library" in sp, "")
sk = skills.list_skills()
check("B2 at least one skill installed", len(sk) > 0, "count=%d" % len(sk))
if sk:
    _cats = sorted({s["category"] for s in sk})
    check("B3 prompt orients on the installed library (count + categories)",
          str(len(sk)) in sp and _cats[0] in sp, "cats=%s" % _cats[:3])
    check("B4 skills block tells HOW to find one (search/list/read)",
          '"action":"search"' in skills.skills_context()
          and '"action":"read"' in skills.skills_context(), "")
check("B5 skills index is bounded (not a dump)", len(skills.skills_context(max_chars=200)) <= 320,
      "len=%d" % len(skills.skills_context(max_chars=200)))
check("B6 a truncated index points to search",
      "search" in skills.skills_context(max_chars=200), "")

# ---- C: the model is told to SCAN and LOAD a skill ----
check("C1 policy tells the model to SCAN the list", "SCAN" in sp, "")
check("C2 policy tells how to LOAD one", "LOAD it with the `skills` tool" in sp, "")

# ---- D: capability questions answered from the prompt / self ----
check("D1 capability rule present", "answer FROM YOUR PROMPT" in sp, "")
check("D2 self-summary documents MCP tool naming", "<client>__<tool>" in sp, "")

# ---- E: memory policy ----
check("E1 memory policy present", "set_core" in sp and "memory" in sp.lower(), "")

# ---- F: skills are SEARCHABLE (progressive discovery, JAG-198) ----
check("F1 policy advertises the search action", '"action":"search"' in sp, "")
hits = skills.search_skills("connect dgx spark", limit=5)
check("F2 keyword search returns ranked skills", len(hits) > 0, "hits=%s" % [h["name"] for h in hits])
check("F3 best hit matches the query", bool(hits) and "dgx" in hits[0]["name"], str(hits[:1]))
res = tools.execute("skills", {"action": "search", "query": "connect dgx spark"})
check("F4 the `skills` tool exposes action=search",
      isinstance(res, dict) and res.get("ok") and res.get("count", 0) >= 1,
      "count=%s" % (res.get("count") if isinstance(res, dict) else res))
bad = tools.execute("skills", {"action": "search"})
check("F5 search without a query fails gracefully",
      isinstance(bad, dict) and bad.get("ok") is False, str(bad)[:80])

# ---- G: prompt budget — no truncated dump, no disabled-tools wall (JAG-202) ----
# JAG-350: the registry gained a native tool (`sessions`), so the ceiling moved
# from 17k to 18k. JAG-401 added the `knowledge` tool (GLOBAL notebooks + web
# discover), so the ceiling moves to 19k. JAG-431j added the `chapters` tool
# the session thread ledger), so it moves to 20k. JAG-431r9: legitimate runtime
# growth — a larger installed-skills index (~2.6k), accumulated memory lessons
# (~0.7k), and 26 PMCP tools (~1.8k) — pushed the composed prompt past 20k.
# Acceptance tests now stub external-tool discovery, so this test makes no PMCP
# connection. JAG-450 added the `dispatch` line to the chat tool contract (hand
# work to the org-chart team), so the ceiling moves to 22k. It still guards
# against a runaway dump / disabled-tools wall (skills index capped at 2600 chars,
# disabled list one line).
check("G1 composed system prompt is bounded (<22k chars)", len(sp) < 22000, "chars=%d" % len(sp))
_idx = skills.skills_context(max_chars=2600)
check("G2 the always-on skills index is bounded", len(_idx) <= 2760, "len=%d" % len(_idx))
_disabled_lines = [l for l in sp.splitlines() if "present but DISABLED" in l]
check("G3 disabled-tools footer is absent or compact",
      len("\n".join(_disabled_lines)) < 400,
      "footer_len=%d" % len("\n".join(_disabled_lines)))

# ---- H: skill-library health audit (JAG-203, read-only) ----
_aud = skills.audit_skills()
check("H1 audit counts the library", _aud.get("count") == len(sk), "count=%s" % _aud.get("count"))
_dupnames = {n for ns in _aud["duplicate_descriptions"].values() for n in ns}
check("H2 audit finds the duplicated MCP-builder description",
      {"mcp-builder", "mcp-server-builder-guide"} <= _dupnames, str(sorted(_dupnames))[:80])
_res_aud = tools.execute("skills", {"action": "audit"})
check("H3 the `skills` tool exposes action=audit",
      isinstance(_res_aud, dict) and _res_aud.get("ok") and "report" in _res_aud,
      str(_res_aud)[:80])

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
