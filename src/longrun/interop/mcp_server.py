#!/usr/bin/env python3
"""Longrun MCP server (stdio transport).

Speaks the Model Context Protocol over stdin/stdout (JSON-RPC 2.0, one message
per line) and forwards every tool call to a running Longrun instance over
HTTP. Register it with any MCP client, e.g.:

    {
      "mcpServers": {
        "longrun": {
          "command": "python3",
          "args": ["/home/jagones/Repositories/MyRepos/longrun/mcp_server.py"],
          "env": {"LONGRUN_URL": "http://127.0.0.1:8790"}
        }
      }
    }

NOTE: point the client at the ROOT launcher shim (`longrun/mcp_server.py`),
NOT at this package module. This file uses relative imports (`from . import mcp`)
so it cannot be run as a standalone script; the root shim adds `src/` to
`sys.path` and calls `main()`.

Protocol traffic goes to stdout; diagnostics go to stderr (never stdout).
"""

import json
import sys

from longrun.interop import mcp

DIAG = "--verbose" in sys.argv


def log(*a):
    if DIAG:
        print("[longrun-mcp]", *a, file=sys.stderr, flush=True)


def main():
    api = mcp.HttpApi()
    log("stdio server up, backend =", api.base)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = mcp.handle(msg, api)
        if resp is None:
            continue
        log("<-", msg.get("method"), "->", "error" if "error" in resp else "ok")
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

