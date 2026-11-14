#!/usr/bin/env python3
"""v983 — a destructive action spelled in CAPITALS still reaches its approval gate.

`canonical_name` derived the canonical subtool from the action VERBATIM while
every handler reads it with `.lower()` (`tools._memory`, `tools._matrix`). So
`memory{action:"DELETE"}` resolved to the bare namespace — whose policy row is
`approval: auto` — and the handler then ran `forget`, deleting a record with no
card; `matrix{action:"REMOVE"}` removed a module the same way. The canonical
spellings (`memory.forget`, `matrix.remove`) correctly ask.

Contract:
  A) an upper/mixed-case action canonicalises to the same subtool as the lower one;
  B) the policy gate then sees the GATED tool, not the bare namespace;
  C) the aliases that close the door (`delete` -> forget, `uninstall` -> remove)
     work in any case;
  D) a plain tool and a dotted name are still returned unchanged.

Deterministic: no model, no server, no network.

Run: python3 tests/acceptance/v983_action_case_gate.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="v983_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITs_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(_TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the same subtool in any case ---------------------------------------
check("A1 memory DELETE -> memory.forget",
      R.canonical_name("memory", {"action": "DELETE"}) == "memory.forget",
      R.canonical_name("memory", {"action": "DELETE"}))
check("A2 memory Forget -> memory.forget",
      R.canonical_name("memory", {"action": "Forget"}) == "memory.forget",
      R.canonical_name("memory", {"action": "Forget"}))
check("A3 matrix REMOVE -> matrix.remove",
      R.canonical_name("matrix", {"action": "REMOVE"}) == "matrix.remove",
      R.canonical_name("matrix", {"action": "REMOVE"}))

# --- B: the gate sees the gated tool --------------------------------------
check("B1 the canonical forget row requires approval",
      (R.tool_spec("memory.forget") or {}).get("approval") == "required",
      (R.tool_spec("memory.forget") or {}).get("approval"))
_decision, _reason = R.classify("memory", {"action": "DELETE", "id": "m1"}, None, None)
check("B2 classify answers 'required' for the capitalised spelling",
      _decision == "required", (_decision, _reason))
_d2, _r2 = R.classify("matrix", {"action": "REMOVE", "name": "x", "kind": "tool"}, None, None)
check("B3 matrix REMOVE is gated too", _d2 == "required", (_d2, _r2))

# --- C: the alias table works in any case ---------------------------------
check("C1 write_core in capitals still maps to set_core",
      R.canonical_name("memory", {"action": "WRITE_CORE"}) == "memory.set_core",
      R.canonical_name("memory", {"action": "WRITE_CORE"}))
check("C2 uninstall in capitals still maps to remove",
      R.canonical_name("matrix", {"action": "UNINSTALL"}) == "matrix.remove",
      R.canonical_name("matrix", {"action": "UNINSTALL"}))

# --- D: no over-reach ------------------------------------------------------
check("D1 a plain tool is unchanged",
      R.canonical_name("fs.read", {"path": "a"}) == "fs.read")
check("D2 a dotted name is unchanged",
      R.canonical_name("memory.forget", {"action": "DELETE"}) == "memory.forget")
check("D3 an external MCP name is unchanged",
      R.canonical_name("pmcp__gateway.list_tools", {}) == "pmcp__gateway.list_tools")

ok = sum(RESULTS)
print("\nv983: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
