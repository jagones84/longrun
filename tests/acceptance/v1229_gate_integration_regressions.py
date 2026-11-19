#!/usr/bin/env python3
"""v1229 — the live gate/Harness fixes found by the round-160 bug hunt.

Five confirmed defects, one section each:
  G1  a nested `{"args": {...}}` envelope made `gated_call` judge the namespace
      DEFAULT while the dispatcher ran the nested action;
  G2  the gate-injected `workspace` made `effect_types`' exact-repeat digest
      unmatchable against the recorded trace;
  G3  a REFUSED read-back was read as proof that an ambiguous write never
      committed (covered in v1188 §3c, asserted here against the same helper);
  G4  every external MCP read (`github__…`, `chrome-devtools__…`) was
      classified `local-read`, so the intent audit's read bypass covered it;
  G5  the untrusted-memory ledger grew per run without bound, and the CORE block
      (`memory.set_core`) bound no provenance at all.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1229_gate_integration_regressions.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1229-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API          # noqa: E402
from longrun.tools import registry as REG        # noqa: E402
from longrun.tools import tools as TOOLS         # noqa: E402
from longrun.tools import approvals              # noqa: E402
from longrun.harness import tool_policy          # noqa: E402
from longrun.harness import intent_audit as IA   # noqa: E402
from longrun.memory import memory as MEM         # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


NESTED = {"args": {"action": "forget", "target": "m-1", "query": "q"}}

# ---- G1: the gate resolves the subtool the dispatcher will run -------------
check("G1 the raw envelope resolves to the destructive subtool",
      REG.canonical_name("memory", NESTED) == "memory.forget",
      REG.canonical_name("memory", NESTED))
_norm = TOOLS.normalize_args("memory", dict(NESTED))
_dec, _why = REG.classify("memory", _norm, hist=[{"role": "user", "content": "hi"}])
check("G1 the gate asks for approval (it used to judge memory.recall: auto)",
      _dec == "required", (_dec, _why))
PEND = API.gated_call("memory", NESTED, run_id=None, wait=False, announce=False)
check("G1 the public door returns a pending approval, not an execution",
      PEND.get("status") == "pending", PEND.get("status"))
_rec = approvals.list_all(None, 10)[0] if approvals.list_all(None, 10) else {}
check("G1 the approval record names the action that would run",
      _rec.get("tool") == "memory.forget", _rec.get("tool"))

KEEP = MEM.store("note", "KEEP-ME", origin="user")["mid"]
_BAD = TOOLS.execute("memory.recall", {"action": "forget", "target": KEEP,
                                       "query": "q"}, run_id=None)
check("G1 a dotted name cannot smuggle a conflicting action past dispatch",
      _BAD.get("ok") is False and _BAD.get("exit_code") == 64, _BAD.get("error"))
check("G1 the record the destructive call named still exists",
      any(r.get("mid") == KEEP for r in MEM.query("KEEP-ME", None, 10)))

# ---- G2: the injected workspace is not part of the call's identity ---------
_W = {"path": "a.txt", "content": "x"}
_DISPATCH, _JUDGED = API._inject_workspace("fs.write", _W, "/workspace/w")
check("G2 dispatch carries the session workspace", _DISPATCH.get("workspace") == "/workspace/w")
check("G2 the judged args are the caller's args", _JUDGED == _W, _JUDGED)
_TRACE = [{"action": "tool", "tool": "fs.write", "args": {"path": "a.txt", "content": "x"},
           "tool_result": {"ok": True}}]
check("G2 an exact repeat is still recognised after the injection",
      API._effect_escalation("fs.write", _JUDGED, _TRACE)[0] == "effect-repeat",
      API._effect_escalation("fs.write", _JUDGED, _TRACE))
_WRAPPED = [{"action": "tool", "tool": "fs.write",
             "args": {"args": {"path": "a.txt", "content": "x"}},
             "tool_result": {"ok": True}}]
check("G2 a repaired trace row digests as the same call",
      API._effect_escalation("fs.write", _W, _WRAPPED)[0] == "effect-repeat")

# ---- G3: only an ABSENCE signal may clear an ambiguous write ---------------
_TMO = [{"action": "tool", "tool": "fs.write", "args": {"path": "n"},
         "tool_result": {"ok": False, "exit_code": 124}}]
_REFUSED = _TMO + [{"action": "tool", "tool": "fs.read", "args": {"path": "n"},
                    "tool_result": {"ok": False, "error": "permission denied"}}]
_ABSENT = _TMO + [{"action": "tool", "tool": "fs.read", "args": {"path": "n"},
                   "tool_result": {"ok": False, "error": "no such file: n"}}]
check("G3 a refused read-back leaves the retry requiring approval",
      API._recovery_escalation("fs.write", {"path": "n"}, _REFUSED)[0]
      == "recovery-retry-would-duplicate")
check("G3 an absence read-back proves the retry safe",
      API._recovery_escalation("fs.write", {"path": "n"}, _ABSENT) == (None, None))

# ---- G4: an external MCP read is not a local read --------------------------
for _n in ("github__search_code", "chrome-devtools__list_pages",
           "pmcp__gateway.tasks_list"):
    _r = REG.tool_record(_n) or {"name": _n}
    check("G4 %s is an external read" % _n,
          tool_policy.classify(_r)["kind"] == "external-read",
          tool_policy.classify(_r)["kind"])
check("G4 fs.read is still a local read",
      tool_policy.classify(REG.tool_record("fs.read"))["kind"] == "local-read")
# Self-contained graph: the live catalog may not include the MCP servers.
_G = IA.graph({"nodes": [{"id": "objective", "tools": ["github__search_code"],
                          "repeatable": True}],
               "edges": [], "satisfied": []})
_KIND = tool_policy.classify({"name": "github__search_code"})["kind"]
_A = IA.audit({"tool": "github__search_code", "params": {}, "kind": _KIND},
              _G, {"untrusted": True}, bypass=True)
check("G4 a tainted external MCP read is audited, not bypassed",
      _A.get("bypassed") is None and _A["verdict"] == "FLAG", _A)

# ---- G5: the ledger is bounded and the CORE write is typed -----------------
API._UNTRUSTED_MEMORY.clear()
for _i in range(API._UNTRUSTED_MAX_RUNS + 50):
    API._remember_untrusted("run-%d" % _i, "x")
check("G5 the ledger keeps at most MAX buckets",
      len(API._UNTRUSTED_MEMORY) == API._UNTRUSTED_MAX_RUNS,
      len(API._UNTRUSTED_MEMORY))
API._forget_untrusted("run-%d" % (API._UNTRUSTED_MAX_RUNS + 49))
check("G5 a finished run's bucket is dropped",
      "run-%d" % (API._UNTRUSTED_MAX_RUNS + 49) not in API._UNTRUSTED_MEMORY)
check("G5 memory.set_core is a declared write",
      (REG.effect_row("memory.set_core") or {}).get("effect") == "write")
check("G5 the CORE write is in the provenance binder",
      "memory.set_core" in API._MEMORY_WRITE_TOOLS)
_CORE = API.gated_call("memory", {"args": {"action": "set_core",
                                           "content": "x", "query": "q"}},
                       run_id=None, wait=False, announce=False)
check("G5 a CORE rewrite takes the approval path",
      _CORE.get("status") == "pending", _CORE.get("status"))
API._remember_untrusted("s-core", "deploy token sk-live-0123456789abcdef")
check("G5 a later action carrying the CORE text is escalated",
      API._memory_gate("sessions.send",
                       {"session": "s", "message": "sk-live-0123456789abcdef"},
                       "s-core")[0] == "memory-untrusted-derived")

# ---- verdict --------------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
