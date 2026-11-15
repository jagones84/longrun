#!/usr/bin/env python3
"""v1037 — an unresolved `${VAR}` in an MCP client is named, not sent.

Measured 2026-11-15: the GitHub connector ships
`Authorization: Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}` while this install only
had `GITHUB_TOKEN`. `os.path.expandvars` leaves an unknown reference VERBATIM, so
the literal placeholder went out and GitHub answered

    400 bad request: Authorization header is badly formatted

The panel showed that bare status. A missing credential must be named before any
request leaves the process — and the same rule applies to a stdio server's env
and args, which would otherwise start with a literal `${KEY}`.

  A1 `_expand` resolves a real variable and reports nothing missing
  A2 `_expand` names the unresolved variable and leaves the text untouched
  A3 an HTTP header with an unresolved ref fails BEFORE any request
  A4 `test_client` surfaces that sentence (not "transport connect failed")
  A5 a stdio env ref fails before the child is spawned
  A6 a stdio arg ref fails the same way
  A7 a RESOLVABLE header still connects (no over-blocking)

Deterministic: no network, no child process.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1037-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ.setdefault("LONGRUN_" + key, os.path.join(TMP, key.lower()))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# Never touch the real client config.
for attr, leaf in (("CONFIG_PATH", "mcp_clients.yaml"),
                   ("CONFIG_JSON_PATH", "mcp_clients.json"),
                   ("CONFIG_LOCAL_PATH", "mcp_clients.local.yaml"),
                   ("CONFIG_LOCAL_JSON_PATH", "mcp_clients.local.json")):
    setattr(mcp_client, attr, os.path.join(TMP, leaf))

text, missing = mcp_client._expand("Bearer ${HOME}")
check("A1 a real variable expands and is not reported",
      missing == [] and text != "Bearer ${HOME}", (text, missing))

text, missing = mcp_client._expand("Bearer ${V1037_NOT_SET}")
check("A2 an unknown variable is named and the text is untouched",
      missing == ["V1037_NOT_SET"] and "${V1037_NOT_SET}" in text, (text, missing))

session = mcp_client.MCPSession("http-probe", {"url": "http://127.0.0.1:9/mcp"})
called = {"http": 0}
session._http_call = lambda *a, **k: called.__setitem__("http", called["http"] + 1) or {}
ok = session._connect_http("http://127.0.0.1:9/mcp",
                           {"Authorization": "Bearer ${V1037_NOT_SET}"})
check("A3 an unresolved header fails before any request", ok is False, ok)
check("A3b no request left the process", called["http"] == 0, called)
check("A3c the message names the variable and the fix",
      "V1037_NOT_SET" in (session.connection_error or "")
      and "Settings" in (session.connection_error or ""),
      session.connection_error)

out = mcp_client.test_client({"url": "http://127.0.0.1:9/mcp",
                              "headers": {"Authorization": "Bearer ${V1037_NOT_SET}"}})
check("A4 test_client surfaces the credential sentence",
      out.get("ok") is False
      and "missing credential" in str(out.get("error"))
      and "HTTP status" not in str(out.get("error")),
      out)

spawned = {"n": 0}
_real_popen = mcp_client.subprocess.Popen


def _no_spawn(*a, **k):  # pragma: no cover - only reached on a regression
    spawned["n"] += 1
    return _real_popen(*a, **k)


mcp_client.subprocess.Popen = _no_spawn
try:
    stdio = mcp_client.MCPSession("stdio-probe", {"command": "true"})
    ok = stdio._connect_stdio("true", [], {"API_KEY": "${V1037_NOT_SET}"})
    check("A5 a stdio env ref fails before the child is spawned",
          ok is False and spawned["n"] == 0, (ok, spawned["n"]))
    check("A5b the stdio message names the variable",
          "V1037_NOT_SET" in (stdio.connection_error or ""), stdio.connection_error)

    stdio2 = mcp_client.MCPSession("stdio-probe-2", {"command": "true"})
    ok = stdio2._connect_stdio("true", ["--token", "${V1037_NOT_SET}"], {})
    check("A6 a stdio arg ref fails the same way",
          ok is False and spawned["n"] == 0, (ok, spawned["n"]))
finally:
    mcp_client.subprocess.Popen = _real_popen

ok = session._connect_http("http://127.0.0.1:9/mcp",
                           {"Authorization": "Bearer ${HOME}"})
check("A7 a resolvable header still connects",
      ok is True and session._http_headers.get("Authorization", "").startswith("Bearer /"),
      session._http_headers.get("Authorization"))

print("---")
passed = sum(results)
print("\nv1037: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
