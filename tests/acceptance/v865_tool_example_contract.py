#!/usr/bin/env python3
"""v865 — the tool contract a model is HANDED is usable (2026-11-07).

Live: a chat called `git.run` with `{}` and the usage error answered with

    Example call: {"action":"tool","tool":"git.run","args":{"args":"<e>"}}

`<e>` is the old example generator cutting the property description
("e.g. 'status --short'") at its first ".". A model that trusts the example
issues a second broken call, so the "failure that teaches" taught nothing.

This locks the replacement:

  A1  `git.run`'s discovered example is the value its schema spells out;
  A2  the usage error for an empty call carries that value, never `<e>`;
  A3  `git.run`'s description names the exact shape (`args` = one string);
  A4  GENERALLY: no native tool whose argument description starts with "e.g."
      is handed a `<placeholder>` as its example;
  A5  a plain description still degrades to a readable `<...|type>`;
  A6  enum / default / typed primitives are unchanged.

Deterministic: no live model, no network, no external MCP client.
Run: python3 tests/acceptance/v865_tool_example_contract.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v865-")
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


# ------------------------------------------- A1 the git example is a value ----
git_rep = diag.tools_report(tool="git.run") or {}
git_example = (git_rep.get("tool") or {}).get("example_args") or {}
check("A1 git.run's example is the subcommand its schema spells out",
      git_example.get("args") == "status --short", git_example)

# --------------------------------- A2 the usage error teaches a real call ----
miss = T._dispatch_execute("git.run", {})
err = str(miss.get("error") or "")
check("A2 an empty git.run call answers with a USABLE example",
      miss.get("ok") is False and "status --short" in err and "<e>" not in err,
      err[:220])

# ------------------------------- A3 the description names the nested shape ----
git_desc = ((registry.tool_spec("git.run") or {}).get("schema") or {}).get("description") or ""
check("A3 git.run documents that its ONE field is `args`, a plain string",
      '"args":"status --short"' in git_desc and "required field" in git_desc,
      git_desc[:200])

# ------------------- A4 no tool is handed a "<...>" for a spelled example ----
bad = []
for t in registry.catalog():
    name = t.get("name") or ""
    if not name or "__" in name:
        continue                      # external MCP schemas are the server's
    props = (t.get("inputSchema") or {}).get("properties") or {}
    spelled = [k for k, v in props.items()
               if isinstance(v, dict)
               and str(v.get("description") or "").strip().lower().startswith(("e.g.", "eg."))]
    if not spelled:
        continue
    ex = (diag.tools_report(tool=name).get("tool") or {}).get("example_args") or {}
    for key in spelled:
        val = str(ex.get(key) or "")
        if not val or val.startswith("<"):
            bad.append("%s.%s=%r" % (name, key, val))
check("A4 every argument that spells an example is handed THAT value", not bad, bad[:8])

# ------------------------------- A5/A6 the fallback behaviour is unchanged ----
_ex5 = diag._example({"type": "string",
                      "description": "the relative or absolute path of the file"})
check("A5 a plain description still degrades to a readable placeholder",
      _ex5.startswith("<the relative or absolute path") and _ex5.endswith(">"), _ex5)
check("A6 enum / default / typed primitives are untouched",
      diag._example({"type": "string", "enum": ["a", "b"]}) == "a"
      and diag._example({"type": "string", "default": "x"}) == "x"
      and diag._example({"type": "integer"}) == 1
      and diag._example({"type": "boolean"}) is False
      and diag._example({"type": "array"}) == []
      and diag._example({"type": "object"}) == {}, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
