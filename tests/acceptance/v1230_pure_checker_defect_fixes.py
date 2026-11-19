#!/usr/bin/env python3
"""v1230 — the pure-checker defects the round-160 bug hunt found (G6–G17).

Each section is one confirmed finding and its corrected behaviour:
  G6  an unattributed voucher fabricated an independent domain;
  G7  `authorize` ignored token fields the action omitted and accepted an
      anonymous (nonce-less) token;
  G8  `adjudicate` read dependency states while still filling them, so the
      verdict depended on the order of the obligation list;
  G9  `fact_ledger` did not enforce I5, crashed on a non-numeric trust, and left
      both values open after an untimestamped supersede;
  G10 an ambiguous tool outcome (exit 124/137/143) was recorded as a failed
      effect, so the audit reported lost approved work;
  G11 `evidence_replay.leak` divided by zero on a zero-total row;
  G12 `awareness.snapshot` raised on an ISO `observed_at`;
  G13 `commitment.decide` raised on a malformed edge;
  G14 `criterion_verification.decomposition` divided by zero;
  G15 an empty obligation set certified `safe-stop` (exit 0);
  G16 a target-less tool made one ambiguous call escalate every later call;
  G17 an instruction/model channel mismatch still reported C1.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1230_pure_checker_defect_fixes.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1230-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API                 # noqa: E402
from longrun.tools import approvals                     # noqa: E402
from longrun.harness import approval_audit as AA        # noqa: E402
from longrun.harness import awareness as AW             # noqa: E402
from longrun.harness import criterion_verification as CV  # noqa: E402
from longrun.harness import effect_recovery as ER       # noqa: E402
from longrun.harness import evidence_replay as EVR      # noqa: E402
from longrun.harness import memory_authority as MA      # noqa: E402
from longrun.harness import memory_channel as MC        # noqa: E402
from longrun.harness import skill_gate as SG            # noqa: E402
from longrun.memory import fact_ledger as FL            # noqa: E402
from longrun.plan import commitment as CM               # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- G6: independence needs an identity ------------------------------------
anon = MA.corroborate({"vouchers": [{}, {}], "k": 2})
check("G6 two anonymous vouchers cannot elevate (no admitted domain)",
      anon["verdict"] != "elevated" and anon["independent"] == 0, anon)
check("G6 the gate stays closed for them",
      MA.gate({"parents": [{"origin": "untrusted"}],
               "action": {"tool": "pay", "value": "x"},
               "vouchers": [{}, {}], "k": 2})["verdict"] == "deny")
named = MA.corroborate({"vouchers": [{"principal": "a", "domain": "d1"},
                                     {"principal": "b", "domain": "d2"}], "k": 2})
check("G6 attributed independent vouchers still elevate",
      named["verdict"] == "elevated" and named["independent"] == 2, named)

# ---- G7: a token must name every field it approves -------------------------
TOK = {"tool": "pay", "value": "bob", "amount": 100, "nonce": "n1"}
check("G7 an action that omits an approved field is refused",
      MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "bob"}})["verdict"]
      == "action-mismatch")
check("G7 an approved field with a different value is refused",
      MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "bob",
                                             "amount": 1}})["verdict"]
      == "action-mismatch")
check("G7 a token with no nonce is refused (single use is unverifiable)",
      MA.authorize({"token": {"tool": "pay", "value": "bob"},
                    "action": {"tool": "pay", "value": "bob"}})["verdict"]
      == "incomplete-token")
check("G7 an empty nonce already in `used` is not authorized",
      MA.authorize({"token": {"tool": "pay", "value": "bob", "nonce": ""},
                    "action": {"tool": "pay", "value": "bob"}, "used": [""]})["verdict"]
      != "authorized")
check("G7 the exact approved call still authorizes",
      MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "bob",
                                             "amount": 100}})["verdict"] == "authorized")

# ---- G8: dependency order must not decide the verdict ----------------------
CAPS = {"pay": {"idempotent": False}, "reserve": {"read_after_write": True}}
_STATES = [{"obligation": "b", "kind": "readback-committed"}]
_late = {"capabilities": CAPS, "evidence": _STATES, "proposed": [],
         "obligations": [{"id": "a", "action": "pay", "requires": ["b"]},
                         {"id": "b", "action": "reserve"}]}
_early = dict(_late, obligations=list(reversed(_late["obligations"])))
check("G8 a committed dependency listed later is still proven",
      ER.adjudicate(_late)["findings"] == [] and ER.adjudicate(_early)["findings"] == [],
      (ER.adjudicate(_late)["findings"], ER.adjudicate(_early)["findings"]))
check("G8 the certificate no longer depends on list order",
      ER.adjudicate(_late)["certificate"] == ER.adjudicate(_early)["certificate"])
_unproven = dict(_late, evidence=[{"obligation": "a", "kind": "timeout"}])
check("G8 a genuinely unproven dependency is still flagged",
      any(f["kind"] == "blocked-by-unproven-dependency"
          for f in ER.adjudicate(_unproven)["findings"]))

# ---- G9: fact-ledger invariants -------------------------------------------
led = FL.Ledger()
led.apply({"key": "k", "value": "a", "trust": 1, "ts": 1})
check("G9 a lower-trust claim cannot replace any trusted incumbent",
      led.apply({"key": "k", "value": "b", "trust": 0, "ts": 2})["status"]
      == "held-untrusted" and led.resolve("k")["value"] == "a")
check("G9 verify() now re-checks I5", led.verify()["verdict"] == "holds")
bad = FL.Ledger()
bad.entries = [{"key": "k", "value": "hi", "source": "", "trust": 3, "from": 1,
                "to": 2, "deleted": False, "event": "", "superseded": True},
               {"key": "k", "value": "lo", "source": "", "trust": 1, "from": 2,
                "to": None, "deleted": False, "event": ""}]
check("G9 a decreasing lineage is reported as I5",
      any(p["invariant"] == "I5" for p in bad.verify()["problems"]), bad.verify())
_noerr = FL.Ledger().apply({"key": "k", "value": "v", "trust": "high"})
check("G9 a non-numeric trust does not abort the ingest",
      _noerr["status"] == "opened", _noerr)
_nots = FL.Ledger()
_nots.apply({"key": "k", "value": "a", "trust": 2})
_nots.apply({"key": "k", "value": "b", "trust": 3})
check("G9 an untimestamped supersede leaves only the current value open",
      _nots.verify()["verdict"] == "holds" and _nots.resolve("k")["value"] == "b",
      _nots.verify())

# ---- G10: an ambiguous outcome is unknown, not failed ---------------------
rec = approvals.create("shell.exec", {"command": "make test"},
                       decision="auto_approved")
approvals.record_outcome(rec["id"], None, witness="")
_rows = [r for r in approvals.audit_records() if r["id"] == rec["id"]]
check("G10 the store keeps the effect unknown", _rows and _rows[0]["effect"]["applied"] is None,
      _rows)
AUD = AA.audit(_rows)
check("G10 the audit counts it as unknown, not incomplete",
      AUD["counts"]["approved_unknown"] == 1
      and AUD["counts"]["approved_incomplete"] == 0
      and AUD["verdict"] == "clean", AUD)

# ---- G11: leak probe with a zero total ------------------------------------
LEAK = EVR.leak([{"total": 0, "undated": 0}])
check("G11 a zero-total row is a clean probe, not a crash",
      [f["kind"] for f in LEAK["findings"]] == ["no-leak-detected"], LEAK)

# ---- G12: snapshot with an ISO timestamp ----------------------------------
SNAP = AW.snapshot([{"route": "r", "observed_at": "2026-11-19T10:00:00Z"}],
                   now=1763500000000)
check("G12 an unparseable timestamp is kept without an age",
      SNAP["rows"] and SNAP["rows"][0].get("age_ms") is None, SNAP)
NUM = AW.snapshot([{"route": "r", "observed_at": 1000}], now=2000, max_age_ms=10000)
check("G12 a numeric timestamp still gets its age", NUM["rows"][0]["age_ms"] == 1000, NUM)

# ---- G13: malformed commitment edge ---------------------------------------
DEC = CM.decide({"actions": ["a", "b"], "edges": [["a"]], "broken": ["a"]})
check("G13 a malformed edge is ignored instead of raising",
      DEC.get("decision") in ("repair", "replan") and DEC.get("chains") == 2, DEC)

# ---- G14: decomposition density -------------------------------------------
DECO = CV.decomposition("must always validate input", expected_per_words=0)
check("G14 a zero density is refused with a finding",
      [f["kind"] for f in DECO["findings"]] == ["invalid-density"], DECO)
OKD = CV.decomposition("one two three four five six seven eight nine ten",
                       expected_per_words=5)
check("G14 a valid density still estimates", OKD.get("estimate") == 2, OKD)

# ---- G15: nothing adjudicated proves nothing ------------------------------
EMPTY = ER.adjudicate({"obligations": [],
                       "evidence": [{"obligation": "x", "kind": "timeout"}]})
check("G15 an empty obligation set is incomplete, never safe-stop",
      EMPTY["certificate"] == "incomplete", EMPTY)

# ---- G16: a target-less tool's identity is its arguments ------------------
_TMO = [{"action": "tool", "tool": "shell.exec", "args": {"command": "deploy"},
         "tool_result": {"ok": False, "exit_code": 124}}]
check("G16 the identical command still asks after an ambiguous outcome",
      API._recovery_escalation("shell.exec", {"command": "deploy"}, _TMO)[0]
      == "recovery-retry-would-duplicate")
check("G16 an unrelated command no longer asks",
      API._recovery_escalation("shell.exec", {"command": "date"}, _TMO) == (None, None))

# ---- G17: the channel follows the authority -------------------------------
MIS = MC.classify({"trigger": "instruction", "authority": "model"})
check("G17 an instruction whose content the model decides is not C1",
      MIS["verdict"] == "authority-mismatch" and MIS["channel"] is None, MIS)
POL = MC.classify({"trigger": "policy", "authority": "instruction"})
check("G17 a policy write decided by the instruction is C1",
      POL["verdict"] == "authority-mismatch" and POL["channel"] == "C1", POL)

# ---- I-3: a duplicate candidate id is never silently dropped --------------
_DUP = SG.select([{"id": "x", "gain": 1, "schema_ok": True, "replay_delta": 0.1,
                   "semantic_ok": True},
                  {"id": "x", "gain": 5, "schema_ok": True, "replay_delta": 0.1,
                   "semantic_ok": True}])
check("I-3 the duplicate is listed as unadmitted, not vanished",
      _DUP["unadmitted"] == ["x"] and _DUP["hot"] == ["x"], _DUP)

# ---- verdict --------------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
