#!/usr/bin/env python3
"""v510 — tools are SELF-DESCRIBING and DISCOVERABLE, not dumped in the prompt (JAG-513).

The chat prompt used to carry the whole tool registry: every subtool with its
argument list, its approval policy and a description cut at the first sentence.
The model read the synopsis, still guessed the arguments, and the part that
mattered (fs.read's line range, knowledge's "do not re-add", improve's review
contract) had been thrown away by the truncation.

This locks the replacement contract:

  A1-A2  every tool (and every argument) carries an authoritative description;
  A3     the prompt carries the DISCOVERY contract + a compact name index, not
         the per-tool policy dump, and it says args is one JSON object;
  A4-A6  `self {action:"tools", tool:"<name>"}` returns the FULL input schema,
         `query` filters, an unknown name answers with suggestions;
  A7-A8  a call missing a REQUIRED argument fails with the argument name, its
         type and a valid example — never "empty command" or "outside roots";
  A9     a canonical `<ns>.<subtool>` description keeps the WHOLE usage text.

Deterministic: no live model, no network, no external MCP client.
Run: python3 tests/acceptance/v510_tool_discovery.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v510-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag             # noqa: E402
from longrun.tools import registry         # noqa: E402
from longrun.tools import tools as T       # noqa: E402

# Deterministic: never start a configured external MCP client in a test.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CAT = [t for t in registry.catalog() if t.get("name")]

# ------------------------------------------- A1/A2 the schemas describe ----
no_desc = [t["name"] for t in CAT if not (t.get("description") or "").strip()]
check("A1 every tool carries a description", not no_desc, no_desc[:8])

no_prop = []
for t in CAT:
    if "__" in t["name"]:
        continue  # external MCP schemas are the server's, not ours
    for k, v in ((t.get("inputSchema") or {}).get("properties") or {}).items():
        if not (isinstance(v, dict) and (v.get("description") or "").strip()):
            no_prop.append(t["name"] + "." + k)
check("A2 every argument carries a description", not no_prop, no_prop[:12])

fs_read = (registry.tool_spec("fs.read") or {}).get("schema") or {}
check("A2b fs.read documents the relative/absolute path contract",
      "RELATIVE" in (fs_read.get("properties", {}).get("path", {}).get("description") or ""),
      fs_read.get("properties", {}).get("path"))

# ------------------------------------------------- A3 the prompt block ----
from longrun.core import api_v02           # noqa: E402
tctx = api_v02.tool_context()
check("A3 prompt states the discovery contract instead of a registry dump",
      "Tool discovery" in tctx and 'self {action:"tools", tool:"<name>"}' in tctx
      and "approval=" not in tctx,
      "%d chars" % len(tctx))
check("A3b prompt states that args is ONE JSON object",
      "`args` is ALWAYS one JSON object" in tctx
      and '"args":{"path"' in tctx)
check("A3c prompt still names the enabled tools, grouped by namespace",
      "fs{" in tctx and "shell{" in tctx and "memory{" in tctx)
check("A3d the block is COMPACT (a name index, not a catalogue)",
      len(tctx) < 4000, "%d chars" % len(tctx))

# ------------------------------------------------- A4 the schema lookup ----
full = diag.tools_report(tool="fs.read")
tool = full.get("tool") or {}
check("A4 self{tool:'fs.read'} returns the FULL input schema",
      full.get("ok") is True and tool.get("required") == ["path"]
      and set(tool.get("properties") or {}) >= {"path", "start_line", "end_line"},
      sorted(tool.get("properties") or {}))
check("A4b it returns one valid example call",
      (tool.get("example_args") or {}).get("path"), tool.get("example_args"))
check("A4c it repeats the JSON-object protocol for THIS tool",
      '"tool":"fs.read"' in (full.get("hint") or ""), full.get("hint"))
# The routing the prompt tells the model to use: `self` with `tool`/`query`.
self_full = T.execute("self", {"tool": "fs.read"})
check("A4d self{tool:'fs.read'} routes to discovery WITHOUT an explicit action",
      (self_full.get("tools") or {}).get("tool", {}).get("name") == "fs.read",
      str(self_full.get("tools"))[:80])

# ---------------------------------------------------- A5 the query filter ----
res = diag.tools_report(query="memory")
names = res.get("native") or []
check("A5 query filters the index (a subset, and a real hit)",
      res.get("ok") is True and names and "memory.recall" in names
      and res.get("count") < len([t for t in CAT if "__" not in t["name"]]),
      "%d hits" % res.get("count"))
self_q = T.execute("self", {"query": "web"})
check("A5b self{query:'web'} filters the live index",
      self_q.get("tools", {}).get("ok") is True
      and "web.search" in (self_q.get("tools", {}).get("native") or []),
      self_q.get("tools", {}).get("native"))

# ------------------------------------------------ A6 unknown name teaches ----
bad = diag.tools_report(tool="totally.unknown")
check("A6 an unknown tool is an ERROR with a search hint",
      bad.get("ok") is False and "unknown tool" in (bad.get("error") or "")
      and "query" in (bad.get("hint") or ""), bad.get("error"))
alias = diag.tools_report(tool="exec").get("tool") or {}
check("A6b a UNIQUE bare subtool name resolves (exec -> shell.exec)",
      alias.get("name") == "shell.exec", alias.get("name"))

# ----------------------------------- A7/A8 a missing argument TEACHES the fix ----
miss = T._dispatch_execute("shell.exec", {})
check("A7 a call with no args names the REQUIRED argument",
      miss.get("ok") is False and miss.get("missing_args") == ["command"]
      and "'command'" in (miss.get("error") or "")
      and "Example call" in (miss.get("error") or ""),
      miss.get("error"))
miss2 = T._dispatch_execute("fs.read", {"start_line": 1})
check("A7b the same for fs.read (no path)",
      miss2.get("ok") is False and miss2.get("missing_args") == ["path"]
      and miss2.get("exit_code") == 64, miss2.get("error"))
ok_call = T._dispatch_execute("memory.recall", {"query": "v510"})
check("A8 a well-formed call is NOT blocked by the validator",
      ok_call.get("missing_args") is None, ok_call.get("error"))
self_schema = (registry.tool_spec("self") or {}).get("schema") or {}
check("A8b `self` advertises tool + query",
      {"tool", "query"} <= set(self_schema.get("properties") or {}))

# ------------------------------- A9 a canonical description is not truncated ----
k = (registry.tool_spec("knowledge.search") or {}).get("schema") or {}
check("A9 a canonical subtool keeps the WHOLE usage text (not the 1st sentence)",
      "Do NOT call" in (k.get("description") or ""), (k.get("description") or "")[:90])

print("---")
okc = sum(results)
print("\nv510: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
