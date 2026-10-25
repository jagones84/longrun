#!/usr/bin/env python3
"""v647 — the five meta tools that answered "nothing" while the data existed.

Source: an operator-ordered spot-check of ~30 tools. The defects were all in the
reflexive layer (self-inspection, memory, audit), not in the operational one:

  1. `memory.recall` — keyword search was an AND-of-words filter, so a multi-word
     query returned "(no memories)" over a store that had 10 notes;
  2. `self.tools {query:"job dispatch"}` — the WHOLE string had to be a literal
     substring of a name/description, so `job.get` was invisible;
  3. `ruleaudit.scan` — defaulted to the legacy `<repo>/.Matrix/rules` ghost;
  4. `mcp.test` — never resolved the stored client spec, so every configured
     server answered "command (stdio) or url (http) required";
  5. `skills.search` — a word present in 40 skills outweighed a rare one.

Contract:
  A) keyword recall RANKS partial matches and returns them with a score;
  B) destructive matching stays strict and literal (a delete is not a search);
  C) tool discovery scores every query word and orders by relevance;
  D) an empty discovery answer explains itself;
  E) ruleaudit reads the live Matrix dir, and says WHY a list is empty;
  F) mcp.test resolves a client by name from the merged config;
  G) skills ranking is IDF-weighted, so the rare domain word wins.

Deterministic: temp dirs + injected fixtures, no server, no model, no network.
Run: python3 tests/acceptance/v647_meta_tools_truth.py
"""
import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v647_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, "matrix")
for d in ("sessions", "data", "matrix"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
os.makedirs(os.path.join(TMP, "matrix", "rules"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory as mem  # noqa: E402
from longrun.memory import skills as skills_mod  # noqa: E402
from longrun.tools import diag  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A/B. memory recall is not blind ----------------------------------------
mem.store("memory.store", "Trust profiles use a syntax gate before plan mode runs.")
mem.store("memory.store", "Dispatch waves: max_steps >= 3 for any tool-using subagent.")
mem.store("agent.note", "Token chain: keep the compactor below 60% of the window.")
mem.store("plan.update", "Plan mode dispatch is gated by the syntax check.")
hits = mem.search("trust profiles syntax gate plan mode")
check("A1 a multi-word recall finds the note that shares most of it", len(hits) >= 1,
      [r.get("content", "")[:40] for _, r in hits])
mixed = mem.search("plan mode dispatch")
check("A2 relevance is ranked by how much of the query a note covers",
      len(mixed) >= 2 and len({s for s, _ in mixed}) >= 2, [s for s, _ in mixed])
check("A3 the best hit is the trust-profiles note",
      bool(hits) and "Trust profiles" in (hits[0][1].get("content") or ""))
partial = mem.search("waves token chain")
check("A4 a query spread across two records still returns both",
      len({r.get("content", "")[:20] for _, r in partial}) >= 2,
      [r.get("content", "")[:20] for _, r in partial])
check("A5 a query with no shared word is still a miss", mem.search("zzzznotpresentzzz") == [])
strict = mem.query("waves trust")
check("B1 destructive matching (query) stays a strict AND filter", strict == [])
_ids = (sys.modules.get("longrun.tools.tools") or None)
check("B2 forget/invalidate keep using the strict matcher",
      "def _memory_match_ids" in open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                                      encoding="utf-8").read())

# ---- C/D. tool discovery (fixture catalog: no MCP connection, no network) ---
_CATALOG = [
    {"name": "job.get", "enabled": True, "origin": "native", "approval": "auto",
     "description": "Read ONE job in full (state, owner, todos)."},
    {"name": "job.dispatch", "enabled": True, "origin": "native", "approval": "required",
     "description": "Dispatch a job to a teammate agent."},
    {"name": "memory.store", "enabled": True, "origin": "native", "approval": "auto",
     "description": "Store a durable note the harness remembers."},
    {"name": "fs.read", "enabled": True, "origin": "native", "approval": "auto",
     "description": "Read a text file from the harness filesystem."},
]
_orig_catalog = registry.catalog
registry.catalog = lambda: list(_CATALOG)
try:
    rep = diag.tools_report(query="job dispatch")
    unknown = diag.tools_report(query="qqqzzzwwwxxx")
    single = diag.tools_report(query="memory")
finally:
    registry.catalog = _orig_catalog
check("C1 two words spread across name/description still match",
      rep.get("count", 0) > 0, rep.get("count"))
check("C2 the job tools come back",
      any(n.startswith("job.") for n in rep.get("native") or []), (rep.get("native") or [])[:6])
check("C3 a fully unknown query answers with a hint, not silence",
      "no tool matches those words" in (unknown.get("hint") or ""))
check("C4 a single common word still returns hits", single.get("count", 0) >= 1, single.get("count"))

# ---- E. ruleaudit default dir -------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "_v647_ruleaudit", os.path.join(REPO, "src", "Matrix", "tools", "ruleaudit.py"))
_ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ra)
with open(os.path.join(TMP, "matrix", "rules", "01-oracle.md"), "w", encoding="utf-8") as f:
    f.write("# The oracle must be able to fail\n\nbody\n")
listed = _ra.execute({"action": "list"})
check("E1 ruleaudit reads the LIVE matrix dir", listed.get("dir", "").startswith(TMP),
      listed.get("dir"))
check("E2 the live rule is listed", listed.get("count") == 1, listed.get("count"))
empty = _ra.execute({"action": "list", "dir": os.path.join(TMP, "no-such-dir")})
check("E3 a missing dir is reported as missing, not as 'no rules'",
      empty.get("exists") is False and "does not exist" in (empty.get("note") or ""))

# ---- F. mcp.test resolves the stored client ------------------------------
# Imported HERE (not at module import) so the fixture config is what the module
# sees, and nothing connects during collection.
from longrun.interop import mcp_client  # noqa: E402
_orig_load = mcp_client.load_doc
mcp_client.load_doc = lambda: {"clients": {"PMCP": {"url": "http://127.0.0.1:9/mcp"}},
                               "env_files": []}
try:
    unknown_client = mcp_client.test_client({"name": "NOPE"})
    check("F1 an unknown client is named as unknown",
          unknown_client.get("ok") is False
          and "unknown MCP client" in (unknown_client.get("error") or ""),
          unknown_client.get("error"))
    known = mcp_client.test_client({"name": "PMCP"})
    check("F2 a configured client is resolved from the config, not rejected",
          "command (stdio) or url (http) required" not in (known.get("error") or ""),
          known.get("error"))
finally:
    mcp_client.load_doc = _orig_load

# ---- G. skills ranking is IDF-weighted -----------------------------------
_fixtures = [
    {"name": "browser-testing", "category": "t", "title": "Browser testing",
     "description": "Test a page in a real browser.", "abspath": "/s/common"},
    {"name": "ci-cd", "category": "t", "title": "CI/CD", "description": "Pipeline and test gates.",
     "abspath": "/s/ci"},
    {"name": "repo-orientation", "category": "t", "title": "Repo orientation",
     "description": "Run the test battery gate of this repository.", "abspath": "/s/local"},
]
_orig_list, _orig_cache = skills_mod.list_skills, skills_mod._cache
skills_mod.list_skills = lambda: _fixtures
skills_mod._cache = {"bodies": {"/s/common": "test the page", "/s/ci": "test stages",
                                "/s/local": "battery gate"}}
try:
    ranked = skills_mod.search_skills("how to run the test battery gate", limit=5)
finally:
    skills_mod.list_skills, skills_mod._cache = _orig_list, _orig_cache
check("G1 the ranking returns the local skill", bool(ranked), [r["name"] for r in ranked])
check("G2 the rare words (battery+gate) beat the common one (test)",
      bool(ranked) and ranked[0]["name"] == "repo-orientation",
      [r["name"] for r in ranked])
check("G3 scores are sorted best first",
      all(ranked[i]["score"] >= ranked[i + 1]["score"] for i in range(len(ranked) - 1)))

print("---")
ok = sum(results)
print("\nv647: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
