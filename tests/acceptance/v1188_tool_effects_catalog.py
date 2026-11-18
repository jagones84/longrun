#!/usr/bin/env python3
"""v1188 — the live tool catalog declares its effects (round 119).

Source: arXiv:2610.35981 (round 116's `effect_types`), wired to the real catalog:
`registry.TOOL_EFFECTS` is the one owner of the declaration, `catalog()` publishes
it on the row, and `effects coverage --live` measures the catalog itself.

Deterministic: the external/matrix/promoted sources are stubbed so no MCP server,
no network and no live config is touched.

Run: python3 tests/acceptance/v1188_tool_effects_catalog.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1188-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG            # noqa: E402
from longrun.harness import effect_types as ET        # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# Offline catalog: the three external sources are what reach MCP / the network.
REG._external_tools = lambda: {}
REG._matrix_tools = lambda: {}
REG._promoted_tools = lambda: {}
rows = {r["name"]: r for r in REG.catalog()}
catalog = {name: {"effect": r.get("effect"), "idempotent": r.get("idempotent"),
                  "reads": r.get("reads") or [], "writes": r.get("writes") or []}
           for name, r in rows.items()}

# ---- 1. the declaration -----------------------------------------------------
check("the catalogue exposes the live tool set", len(rows) > 100, len(rows))
check("every declared effect is one of the six classes",
      all(v.get("effect") in ET.EFFECTS for v in REG.TOOL_EFFECTS.values()),
      sorted(set(v.get("effect") for v in REG.TOOL_EFFECTS.values())))
check("a read declaration names the resource it reads",
      all(v.get("reads") for v in REG.TOOL_EFFECTS.values() if v.get("effect") == "read"))
check("a mutating declaration names the resource it writes",
      all(v.get("writes") for v in REG.TOOL_EFFECTS.values()
          if v.get("effect") in ("write", "delete", "append", "external")))

check("a declared read tool publishes its effect",
      rows["fs.read"].get("effect") == "read"
      and rows["fs.read"].get("reads") == ["file"]
      and rows["fs.read"].get("idempotent") is False, rows.get("fs.read"))
check("a declared write tool publishes non-idempotency",
      rows["fs.write"].get("effect") == "write"
      and rows["fs.write"].get("idempotent") is False
      and rows["fs.write"].get("writes") == ["file"], rows.get("fs.write"))
check("a declared delete tool publishes both read and write resources",
      rows["agent.delete"].get("effect") == "delete"
      and rows["agent.delete"].get("reads") == ["agent"]
      and rows["agent.delete"].get("writes") == ["agent"], rows.get("agent.delete"))
check("an undeclared tool stays untyped",
      "effect" not in rows.get("sessions.list", {}), rows.get("sessions.list"))
check("the declaration never leaks into the model-facing inputSchema",
      all("effect" not in (r.get("inputSchema") or {}) for r in rows.values()))

copy = REG.effect_row("fs.read")
copy["reads"].append("tampered")
check("effect_row hands out a copy, not the owner",
      REG.TOOL_EFFECTS["fs.read"]["reads"] == ["file"])

# ---- 2. coverage over the live catalog -------------------------------------
cov = ET.coverage(catalog)
check("coverage counts exactly the declared tools",
      cov["typed"] == len(REG.TOOL_EFFECTS) and cov["untyped"] == len(rows) - len(REG.TOOL_EFFECTS),
      {"typed": cov["typed"], "untyped": cov["untyped"], "total": len(rows)})
check("a partially typed catalog is reported as partial, never as untyped",
      cov["verdict"] == "partial" and cov["invalid"] == [], cov["verdict"])
check("every declared tool exists in the live catalog",
      set(REG.TOOL_EFFECTS) <= set(rows),
      sorted(set(REG.TOOL_EFFECTS) - set(rows)))

# ---- 3. the verifier reads the live declarations ---------------------------
safe = ET.verify_trace([{"tool": "fs.read"}, {"tool": "fs.write"}], catalog)
check("read then write is effect-safe on the live catalog", safe["verdict"] == "safe", safe)
rep = ET.verify_trace([{"tool": "fs.write"}, {"tool": "fs.write"}], catalog)
check("a repeated non-idempotent write is unsafe on the live catalog",
      rep["verdict"] == "unsafe"
      and any(f["kind"] == "repeat-write" for f in rep["findings"]), rep)
blind = ET.verify_trace([{"tool": "agent.delete"}], catalog)
check("a delete nobody read first is unsafe on the live catalog",
      blind["verdict"] == "unsafe"
      and any(f["kind"] == "delete-without-read" for f in blind["findings"]), blind)
red = ET.verify_trace([{"tool": "fs.read"}, {"tool": "fs.read"}], catalog)
check("a re-read of unchanged state is reported on the live catalog",
      any(f["kind"] == "redundant-read" for f in red["findings"]), red)
undecl = ET.verify_trace([{"tool": "sessions.list"}], catalog)
check("an undeclared live tool still makes a trace unverifiable",
      undecl["verdict"] == "unsafe"
      and any(f["kind"] == "undeclared-tool" for f in undecl["findings"]), undecl)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
