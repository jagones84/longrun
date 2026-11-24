#!/usr/bin/env python3
"""v1301 — ONE search across every discovery library (2026-11-24, operator).

The prompt must never carry a list of tools/skills/plugins; it must carry the
RECIPE. This pins the unified search that makes the recipe sufficient:

  A  `self {action:'tools', scope:'all', query:...}` answers a MERGED ranked list
     over native tools, MCP tools, skills and plugins — every row names its kind
     and the call that opens it;
  B  each kind is served by the ranker that already OWNS it (tools_report,
     skills.search_skills, the plugin scan) — no second implementation;
  C  `scope:'skills'` / `scope:'plugins'` narrow the same search;
  D  `skills.search` blends the lexical score with a semantic cosine when the
     embedding backend is warm, and stays purely lexical when it is not;
  E  the discovery prompt advertises scope=all and still carries NO catalogue;
  F  the skills section states the REAL absolute path (harness repo, never the
     session workspace);
  G  `self.tools {query}` is HYBRID too: `semantic:true` finds a tool with no
     lexical overlap, `semantic:false` stays keyword-only, and the prompt names
     all three modes (keyword / semantic / hybrid) for tools AND skills.

Deterministic: no live model, no network, no external MCP client.
Run: python3 tests/acceptance/v1301_unified_search.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1301-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _server          # noqa: E402
from longrun.core import api_v02                    # noqa: E402
from longrun.tools import diag, registry, tools as T  # noqa: E402
from longrun.memory import memory as _memory, skills, semantic  # noqa: E402

# Deterministic: never start a configured external MCP client in a test.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---------------------------------------------------------------- A: scope=all --
r = T.execute("self", {"action": "tools", "scope": "all", "query": "read a file"})
u = r.get("tools") or {}
rows = u.get("results") or []
check("A1 scope=all answers a merged ranked list",
      u.get("ok") is True and isinstance(rows, list) and len(rows) > 0, u)
check("A2 every row names its kind and the call that opens it",
      rows and all(x.get("kind") in ("tool", "mcp", "skill", "plugin") for x in rows)
      and all(x.get("where") for x in rows))
check("A3 kind counts travel with the answer",
      isinstance(u.get("counts"), dict) and set(u.get("counts") or {}) <=
      {"tool", "mcp", "skill", "plugin"}, u.get("counts"))

# ------------------------------------------------- B: each kind served by owner --
t = diag.tools_report(query="read a file")
tool_names = [x["name"] for x in rows if x["kind"] == "tool"]
check("B1 the tool half is exactly tools_report's ranking",
      tool_names == (t.get("native") or [])[:len(tool_names)], tool_names[:5])

sk = skills.search_skills("brainstorming", limit=5)
check("B2 the skills tool finds skills that self.tools alone misses",
      len(sk) > 0 and "brainstorming" in (sk[0].get("name") or ""), sk[:2])
u2 = T.execute("self", {"action": "tools", "scope": "all", "query": "brainstorming"})
kinds2 = {x["kind"] for x in ((u2.get("tools") or {}).get("results") or [])}
check("B3 scope=all surfaces the matching SKILL (merged world)", "skill" in kinds2, kinds2)

# ------------------------------------------------------------- C: narrowed scope --
u3 = T.execute("self", {"action": "tools", "scope": "skills", "query": "brainstorming"})
k3 = {x["kind"] for x in ((u3.get("tools") or {}).get("results") or [])}
check("C1 scope=skills returns skills only", k3 == {"skill"}, k3)
u4 = T.execute("self", {"action": "tools", "scope": "plugins", "query": "pdf"})
k4 = {x["kind"] for x in ((u4.get("tools") or {}).get("results") or [])}
check("C2 scope=plugins returns plugins only (empty is valid)", k4 <= {"plugin"}, k4)
u5 = T.execute("self", {"action": "tools", "query": "read a file"})
check("C3 the default scope stays the historical tools answer",
      "native" in (u5.get("tools") or {}) and "results" not in (u5.get("tools") or {}))

# ----------------------------------------------------- D: hybrid skills ranking --
import inspect                                        # noqa: E402
check("D1 search_skills accepts the semantic switch",
      "semantic" in inspect.signature(skills.search_skills).parameters)
lex = skills.search_skills("connect dgx spark", limit=5, semantic=False)
check("D2 lexical-only still ranks the keyword match first",
      lex and "dgx" in lex[0]["name"], lex[:1])
check("D3 the semantic half never loads the model inside a search",
      # 2026-11-24: the warm-only cosine has ONE owner (`memory.semantic`) because
      # `self.tools {query}` blends the same half over its own catalogue.
      "_get_embedder" not in inspect.getsource(semantic.ready)
      and "_EMBEDDER" in inspect.getsource(semantic.ready))

# ---------------------------------------------------------------- E: the prompt --
tctx = api_v02.tool_context()
check("E1 the discovery recipe advertises scope=all",
      'scope:"all"' in tctx and "self.tools {query:" in tctx)
check("E2 the prompt still carries NO catalogue",
      "fs(" not in tctx and "shell(" not in tctx and "learned_" not in tctx)
check("E3 the tool recipe names all three modes (keyword / semantic / hybrid)",
      "KEYWORD" in tctx and "semantic:true" in tctx and "HYBRID" in tctx)
check("E4 the skills block says the library is never read whole to find one",
      "never read the whole library" in skills.skills_context())

# ------------------------------------------------------------ F: the skills path --
_texts = __import__("longrun.model.prompt", fromlist=["x"]).section_texts(sess="a2")
_sk = _texts.get("skills") or ""
check("F1 the skills section states the REAL harness path",
      skills.SKILLS_DIR in _sk and "<category>/<name>/SKILL.md" in _sk, _sk[:200])
check("F2 it never claims the skills live in the session workspace",
      "workspace>" not in _sk and "<workspace" not in _sk)
check("F3 the system prompt still builds end to end",
      bool(_server._system_prompt(None)))
check("F4 the skills block names keyword + semantic + hybrid",
      "HYBRID" in _sk and "SEMANTIC" in _sk and "keyword" in _sk, _sk[:200])
check("F5 the skills POLICY says the library is searched, never enumerated",
      "Never enumerate" in _server._system_prompt(None))

# ------------------------------------------------- G: hybrid TOOL ranking ----
check("G1 tools_report accepts the semantic switch",
      "semantic" in inspect.signature(diag.tools_report).parameters)
check("G2 search_all forwards it (scope=all is ONE search, not a second path)",
      "semantic" in inspect.signature(diag.search_all).parameters)

_orig_emb = getattr(_memory, "_EMBEDDER", None)
_orig_batch = _memory._embed_batch
semantic._CACHE.clear()


def _fake_batch(texts, vocab=None):
    # Deterministic 'embeddings': the probe query and fs.read share one axis, every
    # other text the other — so ANY hit for the probe is the semantic half alone.
    out = []
    for t in texts:
        tl = str(t).lower()
        out.append([1.0, 0.0] if ("photonbeam" in tl or tl.startswith("fs.read "))
                   else [0.0, 1.0])
    return out


_memory._EMBEDDER = object()
_memory._embed_batch = _fake_batch
try:
    lex_only = diag.tools_report(query="photonbeam", semantic=False)
    hybrid = diag.tools_report(query="photonbeam", semantic=True)
    merged = diag.search_all("photonbeam", limit=5, semantic=True)
finally:
    _memory._EMBEDDER = _orig_emb
    _memory._embed_batch = _orig_batch
    semantic._CACHE.clear()
check("G3 keyword-only finds nothing for a word no tool carries",
      (lex_only.get("native") or []) == [] and "semantic" not in lex_only,
      lex_only.get("native"))
check("G4 the hybrid rank surfaces the SEMANTIC match (no lexical overlap)",
      "fs.read" in (hybrid.get("native") or []) and hybrid.get("semantic") is True,
      hybrid.get("native"))
check("G5 scope=all carries the same hybrid tool hit",
      any(r.get("kind") == "tool" and r.get("name") == "fs.read"
          for r in (merged.get("results") or [])), merged.get("results"))

print("\n---\nv1301: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
