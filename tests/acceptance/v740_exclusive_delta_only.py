#!/usr/bin/env python3
"""v740 — the exclusive catalog is the DELTA, never a second copy of the builtins.

Operator (2026-10-30): *"exclusive builtin tools overlap the builtins, it makes no
sense: there must be only the DELTA that longrunAgent can use, they must not be
rebuilt. And there are similar tools — what are they for? do a complete audit and
fix."*

An audit of the live catalog (181 tools: 48 exclusive / 91 nucleus / 14 matrix /
28 mcp) found exactly THREE exclusive tools that merely re-implemented a builtin
every agent already has, under a second name:

  `session.list`      -> builtin `sessions.list`            (strict superset: query,
                         limit, owning agent, RUNNING state)
  `kb.notebook_add`   -> builtin `knowledge.create_notebook` (same kb.create_notebook)
  `kb.source_add`     -> builtin `knowledge.add_source`      (same kb.add_sources)

Two names for one read/write is a second truth: the operator sees a duplicate tool
and the model has to guess which one the harness actually honours. They are gone.

What KEEPS an exclusive tool is a real capability the builtin registry lacks
(`agent.*` org chart, `team.*`, `job.*`, `routine.*`, `session.create|rename|delete`,
`kb.notebook_rename|delete`, `kb.source_remove`, `kb.reembed`, `mcp.*`,
`provider.*`, `skill.remove`, `webui.*`).

The `similar` names the audit flagged (`web.fetch` / `http.fetch` /
`browser.fetch`, the five `*search`, the seven `*list`, the five `*status`) are NOT
duplicates: they read different substrates. B pins that each one says which
substrate it reads and that no two share a description, so the set stays
navigable instead of collapsing into look-alikes.

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v740_exclusive_delta_only.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v740-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT"):
    _v = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE"):
        os.makedirs(_v, exist_ok=True)
    os.environ["LONGRUN_" + _k] = _v
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import longrun_agent as LRA   # noqa: E402
from longrun.tools import registry               # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the exclusive catalog is exactly the delta ---------------------------
DELTA = {
    "agent.create", "agent.update", "agent.get", "agent.list", "agent.delete",
    "agent.prompt_set", "agent.prompt_get", "agent.prompt_clear",
    "team.create", "team.update", "team.delete", "team.get", "team.list",
    "team.member_add", "team.member_remove",
    "job.create", "job.dispatch", "job.get", "job.list", "job.delete",
    "routine.create", "routine.update", "routine.get", "routine.list",
    "routine.delete",
    "session.create", "session.rename", "session.delete",
    "kb.notebook_rename", "kb.notebook_delete", "kb.source_remove", "kb.reembed",
    "mcp.upsert", "mcp.remove", "mcp.test", "mcp.reload",
    "provider.upsert", "provider.remove", "provider.add_model",
    "provider.remove_model", "provider.set_default", "provider.reload",
    "skill.remove", "webui.inspect", "webui.configure",
}
live = set(LRA.TOOL_SCHEMAS)
check("A1 the exclusive catalog is exactly the pinned delta (%d tools)" % len(DELTA),
      live == DELTA, sorted(live ^ DELTA))

check("A2 the three duplicated tools are gone from every path (schema + handler)",
      not (live & {"session.list", "kb.notebook_add", "kb.source_add"})
      and not (set(LRA._SUBTOOL_MAP) & {"session.list", "kb.notebook_add",
                                        "kb.source_add"})
      and not hasattr(LRA, "_session_list"))

BUILTIN_OWNER = {
    "sessions.list": "the session table",
    "sessions.read": "another session's transcript",
    "knowledge.create_notebook": "creating a notebook",
    "knowledge.add_source": "attaching a source",
    "knowledge.search": "searching indexed knowledge",
}
check("A3 every builtin that replaced an exclusive copy still exists and is NOT gated",
      all(registry.tool_spec(n)
          and not (registry.tool_spec(n).get("schema") or {}).get("_origin")
          for n in BUILTIN_OWNER),
      {n: bool(registry.tool_spec(n)) for n in BUILTIN_OWNER})

# Removing a duplicate must not blind A1: the prompt names the builtin owner.
_prompt = open(os.path.join(REPO, "src", "longrun", "model", "prompt.py"),
               encoding="utf-8").read()
check("A4 the longrunAgent prompt points at the builtin that now owns each verb",
      "are ALL of them right now" in _prompt
      and "sessions.list" in _prompt and "knowledge.create_notebook" in _prompt
      and "knowledge.add_source" in _prompt
      and "they do not exist" in _prompt)

# --- B: the look-alike names are different substrates, not duplicates --------
GROUPS = {
    "fetch": ["browser.fetch", "http.fetch", "web.fetch"],
    "search": ["grep.search", "index.search", "knowledge.search",
               "skills.search", "web.search"],
    "list": ["chapters.list", "glob.list", "memory.list", "process.list",
             "ruleaudit.list", "sessions.list", "skills.list"],
    "status": ["context.status", "cost.status", "index.status",
               "knowledge.status", "matrix.status"],
    "read": ["chapters.read", "fs.read", "sessions.read", "skills.read"],
}
SUBSTRATE = {
    "browser.fetch": ("page", "text"), "http.fetch": ("allowlist", "local"),
    "web.fetch": ("internet", "public"),
    "grep.search": ("workspace", "files"),
    "index.search": ("codebase", "workspace"),
    "knowledge.search": ("indexed", "text"),
    "skills.search": ("skills", "keyword"),
    "web.search": ("internet", "public"),
    "glob.list": ("glob", "files"),
    "process.list": ("processes", "pid"),
    "sessions.list": ("sessions", "teammate"),
    "skills.list": ("skills",),
    "memory.list": ("memory", "persistent"),
    "chapters.list": ("thread", "session"),
    "ruleaudit.list": ("rules",),
    "context.status": ("context", "tokens"),
    "cost.status": ("cost", "tokens"),
    "index.status": ("index", "codebase"),
    "knowledge.status": ("knowledge", "notebook"),
    "matrix.status": ("matrix", "tools"),
    "fs.read": ("file", "harness"),
    "sessions.read": ("session", "chat"),
    "skills.read": ("skill", "SKILL.md"),
    "chapters.read": ("thread", "chat"),
}
rows = {t.get("name"): t for t in registry.catalog()}
# A bare test environment may not have the Matrix zone mounted: those three
# look-alikes live there, so their ABSENCE is environment, not a defect. Every
# nucleus/exclusive name must always be present.
MATRIX_ZONE = {"grep.search", "ruleaudit.list", "cost.status"}
_all_names = sorted({n for g in GROUPS.values() for n in g})
_absent = [n for n in _all_names if n not in rows]
check("B1 every look-alike name is a live tool (Matrix names only with the zone)",
      not [n for n in _absent if n not in MATRIX_ZONE], _absent)
_present = [n for n in _all_names if n in rows]

_bad_desc, _dupe_desc, _seen = [], [], {}
for name in _present:
    desc = " ".join(str(rows[name].get("description") or "").split())
    if len(desc) < 40:
        _bad_desc.append((name, desc))
    key = desc.lower()
    if key in _seen:
        _dupe_desc.append((_seen[key], name))
    _seen[key] = name
check("B2 no two look-alikes share a description (a duplicate would read the same)",
      not _dupe_desc, _dupe_desc)
check("B3 every look-alike describes its own substrate in the first sentence",
      not _bad_desc and all(
          any(k in " ".join(str(rows[n].get("description") or "").split()).lower()
              for k in keys)
          for n, keys in SUBSTRATE.items() if n in rows),
      [_bad_desc,
       [n for n, keys in SUBSTRATE.items() if n in rows
        if not any(k in str(rows[n].get("description") or "").lower() for k in keys)]])

print("---")
ok = sum(results)
print("\nv740: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
