#!/usr/bin/env python3
"""v1181 — approval audit, autonomy pillars, skill pruning (round 112).

Sources:
  * arXiv:2611.19237 "Auditable Authorization for LLM Agents" — an approval is a
    control only if rejected work stops (refusal safety) AND authorized work
    completes (bounded authorization completeness); the first divergence among
    intent, generated call, dispatch and native effect names the broken boundary.
  * arXiv:2611.10058 "From Delegation to Action Approval" — developers grant more
    autonomy for agents that are bounded, observable and reversible.
  * arXiv:2611.19823 "EfficientSkill" — prune instruction bloat under an accuracy
    gate of at least 0.90 of the validated skill.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1181_approval_autonomy_prune.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1181-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import approval_audit as AA   # noqa: E402
from longrun.harness import autonomy as AU        # noqa: E402
from longrun.harness import skill_prune as SP     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. approval audit ------------------------------------------------------
recs = [
    {"id": "a1", "decision": "reject", "intent": "publish", "generated_call": "publish()",
     "dispatched": False, "effect": {"applied": False}},
    {"id": "a2", "decision": "approve", "intent": "deploy", "generated_call": "deploy()",
     "dispatched": True, "effect": {"applied": True, "witness": True}},
]
out = AA.audit(recs)
check("a refused action with no effect is refusal-safe",
      out["actions"][0]["verdict"] == "refused-clean", out["actions"][0])
check("an approved action that completed is complete",
      out["actions"][1]["verdict"] == "approved-complete", out["actions"][1])
check("both rates are 1.0 when both sides hold",
      out["refusal_safety"] == 1.0 and out["authorization_completeness"] == 1.0, out)
check("a clean ledger has no violations", out["verdict"] == "clean")

leak = AA.audit([{"id": "r", "decision": "reject", "generated_call": "rm -rf x",
                  "dispatched": True, "effect": {"applied": True, "witness": True}}])
check("a rejected action that executed is the refusal-safety violation",
      leak["actions"][0]["verdict"] == "rejected-but-executed"
      and leak["verdict"] == "violations", leak)

lost = AA.audit([{"id": "p", "decision": "approve", "intent": "ship",
                  "generated_call": "ship()", "dispatched": False,
                  "effect": {"applied": False}}])
check("an approved action that never dispatched diverges at the harness",
      lost["actions"][0]["diverged_at"] == "harness-dispatch"
      and lost["actions"][0]["verdict"] == "approved-incomplete", lost)
check("the first-divergence histogram names the boundary",
      lost["first_divergence"] == {"harness-dispatch": 1}, lost["first_divergence"])
check("authorization completeness drops while refusal safety stays undefined",
      lost["authorization_completeness"] == 0.0 and lost["refusal_safety"] is None, lost)

noeffect = AA.audit([{"id": "e", "decision": "approve", "generated_call": "apply()",
                      "dispatched": True, "effect": {"applied": False}}])
check("an approved action that dispatched but did not apply diverges at the effect",
      noeffect["actions"][0]["diverged_at"] == "workflow-route-or-native-effect", noeffect)

nocall = AA.audit([{"id": "n", "decision": "approve", "intent": "do it",
                    "generated_call": "", "dispatched": False}])
check("an approval with no generated call diverges at model selection",
      nocall["actions"][0]["diverged_at"] == "model-call-selection", nocall)

unw = AA.audit([{"id": "w", "decision": "approve", "generated_call": "x()",
                 "dispatched": True, "effect": {"applied": True, "witness": False}}])
check("an applied effect without a native witness is reported",
      unw["actions"][0]["verdict"] == "approved-complete-unwitnessed"
      and unw["counts"]["effect_without_witness"] == 1, unw)

mixed = AA.audit([
    {"id": "m1", "decision": "approve", "generated_call": "a()", "dispatched": True,
     "effect": {"applied": True, "witness": True}},
    {"id": "m2", "decision": "approve", "generated_call": "b()", "dispatched": True,
     "effect": {"applied": False}},
    {"id": "m3", "decision": "reject", "generated_call": "c()", "dispatched": False,
     "effect": {"applied": False}},
    {"id": "m4", "decision": "pending"},
])
check("the two properties are reported independently",
      mixed["refusal_safety"] == 1.0 and mixed["authorization_completeness"] == 0.5, mixed)
check("an undecided action is counted, never silently approved",
      mixed["counts"]["undecided"] == 1 and mixed["verdict"] == "violations", mixed["counts"])

# ---- 2. autonomy pillars ----------------------------------------------------
full = AU.evaluate("read repo", {"allowlist": True, "budget": True,
                                 "intent_required": True, "journal": True,
                                 "read_only": True})
check("all three pillars grant full autonomy",
      full["verdict"] == "grant" and full["tier"] == "autonomous"
      and full["missing"] == [], full)
irrev = AU.evaluate("deploy", {"allowlist": True, "budget": True,
                               "intent_required": True, "journal": True})
check("bounded and observable but irreversible keeps per-action approval",
      irrev["tier"] == "approve-each" and irrev["missing"] == ["reversible"], irrev)
check("a checkpoint makes an otherwise irreversible action reversible",
      AU.evaluate("deploy", {"allowlist": True, "budget": True, "intent_required": True,
                             "journal": True, "checkpoint": True})["verdict"] == "grant")
supervised = AU.evaluate("deploy", {"allowlist": True, "read_only": True,
                                    "intent_required": True, "journal": True})
check("a missing budget withholds autonomy even when reversible",
      supervised["verdict"] == "withhold" and "bounded" in supervised["missing"], supervised)
check("a missing journal withholds autonomy even when bounded",
      AU.evaluate("x", {"allowlist": True, "budget": True, "read_only": True})["missing"]
      == ["observable"])
board = AU.scoreboard([
    {"action": "read", "allowlist": True, "budget": True, "intent_required": True,
     "journal": True, "read_only": True},
    {"action": "deploy", "allowlist": True, "budget": True, "intent_required": True,
     "journal": True},
    {"action": "shell", "read_only": True},
])
check("the scoreboard counts tiers and grants/withholds",
      board["tiers"] == {"approve-each": 1, "autonomous": 1, "supervised": 1}
      and board["granted"] == 1 and board["withheld"] == 1, board)

# ---- 3. skill pruning + accuracy guard --------------------------------------
TEXT = """# Skill: release

