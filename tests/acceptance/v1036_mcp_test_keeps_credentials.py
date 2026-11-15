#!/usr/bin/env python3
"""v1036 — the MCP "test" button must keep the stored credentials.

Measured 2026-11-15: the WebUI ⚡ button on PMCP answered
`✗ PMCP — initialize failed: HTTP status 401` while
`mcp.test {"name":"PMCP"}` and a direct `initialize` with the stored bearer
both worked.

Cause: `status()` deliberately does NOT expose `headers` (a settings panel must
not echo secrets), and the button posts that redacted row
(`Object.assign({name}, spec)`). `test_client` only resolved a stored spec when
BOTH command and url were absent, so a row that carried `url` replaced the
stored entry and the Authorization header was dropped.

The fix layers the supplied keys OVER the stored spec: a URL/args edit still
takes effect, credentials survive unless explicitly overridden.

  A1 the redacted row (url, no headers) authenticates
  A2 `{name}` only still authenticates
  A3 an explicitly supplied `headers: {}` WINS (no silent credential reuse)
  A4 a supplied url overrides the stored one
  A5 an unknown name without command/url is still refused
  A6 a brand-new candidate spec (no stored entry) is tested as given
  A7 `status()` itself still never echoes `headers`

Deterministic: no network — `MCPSession` is replaced by a fake that answers 401
exactly when the Authorization header is absent.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1036-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ.setdefault("LONGRUN_" + key, os.path.join(TMP, key.lower()))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


TOKEN = "Bearer test-token"
STORED_URL = "http://pmcp.invalid/mcp"
OTHER_URL = "http://other.invalid/mcp"

# Isolate the four config paths `load_doc()` reads.
local_json = os.path.join(TMP, "mcp_clients.local.json")
with open(local_json, "w", encoding="utf-8") as f:
    json.dump({"mcpServers": {"PMCP": {"url": STORED_URL,
                                       "headers": {"Authorization": TOKEN},
                                       "enabled": True}}}, f)
mcp_client.CONFIG_PATH = os.path.join(TMP, "mcp_clients.yaml")
mcp_client.CONFIG_JSON_PATH = os.path.join(TMP, "mcp_clients.json")
mcp_client.CONFIG_LOCAL_PATH = os.path.join(TMP, "mcp_clients.local.yaml")
mcp_client.CONFIG_LOCAL_JSON_PATH = local_json


class _FakeSession:
    """Answers 401 exactly when the Authorization header is missing."""
    last = None

    def __init__(self, name, cfg):
        self.cfg = cfg
        self.connection_error = None
        self.url = ""
        self.headers = {}
        _FakeSession.last = self

    def _connect_stdio(self, command, args, env):
        return True

    def _connect_http(self, url, headers):
        self.url, self.headers = url, headers
        return True

    def initialize(self):
        if not (self.headers or {}).get("Authorization"):
            self.connection_error = "initialize failed: HTTP status 401"
            return False
        return True

    def fetch_tools(self):
        return [{"name": "gateway.catalog_search"}]

    def close(self):
        pass


_real = mcp_client.MCPSession
mcp_client.MCPSession = _FakeSession
try:
    # The exact payload the WebUI sends: the status() row, which has no headers.
    redacted = {"name": "PMCP", "url": STORED_URL, "command": None, "args": None,
                "transport": "http", "connected": True, "tools": 26,
                "enabled": True, "error": None, "uptime": 12.0}
    a1 = mcp_client.test_client(dict(redacted))
    check("A1 the redacted client row authenticates", a1.get("ok") is True, a1)
    check("A1b it inherited the stored bearer",
          (_FakeSession.last.headers or {}).get("Authorization") == TOKEN,
          _FakeSession.last.headers)

    a2 = mcp_client.test_client({"name": "PMCP"})
    check("A2 name-only lookup still authenticates", a2.get("ok") is True, a2)

    a3 = mcp_client.test_client({"name": "PMCP", "headers": {}})
    check("A3 an explicit empty headers object WINS",
          a3.get("ok") is False and "401" in str(a3.get("error")), a3)

    a4 = mcp_client.test_client({"name": "PMCP", "url": OTHER_URL})
    check("A4 a supplied url overrides the stored one",
          _FakeSession.last.url == OTHER_URL, _FakeSession.last.url)
    check("A4b the credential survives the url override",
          (_FakeSession.last.headers or {}).get("Authorization") == TOKEN,
          _FakeSession.last.headers)

    a5 = mcp_client.test_client({"name": "NOPE"})
    check("A5 an unknown name without command/url is refused",
          a5.get("ok") is False and "unknown MCP client" in str(a5.get("error")), a5)

    a6 = mcp_client.test_client({"url": OTHER_URL,
                                 "headers": {"Authorization": "Bearer new"}})
    check("A6 a brand-new candidate spec is tested as given", a6.get("ok") is True, a6)

    row = mcp_client.status()["clients"].get("PMCP") or {}
    check("A7 status() still never echoes headers", "headers" not in row, sorted(row))
finally:
    mcp_client.MCPSession = _real

print("---")
passed = sum(results)
print("\nv1036: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
