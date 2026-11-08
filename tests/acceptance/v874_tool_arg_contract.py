#!/usr/bin/env python3
"""v874 — the gate IMPOSES the declared argument contract (types + unknown keys).

Measured 2026-11-08 on the running service:
  * `fs.read {"path": 12345}` → `no such file: .../12345`: the handler's `str()`
    turned the model's programming error into a path, so a type mistake read as a
    missing file (exit 1) instead of a usage error (exit 64);
  * `fs.read {"path":"README.md","bogus_arg":"X"}` → exit 0, file read, no warning:
    a typo'd key ("startline") is dropped in silence and the call LOOKS correct.

Contract pinned here:
  A1 an int for a declared string is a USAGE error (exit 64) naming the key + type
  A2 it never reaches the handler (no "no such file" path is built)
  A3 an undeclared key on a successful call is NAMED in a non-fatal warning
  A4 the warning lists what the tool accepts
  A5 the warning reaches the MODEL (observation renders it)
  A6 a numeric string for an INTEGER argument is still accepted (no new strictness
     where the tool can convert safely)

Run: python3 tests/acceptance/v874_tool_arg_contract.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v874-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry         # noqa: E402
from longrun.tools import tools as T       # noqa: E402

# Deterministic: never start a configured external MCP client in a test.
registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------------------------- A1/A2 a wrong TYPE --------
bad = T._dispatch_execute("fs.read", {"path": 12345})
check("A1 an integer for a declared string is a USAGE error (exit 64)",
      bad.get("ok") is False and bad.get("exit_code") == 64,
      "exit=%s error=%r" % (bad.get("exit_code"), bad.get("error")))
check("A2 it names the key and the type instead of blaming the filesystem",
      "'path' must be a string" in (bad.get("error") or "")
      and "no such file" not in (bad.get("error") or ""),
      bad.get("error"))
check("A2b a bool is not a string either",
      T._dispatch_execute("fs.read", {"path": True}).get("exit_code") == 64,
      T._dispatch_execute("fs.read", {"path": True}).get("error"))

# ------------------------------------- A3/A4/A5 an UNDECLARED argument --------
ok = T._dispatch_execute("self", {"action": "tools", "tool": "fs.read",
                                 "bogus_arg": "A50-X1"})
warn = str(ok.get("warning") or "")
check("A3 a successful call reports the undeclared key instead of dropping it",
      ok.get("ok") is True and "bogus_arg" in warn, "warning=%r" % warn)
check("A4 the warning lists the arguments the tool accepts",
      "accepts" in warn and "query" in warn and "tool" in warn, warn)
check("A5 the warning reaches the MODEL (rendered by observation)",
      "bogus_arg" in T.observation(ok), T.observation(ok).splitlines()[:4])

# ------------------------------------------- A6 no new strictness elsewhere -----
shape = (registry.tool_spec("fs.read") or {}).get("schema") or {}
ptype = ((shape.get("properties") or {}).get("start_line") or {}).get("type")
notes = T._shape_notes("fs.read", {"path": "README.md", "start_line": "1"})
check("A6 a numeric STRING for an integer argument is still accepted",
      ptype == "integer" and notes == [], "%s -> %r" % (ptype, notes))

print("---")
okc = sum(results)
print("\nv874: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
