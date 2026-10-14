#!/usr/bin/env python3
"""v253 — registry.catalog() crashed (and dropped the HTTP connection) when the
external MCP tool set changed between the two lookups (JAG-253).

`tool_names()` and `tool_spec()` each re-evaluated `_external_tools()`. While an
MCP server was (re)connecting the two views disagreed: a name was listed by
`tool_names()` but `tool_spec()` returned None -> `None["enabled"]` raised in
`catalog()` -> GET /api/status (and /api/tools) closed the socket with no reply.

Deterministic, no live server, no network. Run: python3 tests/v253_registry_catalog.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v253-")
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

# The baseline catalog is local-only; the flaky external set is injected below.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# baseline: the catalogue builds
try:
    cat = registry.catalog()
    check("catalog() returns a list", isinstance(cat, list), "n=%d" % len(cat))
    check("catalog() entries all carry an 'enabled' key",
          all("enabled" in t for t in cat))
except Exception as e:  # noqa: BLE001
    check("catalog() returns a list", False, repr(e))
    check("catalog() entries all carry an 'enabled' key", False, "n/a")

# THE BUG: external tool set flips between the two lookups.
_external = {"description": "x", "inputSchema": {"type": "object", "properties": {}}}
calls = {"n": 0}


def flaky():
    calls["n"] += 1
    return {"ext.flaky": _external} if calls["n"] == 1 else {}


orig = registry._external_tools
registry._external_tools = flaky
try:
    cat2 = registry.catalog()
    check("catalog() does not raise on a flaky external tool set",
          isinstance(cat2, list))
    names = [t["name"] for t in cat2]
    check("the flaky external tool is listed consistently",
          "ext.flaky" in names)
except Exception as e:  # noqa: BLE001
    check("catalog() does not raise on a flaky external tool set", False, repr(e))
    check("the flaky external tool is listed consistently", False, "crashed")
finally:
    registry._external_tools = orig

# JAG-254: a config entry for an external MCP tool must NOT be advertised when the
# server is absent (e.g. a clone without pmcp). It only supplies policy for when
# the tool actually exists.
registry._external_tools = lambda: {}
try:
    check("JAG-254 absent external tool -> tool_spec None",
          registry.tool_spec("pmcp__gateway.describe") is None)
    check("JAG-254 shipped tool still resolves",
          registry.tool_spec("shell") is not None)
    cat3 = registry.catalog()
    check("JAG-254 catalog omits absent external tools",
          all("__" not in t["name"] for t in cat3), "n=%d" % len(cat3))
finally:
    registry._external_tools = orig

# static guards
with open(os.path.join(REPO, "src", "longrun", "tools/registry.py"), encoding="utf-8") as f:
    src = f.read()
check("catalog snapshots external tools once", "ext = _external_tools()" in src)
check("catalog passes the snapshot to tool_spec", "tool_spec(name, ext)" in src)
check("catalog skips a missing spec", "if not spec:" in src)
check("JAG-254 external tool without schema is None", '"__" in name' in src)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
