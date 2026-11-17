#!/usr/bin/env python3
"""v1116 — the provider is part of a tool's identity.

Round 50, from arXiv:2611.21577 *When Tool Names Are Not Identities: Measuring
Provider Misbinding in MCP-Based AI Agents*: an MCP client composes tools from
several servers, and a tool NAME alone does not bind a request to a provider.
Longrun already namespaces every external tool `client__tool`, but two config
keys that differ only by case collapse onto the SAME name, and the last writer
won silently — the exact-name collision the paper measures. A client key that
carries the `__` separator can likewise spell another server's namespace.

  A  two clients differing only by case: ONE name, owned by the first client
  B  the loser is refused loudly (a status error), never silently dropped
  C  a client key containing `__` is refused (it can spell another namespace)
  D  distinct providers keep their own names (no regression)
  E  the description still names the provider (attribution stays visible)
  F  a disconnected client still exposes nothing

Deterministic: fake sessions, tmp dirs, no network, no server.
Run: python3 tests/acceptance/v1116_mcp_provider_identity.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="v1116-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"]):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client as mc  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


class _Sess:
    def __init__(self, tools, connected=True):
        self.tools = tools
        self.connected = connected


def _tool(desc="search things"):
    return {"description": desc, "inputSchema": {"type": "object", "properties": {}}}


# ------------------------------------------------- A/B: case collision --------
_mgr = mc.MCPClientManager()
mc._EXTERNAL_TOOLS.clear()
_mgr.sessions["GitHub"] = _Sess({"search": _tool()})
_mgr.sessions["github"] = _Sess({"search": _tool("search things, from the other one")})
_names = sorted(t["name"] for t in _mgr.list_external_tools())
check("A1 two case-differing clients expose ONE name", _names == ["github__search"], _names)
_owner = (_mgr.list_external_tools()[0] or {}).get("client_name") if _names else None
check("A2 the FIRST registered provider owns it (deterministic, not last-writer)",
      _owner == "GitHub", _owner)
_err = (_mgr._errors or {}).get("github") or ""
check("B1 the refused provider says why, in the status channel",
      "collides with 'GitHub'" in _err and "misbound" in _err, _mgr._errors)

# ------------------------------------------------- C: `__` in the key --------
_mgr2 = mc.MCPClientManager()
mc._EXTERNAL_TOOLS.clear()
_mgr2.sessions["GitHub"] = _Sess({"search": _tool()})
_mgr2.sessions["Git__Hub"] = _Sess({"search": _tool()})
_names2 = sorted(t["name"] for t in _mgr2.list_external_tools())
check("C1 a client key carrying '__' is refused",
      _names2 == ["github__search"], _names2)
check("C2 and it is named in the status channel",
      "provider separator" in str((_mgr2._errors or {}).get("Git__Hub") or ""),
      _mgr2._errors)

# ------------------------------------------------- D/E: no regression --------
_mgr3 = mc.MCPClientManager()
mc._EXTERNAL_TOOLS.clear()
_mgr3.sessions["alpha"] = _Sess({"search": _tool()})
_mgr3.sessions["beta"] = _Sess({"search": _tool()})
_tools3 = {t["name"]: t for t in _mgr3.list_external_tools()}
check("D1 distinct providers keep distinct names",
      set(_tools3) == {"alpha__search", "beta__search"}, sorted(_tools3))
check("E1 the description still names the provider",
      all("[external MCP: " in (t["description"] or "") for t in _tools3.values()),
      [t["description"] for t in _tools3.values()])

# ------------------------------------------------- F: disconnected -----------
_mgr4 = mc.MCPClientManager()
mc._EXTERNAL_TOOLS.clear()
_mgr4.sessions["gone"] = _Sess({"search": _tool()}, connected=False)
check("F1 a disconnected client exposes nothing",
      _mgr4.list_external_tools() == [], _mgr4.list_external_tools())

print("\n---\nv1116: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
