#!/usr/bin/env python3
"""v1184 — fact ledger, fault episode record, API usage contract (round 115).

Sources:
  * arXiv:2611.20927 "LEDGER" — current value, validity interval, provenance and
    deletion state; I1 deletion, I2 supersession, I3 temporal, I4 dedupe,
    I5 contamination.
  * arXiv:2611.13254 "Dependable Long-Horizon LLM Agents" — an episode record
    (origin, propagation, detection, response, consequence) plus the control
    families that reach it.
  * arXiv:2611.15207 "Pre-QED" — an API usage contract with illegal call orders,
    so a proof covers every well-behaved caller instead of one sequence.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1184_ledger_episodes_contract.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1184-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import fact_ledger as FL        # noqa: E402
from longrun.harness.checks import fault_episode as FE  # noqa: E402
from longrun.harness.checks import api_contract as AC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. fact ledger ---------------------------------------------------------
led = FL.Ledger()
a = led.apply({"id": "e1", "key": "Service Port", "value": "8790",
               "source": "config", "trust": 3, "ts": 1})
check("a first claim opens the current value", a["status"] == "opened", a)
check("the current value resolves", led.resolve("service port")["value"] == "8790")
check("a replayed event id is ignored (I4)",
      led.apply({"id": "e1", "key": "service port", "value": "9999",
                 "source": "x", "trust": 3, "ts": 2})["status"] == "duplicate-ignored")
check("the same value is not a new version (I4)",
      led.apply({"id": "e2", "key": "service port", "value": "8790",
                 "source": "note", "trust": 2, "ts": 3})["status"] == "unchanged")
b = led.apply({"id": "e3", "key": "service port", "value": "8080",
               "source": "user", "trust": 3, "ts": 5})
check("an accepted update supersedes the old value (I2)", b["status"] == "superseded")
check("only the current value is served", led.resolve("service port")["value"] == "8080")
check("a past question returns the value that held (I3)",
      led.resolve("service port", as_of=3)["value"] == "8790")

held = led.apply({"id": "e4", "key": "service port", "value": "1",
                  "source": "guess", "trust": 1, "ts": 6})
check("a less trusted source cannot replace the current value (I5)",
      held["status"] == "held-untrusted" and led.resolve("service port")["value"] == "8080",
      held)

led2 = FL.Ledger()
led2.apply({"id": "f1", "key": "db host", "value": "old", "source": "ops",
            "trust": 3, "ts": 1})
led2.apply({"id": "f2", "key": "db host", "value": "new", "source": "ops",
            "trust": 3, "ts": 4})
forgot = led2.forget("db host", ts=6)
check("forgetting closes the interval with a tombstone", forgot["status"] == "deleted")
check("a deleted fact is never served again (I1)",
      led2.resolve("db host")["value"] is None
      and led2.resolve("db host")["status"] == "deleted", led2.resolve("db host"))
check("even a past question does not resurrect it (I1)",
      led2.resolve("db host", as_of=2)["value"] is None)
check("evidence excludes the deleted fact", led2.evidence(["db host"]) == [])
check("the ledger verifies its own invariants", led.verify()["verdict"] == "holds"
      and led2.verify()["verdict"] == "holds", (led.verify(), led2.verify()))

broken = FL.Ledger()
broken.apply({"id": "x1", "key": "k", "value": "v1", "source": "s", "trust": 3, "ts": 1})
broken.entries.append({"key": "k", "value": "v2", "source": "s", "trust": 3,
                       "from": 2, "to": None, "deleted": False, "event": "x2"})
check("two open values for one key violate I2",
      any(p["invariant"] == "I2" for p in broken.verify()["problems"]), broken.verify())

# ---- 2. fault episode ------------------------------------------------------
REC = {
    "origin": {"phase": "execution", "domain": "task", "fault_in": "state",
               "step": 10, "source": "agent"},
    "symptom": {"step": 80, "what": "wrong file edited"},
    "propagation": [{"from": "belief", "to": "action"}],
    "detection": {"flagged": True},
    "response": "revert",
    "consequence": {"service": "integrity"},
    "evidence_before": True,
    "run_length": 100,
}
res = FE.audit(REC)
check("a full episode record is complete", res["verdict"] == "complete", res)
ctrls = {c["family"] for c in FE.controls(REC)["controls"]}
check("controls name the families that reach it",
      {"independent-judge", "task-contract", "provenance", "checkpoint"} <= ctrls, ctrls)

missing = FE.audit({k: v for k, v in REC.items() if k != "origin"})
check("a record without an origin is unusable",
      missing["verdict"] == "unusable"
      and any(f["kind"] == "missing-field" for f in missing["findings"]), missing)
late = FE.audit({**REC, "origin": {**REC["origin"], "step": 80}})
check("a late origin is flagged, not hidden",
      any(f["kind"] == "late-origin" for f in late["findings"]), late)
unflagged = FE.audit({**REC, "detection": {"flagged": False}})
check("evidence present but never flagged is a finding",
      any(f["kind"] == "evidence-not-flagged" for f in unflagged["findings"]), unflagged)
ignored = FE.audit({**REC, "response": "none"})
check("a flagged deviation with no response is a finding",
      any(f["kind"] == "flagged-not-acted" for f in ignored["findings"]), ignored)
replay = FE.audit({**REC, "origin": {**REC["origin"], "fault_in": "plan"},
                   "response": "restore"})
check("restoring a plan fault would replay it",
      any(f["kind"] == "restore-would-replay-the-fault" for f in replay["findings"]), replay)
bad_service = FE.audit({**REC, "consequence": {"service": "speed"}})
check("a consequence outside the three attributes is flagged",
      any(f["kind"] == "invalid-service" for f in bad_service["findings"]), bad_service)
tool_ctl = {c["family"] for c in FE.controls({**REC, "origin": {
    **REC["origin"], "domain": "tool"}})["controls"]}
check("a tool-domain fault adds the environment re-check",
      "recheck-against-environment" in tool_ctl, tool_ctl)

# ---- 3. API contract -------------------------------------------------------
CONTRACT = {
    "calls": ["init", "read", "write", "close"],
    "rules": [
        {"type": "requires_before", "call": "write", "before": ["init"]},
        {"type": "forbidden_before", "call": "read", "before": ["close"]},
        {"type": "no_duplicate", "call": "init"},
    ],
}
good = AC.check(CONTRACT, ["init", "read", "write", "close"])
check("a legal sequence passes", good["verdict"] == "pass" and good["violations"] == [], good)
check("coverage reports every declared call exercised",
      good["exercised"] == ["close", "init", "read", "write"] and good["unexercised"] == [],
      good)

nopre = AC.check(CONTRACT, ["read", "write"])
check("a missing successful predecessor is a violation",
      any(v["rule"] == "requires_before" and v["call"] == "write"
          for v in nopre["violations"]), nopre)
failed_pre = AC.check(CONTRACT, [{"call": "init", "ok": False}, "write"])
check("a FAILED predecessor does not satisfy the rule",
      any(v["rule"] == "requires_before" for v in failed_pre["violations"]), failed_pre)
forbidden = AC.check(CONTRACT, ["close", "read"])
check("a forbidden order is a violation",
      any(v["rule"] == "forbidden_before" and v["call"] == "read"
          for v in forbidden["violations"]), forbidden)
dup = AC.check(CONTRACT, ["init", "init", "write"])
check("a no-duplicate call is reported on the second occurrence",
      any(v["rule"] == "no_duplicate" for v in dup["violations"]), dup)
unknown = AC.check(CONTRACT, ["init", "delete"])
check("a call outside the contract is reported",
      any(v["rule"] == "declared-calls" and v["call"] == "delete"
          for v in unknown["violations"]), unknown)
partial = AC.check(CONTRACT, ["init"])
check("unexercised declared calls are named, not assumed",
      partial["unexercised"] == ["close", "read", "write"], partial)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