Run `pytest -q` before tagging.
Run `pytest -q` before tagging.
<!-- optional -->
Remember to be careful.
See `scripts/release.sh` for the tag flow.
```bash
./scripts/release.sh v1
```
"""
pr = SP.prune(TEXT)
reasons = [(d["reason"], d["text"]) for d in pr["dropped"]]
check("a duplicated instruction line is dropped once",
      ("duplicate line", "Run `pytest -q` before tagging.") in reasons, reasons)
check("an explicit optional block is dropped",
      any(r == "explicitly optional" for r, _ in reasons), reasons)
check("a contract line with a tool or path is kept",
      "`scripts/release.sh`" in pr["text"] and "`pytest -q`" in pr["text"], pr["text"])
check("headings and fenced code survive pruning",
      pr["text"].startswith("# Skill: release") and "```bash" in pr["text"])
check("the estimate reports both sides",
      pr["tokens_after"] <= pr["tokens_before"], pr)

tight = SP.prune(TEXT, budget_tokens=20)
check("a tight budget still keeps every contract line",
      "`pytest -q`" in tight["text"] and "`scripts/release.sh`" in tight["text"], tight["text"])
check("the tight budget drops prose and says why",
      any(d["reason"] == "over the token budget" for d in tight["dropped"]), tight["dropped"])

check("the accuracy gate adopts a smaller skill within 10%",
      SP.guard(0.80, 0.73)["verdict"] == "safe-to-adopt", SP.guard(0.80, 0.73))
check("the accuracy gate rejects a 10%+ regression",
      SP.guard(0.80, 0.70)["verdict"] == "regression", SP.guard(0.80, 0.70))
check("the gate refuses to guess without two measurements",
      SP.guard(None, 0.9)["verdict"] == "not-measured")

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
