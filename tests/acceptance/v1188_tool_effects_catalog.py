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

check("a declared read tool publishes its effect and its idempotency",
      rows["fs.read"].get("effect") == "read"
      and rows["fs.read"].get("reads") == ["file"]
      and rows["fs.read"].get("idempotent") is True, rows.get("fs.read"))
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
check("coverage counts exactly the idempotent declarations",
      0 < cov["idempotent"] == sum(1 for v in REG.TOOL_EFFECTS.values() if v.get("idempotent"))
      and all(v.get("idempotent") for v in REG.TOOL_EFFECTS.values()
              if v.get("effect") == "read"), cov)
check("no mutating tool claims idempotency without proof",
      not any(v.get("idempotent") for v in REG.TOOL_EFFECTS.values()
              if v.get("effect") in ("write", "delete", "append", "external")))
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
check("an undeclared live tool leaves the trace undecidable, not unsafe",
      undecl["verdict"] == "undecidable"
      and any(f["kind"] == "undeclared-tool" for f in undecl["findings"]), undecl)

# ---- 3b. escalation at the live tool gate -----------------------------------
# The declaration participates: the gate upgrades an automatic approval when the
# effect is destructive or the exact non-idempotent call already ran.
_del = ET.escalation("agent.delete", REG.effect_row("agent.delete"),
                     {"agent": "A1"}, [])
check("a declared delete cannot be auto-approved",
      _del[0] == "effect-destructive" and "delete" in _del[1], _del)
_unt = ET.escalation("sessions.list", REG.effect_row("sessions.list"), {}, [])
check("an untyped tool is left to the existing policy", _unt == (None, None), _unt)
_ran = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
         "tool_result": {"ok": True}}]
_rep = ET.escalation("fs.write", REG.effect_row("fs.write"), {"path": "a"}, _ran)
check("an exact repeat of a non-idempotent write needs approval",
      _rep[0] == "effect-repeat", _rep)
_failed = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
            "tool_result": {"ok": False}}]
check("a failed earlier call is not a duplicate effect",
      ET.escalation("fs.write", REG.effect_row("fs.write"), {"path": "a"},
                    _failed) == (None, None))
check("a different write is not a duplicate effect",
      ET.escalation("fs.write", REG.effect_row("fs.write"), {"path": "b"},
                    _ran) == (None, None))
check("an idempotent read may repeat without approval",
      ET.escalation("fs.read", REG.effect_row("fs.read"), {"path": "a"},
                    [{"action": "tool", "tool": "fs.read", "args": {"path": "a"},
                      "tool_result": {"ok": True}}]) == (None, None))

# ---- 3c. recovery adjudication at the live tool gate (round 116) ------------
# `effect_types.escalation` treats a failed call as "not a duplicate". A timeout
# is different: the effect may have committed, so `effect_recovery` decides the
# retry from the evidence in the same trace.
from longrun.core import api_v02 as API              # noqa: E402
_tmo = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
         "tool_result": {"ok": False, "exit_code": 124}}]
_rej = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
         "tool_result": {"ok": False, "exit_code": 1, "stderr": "no such file"}}]
_acked = [{"action": "tool", "tool": "fs.write", "args": {"path": "a"},
           "tool_result": {"ok": True}}]
_rc = API._recovery_escalation("fs.write", {"path": "a"}, _tmo)
check("a retry after a timed-out non-idempotent write needs approval",
      _rc[0] == "recovery-retry-would-duplicate" and "ambiguous" in _rc[1], _rc)
check("an explicit rejection is not an ambiguous outcome",
      API._recovery_escalation("fs.write", {"path": "a"}, _rej) == (None, None))
check("a completed call is not an ambiguous outcome",
      API._recovery_escalation("fs.write", {"path": "a"}, _acked) == (None, None))
check("an ambiguous call on another object does not block this one",
      API._recovery_escalation("fs.write", {"path": "b"}, _tmo) == (None, None))
check("an idempotent read ignores an ambiguous history",
      API._recovery_escalation("fs.read", {"path": "a"}, _tmo) == (None, None))
_absent = _tmo + [{"action": "tool", "tool": "fs.read", "args": {"path": "a"},
                   "tool_result": {"ok": False, "exit_code": 1}}]
check("a failed read-back proves nothing committed, so the retry is safe",
      API._recovery_escalation("fs.write", {"path": "a"}, _absent) == (None, None))
_committed = _tmo + [{"action": "tool", "tool": "fs.read", "args": {"path": "a"},
                      "tool_result": {"ok": True}}]
check("a successful read-back proves the write landed and blocks the retry",
      API._recovery_escalation("fs.write", {"path": "a"},
                               _committed)[0] == "recovery-retry-would-duplicate")
_killed = [{"action": "tool", "tool": "shell.exec",
            "args": {"command": "deploy"},
            "tool_result": {"ok": False, "exit_code": 137}}]
check("a killed external command is ambiguous, not a rejection",
      API._recovery_escalation("shell.exec", {"command": "deploy"},
                               _killed)[0] == "recovery-retry-would-duplicate")
_caps = API._recovery_capabilities(["fs.read", "fs.write", "shell.exec",
                                    "memory.recall", "memory.store"])
check("read_after_write is derived from the declarations, not invented",
      _caps["fs.write"]["read_after_write"] and _caps["memory.store"]["read_after_write"]
      and not _caps["shell.exec"]["read_after_write"], _caps)
check("atomic_abort is never assumed",
      not any(c["atomic_abort"] for c in _caps.values()), _caps)

# ---- 4. the declarations feed the tool graph (round 121) --------------------
from longrun.harness import tool_graph as TG          # noqa: E402
lg = TG.build(list(rows.values()))
ledges = {(e["from"], e["to"]): e for e in lg["edges"]}
check("the live catalog yields a typed writer->reader edge",
      ("memory.store", "memory.recall") in ledges
      and any(r.startswith("effect:memory") for r in
              ledges[("memory.store", "memory.recall")]["reasons"]),
      ledges.get(("memory.store", "memory.recall")))
check("a reader is not chained back into the writer",
      ("memory.recall", "memory.store") not in ledges)
check("an untyped live tool contributes no effect edge",
      not any(r.startswith("effect:") for e in lg["edges"]
              for r in e["reasons"] if e["from"] == "sessions.list"))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
