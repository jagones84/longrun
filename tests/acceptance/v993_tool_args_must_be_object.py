#!/usr/bin/env python3
"""v993 — a tool call whose `args` is not a JSON object answers an error, never dies.

`gated_call` is the ONE door both `POST /api/tools/call` and the chat loop use
(and the MCP adapter). It assumed `args` was a mapping and called
`dict(args or {})`, so `{"tool": "fs.read", "args": "a string"}` raised
ValueError/TypeError inside the handler and the HTTP connection was closed with
NO response (measured 2026-11-14 on the live service; a model that emits a
string or a list in `args` would kill its own turn the same way).

Contract:
  A) a string / list / number is refused with a named error, no exception;
  B) a real mapping still runs the tool (unchanged);
  C) `None` keeps meaning "no arguments" (the tool's own validation answers).

Deterministic: temp dirs, no server, no model.
Run: python3 tests/acceptance/v993_tool_args_must_be_object.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="v993_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR",
           "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: a non-mapping is refused, with the type named --------------------
for bad, label in (("a string", "str"), ([1, 2], "list"), (42, "int")):
    try:
        got = A.gated_call("fs.read", bad)
    except Exception as exc:  # noqa: BLE001
        check("A %s answers instead of raising" % label, False, "%s: %s"
              % (type(exc).__name__, exc))
        continue
    check("A %s answers instead of raising" % label, isinstance(got, dict), got)
    check("A %s error names the type" % label,
          got.get("status") == "error" and label in str(got.get("error")), got)

# ---- B: a mapping still runs ---------------------------------------------
got = A.gated_call("fs.read", {"path": os.path.join(REPO, "README.md"), "max_bytes": 120})
check("B a real mapping still executes the tool",
      got.get("status") == "executed" and (got.get("result") or {}).get("ok") is True, got)

# ---- C: None means "no arguments" ---------------------------------------
got = A.gated_call("fs.read", None)
check("C None reaches the tool's own validation, not the args check",
      isinstance(got, dict) and "JSON object" not in str(got.get("error"))
      and "JSON object" not in str((got.get("result") or {}).get("error")), got)

ok = sum(RESULTS)
print("\nv993: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
