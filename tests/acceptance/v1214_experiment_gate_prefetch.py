#!/usr/bin/env python3
"""v1214 — harness update gate, experiment ledger, context prefetch (round 145).

Sources:
  * arXiv:2611.23651 "Safe Personal RSI" — the named-block harness, the
    differential and absolute search, strict-majority confirmation, rollback
    localisation by gain retention, verification held apart from admission, the
    suite-normalised risk gate, the severe-case veto, utility, transfer and the
    audit's misreadings.
  * arXiv:2611.23678 "Evaluating Governed LLM-Driven ML Experimentation" — the
    five desiderata, the pre-run guards, the one-terminal-record invariant,
    acceptance/invalid/provenance rates, the repeated-bad rate, the governed vs
    ungoverned counterfactual, the structural relabeller and the taxonomy.
  * arXiv:2611.23857 "Neural Memory Orchestration" — per-target sliding
    windows, online ordinal ranks over deltas, the narrow contract, arrival
    latency, local vs remote benefit, graceful degradation and warm-up.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1214_experiment_gate_prefetch.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1214-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import harness_update_gate as UG   # noqa: E402
from longrun.harness import experiment_ledger as EL     # noqa: E402
from longrun.harness import context_prefetch as CP      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ---- 1. harness update gate (Safe Personal RSI) -------------------------
h = UG.blocks([{"name": "role", "text": "daily email assistant"},
               {"name": "disclosure", "text": "summarise before sharing"}])
check("a named-block harness is valid", h["verdict"] == "harness-valid")
check("the block order is preserved", [b["name"] for b in h["blocks"]] == ["role", "disclosure"])
check("the digest is stable",
      UG.blocks([{"name": "role", "text": "x"}])["digest"]
      == UG.blocks([{"name": "role", "text": "x"}])["digest"])
check("a changed block changes the digest",
      UG.blocks([{"name": "role", "text": "x"}])["digest"]
      != UG.blocks([{"name": "role", "text": "y"}])["digest"])
check("a duplicate block is named",
      UG.blocks([{"name": "a"}, {"name": "a"}])["verdict"] == "harness-malformed")
check("an unnamed block is named",
      UG.blocks([{"text": "x"}])["unnamed"] == [0])

d = UG.differential([
    {"case": "c1", "parent_violation": None, "candidate_violation": "unauthorized_commitment"},
    {"case": "c2", "parent_violation": "privacy_oversharing", "candidate_violation": "privacy_oversharing"},
    {"case": "c3", "parent_violation": "source_confusion", "candidate_violation": None},
    {"case": "c4", "parent_violation": None, "candidate_violation": None},
])
check("a new violation is a regression", d["regressions"] == ["c1"])
check("a violation present in both is shared", d["shared"] == ["c2"])
check("a violation the candidate clears is a fix", d["fixed"] == ["c3"])
check("a clean pair is clean", d["clean"] == ["c4"])
check("a regression outranks shared failures", d["verdict"] == "candidate-regresses")
check("shared failures are still reported",
      UG.differential([{"case": "c", "parent_violation": "x", "candidate_violation": "x"}])["verdict"]
      == "shared-failures-remain")
check("a strictly better candidate is not worse",
      UG.differential([{"case": "c", "parent_violation": "x", "candidate_violation": None}])["verdict"]
      == "candidate-not-worse")

check("two of three violating replays confirm",
      UG.confirm([{"violation": True}, {"violation": True}, {"violation": False}])["verdict"]
      == "confirmed")
check("one of three violating replays does not confirm",
      UG.confirm([{"violation": True}, {"violation": False}, {"violation": False}])["verdict"]
      == "unconfirmed")
check("no violation is not confirmed",
      UG.confirm([{"violation": False}, {"violation": False}])["verdict"] == "not-confirmed")
check("no replay is insufficient evidence",
      UG.confirm([])["verdict"] == "insufficient-evidence")
check("an incomplete replay is insufficient when all are required",
      UG.confirm([{"violation": True}, {"violation": True, "completed": False}],
                 require_all=True)["verdict"] == "insufficient-evidence")
check("an incomplete replay still counts when not required",
      UG.confirm([{"violation": True}, {"violation": True, "completed": False}])["verdict"]
      == "confirmed")

loc = UG.localize([
    {"block": "disclosure", "clears_violation": True, "gain": 0.10, "gain_removed": 0.09},
    {"block": "role", "clears_violation": True, "gain": 0.10, "gain_removed": 0.04},
    {"block": "tone", "clears_violation": False, "gain": 0.10, "gain_removed": 0.10},
])
check("the block that keeps 90% of the gain is implicated", loc["implicated"] == ["disclosure"])
check("the block that keeps 40% is not implicated",
      [row["implicated"] for row in loc["examined"] if row["block"] == "role"] == [False])
check("clearing the violation is required",
      [row["implicated"] for row in loc["examined"] if row["block"] == "tone"] == [False])
check("a zero measured gain retains 1.0 by convention",
      UG.localize([{"block": "a", "clears_violation": True, "gain": 0.0,
                    "gain_removed": 0.0}])["examined"][0]["retention"] == 1.0)
check("an unreadable gain is reported, not guessed",
      UG.localize([{"block": "a", "clears_violation": True, "gain": None,
                    "gain_removed": 0.1}])["verdict"] == "insufficient-evidence")
check("no implicated block is a verdict",
      UG.localize([{"block": "a", "clears_violation": False, "gain": 0.1,
                    "gain_removed": 0.1}])["verdict"] == "no-block-implicated")

check("a clean repair passes verification",
      UG.verify({"violations": 0, "replays": 3, "complete": 3,
                 "parent_utility": 0.80, "working_utility": 0.82})["verdict"]
      == "verification-passes")
check("an observed violation fails verification",
      UG.verify({"violations": 1, "replays": 3, "complete": 3,
                 "parent_utility": 0.8, "working_utility": 0.9})["verdict"]
      == "verification-fails")
check("a utility regression fails verification",
      UG.verify({"violations": 0, "replays": 3, "complete": 3,
                 "parent_utility": 0.8, "working_utility": 0.7})["reasons"]
      == ["utility-regresses"])
check("an incomplete replay fails verification",
      UG.verify({"violations": 0, "replays": 3, "complete": 2,
                 "parent_utility": 0.8, "working_utility": 0.8})["reasons"]
      == ["incomplete-replays"])

r1 = UG.risk([{"violation": None}] * 19 + [{"violation": "unauthorized_disclosure"}])
check("one flagged replay in twenty is 5%", close(r1["max_rate"], 0.05))
check("5% is inside the gate", r1["verdict"] == "risk-within-gate")
r2 = UG.risk([{"violation": "unauthorized_disclosure"}] * 3 + [{"violation": None}] * 17)
check("three flagged replays in twenty is 15%", close(r2["max_rate"], 0.15))
check("15% exceeds the gate", r2["verdict"] == "risk-exceeds-gate")
check("an unknown category still counts in the primary rate",
      close(UG.risk([{"violation": "novel"}] * 2 + [{"violation": None}] * 2)["primary_rate"], 0.5))

u = UG.utility([{"success": True, "violation": False, "cost": 10,
                 "latency_ms": 30000, "confirmations": 1}])
check("the utility formula clips every penalty", close(u["utility"], 0.75))
check("a violation removes the success term",
      close(UG.utility([{"success": True, "violation": True}])["utility"], 0.0))
check("no replay is not a measurement",
      UG.utility([])["verdict"] == "no-replays")

PARENT = {"replays": 5, "completed": 5, "max_risk": 0.05, "utility": 0.70,
          "success": 0.80, "cost": 1.0}
check("a confirmed disclosure case vetoes the attempt",
      UG.admit({"parent": PARENT, "working": dict(PARENT, utility=0.99),
                "severe_confirmed": True})["criterion"] == "severe-case-veto")
check("four replays are insufficient evidence",
      UG.admit({"parent": dict(PARENT, replays=4), "working": PARENT})["decision"]
      == "insufficient-evidence")
check("an incomplete parent is insufficient evidence",
      UG.admit({"parent": dict(PARENT, completed=4), "working": PARENT})["decision"]
      == "insufficient-evidence")
check("risk above the cap rejects",
      UG.admit({"parent": PARENT, "working": dict(PARENT, max_risk=0.12)})["criterion"]
      == "risk")
check("risk above the parent rejects even below the cap",
      UG.admit({"parent": PARENT, "working": dict(PARENT, max_risk=0.08)})["decision"]
      == "reject")
check("a nonnegative utility gain admits",
      UG.admit({"parent": PARENT, "working": dict(PARENT, utility=0.75)})["verdict"]
      == "adopted")
check("the cost branch admits inside the success tolerance",
      UG.admit({"parent": PARENT, "working": dict(PARENT, utility=0.69, success=0.79,
                                                  cost=0.85)})["criterion"] == "cost")
check("a success drop beyond tolerance rejects",
      UG.admit({"parent": PARENT, "working": dict(PARENT, utility=0.69, success=0.70,
                                                  cost=0.85)})["criterion"] == "utility")
check("a smaller cost gain is not enough",
      UG.admit({"parent": PARENT, "working": dict(PARENT, utility=0.69, success=0.79,
                                                  cost=0.95)})["decision"] == "reject")

tr = UG.transfer({"target_before": 0.690, "target_after": 0.179})
check("a transfer reports the target delta", close(tr["target_delta"], -0.511))
check("a transfer stays an observation, not an admission",
      "not its admission" in tr["caveat"])
check("an unmeasured transfer says so",
      UG.transfer({})["verdict"] == "transfer-unmeasured")

aud = UG.audit({"utility_only": True, "max_only": True, "repair_as_admission": True,
                "deletion_as_forgetting": True})
check("utility-only adoption is a finding",
      "utility-only-adoption" in [f["kind"] for f in aud["findings"]])
check("a maximum that hides a category is a finding",
      "max-hides-a-category" in [f["kind"] for f in aud["findings"]])
check("repair treated as admission is a finding",
      "repair-treated-as-admission" in [f["kind"] for f in aud["findings"]])
check("entry deletion treated as forgetting is a finding",
      "entry-deletion-as-forgetting" in [f["kind"] for f in aud["findings"]])
check("a clean record has no misreading",
      UG.audit({})["findings"] == [{"kind": "audit-conditions-met"}])
check("an empty profile raises every check", len(UG.advise({})["findings"]) == 8)
FULL_PROFILE = {k: True for k in (
    "tests_updates_before_adoption", "compares_against_the_parent",
    "confirms_with_replays", "rolls_back_to_localise",
    "separates_verification_from_admission", "keeps_a_severe_case_veto",
    "checks_runtime_controls_separately", "records_the_decision")}
check("a complete profile raises none", UG.advise(FULL_PROFILE)["findings"] == [])

# ---- 2. experiment ledger (governed experimentation) --------------------
SCOPE = {"editable_paths": ["train.py"], "frozen_paths": ["prepare.py", "data/"]}
check("an in-scope edit passes", EL.scope(dict(SCOPE, touched=["train.py"]))["verdict"]
      == "scope-clear")
check("a frozen file is rejected",
      EL.scope(dict(SCOPE, touched=["prepare.py"]))["verdict"] == "invalid_edit_scope")
check("a frozen directory is rejected by prefix",
      EL.scope(dict(SCOPE, touched=["data/shard.bin"]))["violations"][0]["reason"] == "frozen")
check("an unlisted file is rejected",
      EL.scope(dict(SCOPE, touched=["extra.py"]))["violations"][0]["reason"] == "not-editable")

check("an empty patch is a no-op",
      EL.noop({"patch_empty": True})["verdict"] == "no_op_patch")
check("a byte-identical patch is a no-op",
      EL.noop({"patch_hash": "abc", "baseline_hash": "abc",
               "touched": ["train.py"]})["verdict"] == "no_op_patch")
check("a changed patch is materialised",
      EL.noop({"patch_hash": "abc", "baseline_hash": "def",
               "touched": ["train.py"]})["verdict"] == "patch-materialised")

check("a missing field fails the precondition",
      EL.precondition({"summary": "s"})["verdict"] == "proposal_precondition_failed")
check("new equal to old fails the precondition",
      EL.precondition({"summary": "s", "param": "lr", "old_value": 1,
                       "new_value": 1})["reasons"] == ["new-equals-old"])
check("a well-formed proposal passes",
      EL.precondition({"summary": "s", "param": "lr", "old_value": 1,
                       "new_value": 2})["verdict"] == "precondition-ok")

check("an improvement is kept",
      EL.decide({"valid": True, "candidate": 0.78, "best": 0.77})["decision"] == "kept")
check("a non-improvement is discarded, not failed",
      EL.decide({"valid": True, "candidate": 0.77, "best": 0.77})["decision"] == "discarded")
check("a discarded trial carries degraded_metric",
      EL.decide({"valid": True, "candidate": 0.77, "best": 0.78})["failure_category"]
      == "degraded_metric")
check("a minimised metric improves downward",
      EL.decide({"valid": True, "candidate": 0.9, "best": 1.0, "direction": "minimize"})
      ["decision"] == "kept")
check("an invalid trial is failed_invalid",
      EL.decide({"valid": False, "category": "no_op_patch"})["decision"] == "failed_invalid")
check("a missing metric is failed_invalid",
      EL.decide({"valid": True, "candidate": None, "best": 1})["failure_category"]
      == "metric_missing")

LEDGER = [
    {"trial_id": "t1", "budget_index": 1, "decision": "kept", "metric": 0.80},
    {"trial_id": "t2", "budget_index": 2, "decision": "discarded", "metric": 0.79},
    {"trial_id": "t3", "budget_index": 3, "decision": "failed_invalid"},
]
lg = EL.ledger(LEDGER)
check("three slots, three terminal records", lg["terminal"] == 3)
check("the ledger is complete", lg["verdict"] == "ledger-complete")
check("completeness is 1.0", close(lg["completeness"], 1.0))
check("an open slot is a violation",
      EL.ledger(LEDGER + [{"trial_id": "t4", "budget_index": 4,
                           "decision": "executing"}])["violations"][0]["kind"] == "slot-open")
check("a re-opened trial is an overwritten record",
      [v["kind"] for v in EL.ledger(LEDGER + [{"trial_id": "t1", "budget_index": 4,
                                               "decision": "kept"}])["violations"]]
      == ["record-overwritten"])
check("a gap in budget indices is a skipped slot",
      [v["kind"] for v in EL.ledger([
          {"trial_id": "t1", "budget_index": 1, "decision": "kept"},
          {"trial_id": "t3", "budget_index": 3, "decision": "discarded"},
      ])["violations"]] == ["slot-skipped"])
check("a falling best metric is a violation",
      "best-not-monotone" in [v["kind"] for v in EL.ledger([
          {"trial_id": "t1", "budget_index": 1, "decision": "kept", "metric": 0.80},
          {"trial_id": "t2", "budget_index": 2, "decision": "kept", "metric": 0.70},
      ])["violations"]])

met = EL.metrics([
    {"decision": "kept", "provenance": {k: "h" for k in EL.PROVENANCE_IDS},
     "patch_ref": "p", "raw_log_ref": "l"},
    {"decision": "discarded", "provenance": {k: "h" for k in EL.PROVENANCE_IDS},
     "patch_ref": "p", "raw_log_ref": "l"},
    {"decision": "failed_invalid", "provenance": {k: "h" for k in EL.PROVENANCE_IDS}},
    {"decision": "failed_invalid", "provenance": {}},
])
check("acceptance rate is kept over all trials", close(met["acceptance_rate"], 0.25))
check("invalid rate is failed_invalid over all trials", close(met["invalid_rate"], 0.5))
check("provenance completeness counts all five IDs",
      close(met["provenance_completeness"], 0.75))
check("artifact coverage divides by materialised runs",
      close(met["artifact_reference_coverage"], 1.0))

rep = EL.repeated([
    {"target": "lr", "direction": "increase", "summary": "increase learning rate",
     "decision": "discarded"},
    {"target": "lr", "direction": "increase", "summary": "increase learning rate value",
     "decision": "discarded"},
    {"target": "lr", "direction": "increase", "summary": "increase learning rate value",
     "decision": "discarded", "references_rejection": True},
    {"target": "lr", "direction": "decrease", "summary": "increase learning rate value",
     "decision": "discarded"},
])
check("a near-duplicate of a rejected edit is repeated-bad", rep["flagged"] == [1])
check("the repeated-bad rate divides by the budget", close(rep["rate"], 0.25))
check("a corrective rationale clears the flag", 2 not in rep["flagged"])
check("a different direction is not a repeat", 3 not in rep["flagged"])

cf = EL.counterfactual([
    {"node": "autoresearch", "ran": 30, "governed_records": 30, "ungoverned_records": 0},
    {"node": "openml_bank", "ran": 20, "governed_records": 20, "ungoverned_records": 7},
])
check("the ungoverned ledger silently drops 43 of 50", cf["silent_drops"] == 43)
check("governed completeness is 1.0 on both rows",
      all(close(r["governed"], 1.0) for r in cf["rows"]))
check("the counterfactual names the loss", cf["verdict"] == "ungoverned-drops-failures")

check("perfect labels agree exactly",
      close(EL.relabel([{"assigned": "a", "observable": "a"}] * 4)["kappa"], 1.0))
split = EL.relabel([{"assigned": "a", "observable": "a"},
                    {"assigned": "a", "observable": "b"},
                    {"assigned": "b", "observable": "a"},
                    {"assigned": "b", "observable": "b"}])
check("chance-level agreement is kappa 0", close(split["kappa"], 0.0))
check("chance level is not structural agreement",
      split["verdict"] == "structural-disagreement")
balanced = ([{"assigned": "a", "observable": "a"}] * 9
            + [{"assigned": "a", "observable": "b"}]
            + [{"assigned": "b", "observable": "a"}]
            + [{"assigned": "b", "observable": "b"}] * 9)
check("the paper's kappa reads as almost perfect",
      EL.relabel(balanced)["band"] == "almost-perfect")
check("no records is not a kappa",
      EL.relabel([])["verdict"] == "no-records")

check("the taxonomy covers eight categories", len(EL.taxonomy()["categories"]) == 8)
check("a degraded metric belongs to the decision rule",
      [c for c in EL.taxonomy()["categories"] if c["category"] == "degraded_metric"][0]
      ["guard"] == "decision rule")
check("scope failures fire before the run",
      [c for c in EL.taxonomy()["categories"] if c["category"] == "invalid_edit_scope"][0]
      ["fires_at"] == "pre-run")

lad = EL.audit({"score_only": True, "discard_as_failure": True,
                "ledger_in_the_loop": True, "unverified_reset": True})
check("score-only is a finding", "score-only" in [f["kind"] for f in lad["findings"]])
check("discard-as-failure is a finding",
      "discard-treated-as-failure" in [f["kind"] for f in lad["findings"]])
check("an agent-owned ledger is a finding",
      "ledger-owned-by-the-agent" in [f["kind"] for f in lad["findings"]])
check("an unverified reset is a finding",
      "unverified-reset" in [f["kind"] for f in lad["findings"]])
check("an empty profile raises eight checks", len(EL.advise({})["findings"]) == 8)
check("a complete profile raises none",
      EL.advise({k: True for k in (
          "has_a_control_plane", "enforces_edit_scope_before_running",
          "appends_one_record_per_slot", "guards_against_mid_trial_crashes",
          "keeps_failed_and_discarded_distinct", "records_provenance_ids",
          "measures_repeated_bad_proposals", "verifies_the_start_state")})["findings"] == [])

# ---- 3. context prefetch (Overseer) ------------------------------------
events = [{"target": "p1", "address": a, "context": "ip"} for a in range(5)]
w = CP.window(events, size=3)
check("five events at size three emit one packet", len(w["packets"]) == 1)
check("the packet keeps the first window", w["packets"][0]["addresses"] == [0, 1, 2])
check("the remainder stays open", w["leftover"]["p1"] == 2)
two = CP.window([{"target": "a", "address": 1}, {"target": "b", "address": 2},
                 {"target": "a", "address": 3}, {"target": "b", "address": 4}], size=2)
check("targets are windowed independently", len(two["packets"]) == 2)
check("an unreadable event is reported",
      CP.window([{"target": "a", "address": "x"}])["unreadable"][0]["why"] == "event-unreadable")
check("no full window is a verdict",
      CP.window([{"target": "a", "address": 1}], size=3)["verdict"] == "no-full-window")

enc = CP.encode([100, 200, 300])
check("the first delta is the zero sentinel", enc["deltas"] == [0, 100, 100])
check("repeated deltas share a rank", enc["ranks"] == [1, 2, 2])
check("distinct deltas converge to two", enc["distinct_deltas"] == 2)
check("encoding succeeds", enc["verdict"] == "encoded")
check("a non-numeric address is refused",
      CP.encode(["x"])["verdict"] == "not-addressable")
check("no addresses is not an encoding", CP.encode([])["verdict"] == "no-addresses")
capped = CP.encode([100, 200, 300], cap=1)
check("a full table evicts the oldest delta", capped["evicted"] == 1)
check("the cap bounds the live vocabulary", capped["distinct_deltas"] == 1)

dec = CP.decode([2, 2], 100, {1: 0, 2: 100})
check("ranks decode back to absolute addresses", dec["addresses"] == [200, 300])
check("an evicted rank is reported, not invented",
      CP.decode([9], 100, {1: 0})["unresolved"] == [9])
check("no anchor is refused", CP.decode([1], None, {1: 0})["verdict"] == "no-anchor")

check("the request carries three fields",
      CP.contract({"target": "p", "contexts": ["i"], "addresses": [1]})["verdict"]
      == "contract-complete")
check("a missing field is named",
      CP.contract({"target": "p", "contexts": ["i"]})["missing"] == ["addresses"])
check("the reply needs only target and addresses",
      CP.contract({"reply": True, "target": "p", "addresses": [1]})["verdict"]
      == "contract-complete")

check("a prediction inside the inter-arrival time is in time",
      CP.prefetch({"latency_ms": 5, "interarrival_ms": 10})["verdict"]
      == "predictions-arrive-in-time")
check("a late prediction can still cut service time",
      CP.prefetch({"latency_ms": 20, "interarrival_ms": 10,
                   "reduces_service_time": True})["verdict"] == "late-but-still-useful")
check("a late prediction with no service benefit is late",
      CP.prefetch({"latency_ms": 20, "interarrival_ms": 10})["verdict"]
      == "predictions-arrive-late")
check("no latency is not a measurement",
      CP.prefetch({"latency_ms": 0, "interarrival_ms": 10})["verdict"]
      == "no-latency-recorded")

hilbert = CP.benefit([
    {"arm": "baseline", "runtime_s": 35.5, "major_faults": 123000},
    {"arm": "local", "runtime_s": 23.0, "major_faults": 90000},
    {"arm": "remote", "runtime_s": 29.0, "major_faults": 118000},
])
check("the local arm reproduces the ~35% runtime cut",
      close(hilbert["arms"]["local"]["runtime_reduction"], 1 - 23.0 / 35.5, 1e-6))
check("the remote arm reproduces the ~18% runtime cut",
      close(hilbert["arms"]["remote"]["runtime_reduction"], 1 - 29.0 / 35.5, 1e-6))
check("local removes ~27% of major faults",
      close(hilbert["arms"]["local"]["fault_reduction"], 1 - 90000 / 123000, 1e-6))
check("latency bounds the benefit when local beats remote",
      hilbert["verdict"] == "latency-bounds-the-benefit")
matmul = CP.benefit([
    {"arm": "baseline", "runtime_s": 450, "major_faults": 3500000},
    {"arm": "local", "runtime_s": 60, "major_faults": 350000},
    {"arm": "remote", "runtime_s": 125, "major_faults": 1800000},
])
check("matmul local is the paper's 7.5x", close(matmul["arms"]["local"]["runtime_reduction"],
                                               1 - 60.0 / 450.0, 1e-6))
check("matmul local cuts faults by about an order of magnitude",
      matmul["arms"]["local"]["fault_reduction"] >= 0.85)
check("a single arm with a gain is a benefit",
      CP.benefit([{"arm": "baseline", "runtime_s": 10},
                  {"arm": "local", "runtime_s": 8}])["verdict"] == "prefetch-helps")
check("no gain is no benefit",
      CP.benefit([{"arm": "baseline", "runtime_s": 10},
                  {"arm": "remote", "runtime_s": 10}])["verdict"] == "no-measurable-benefit")

check("a dead collector leaves the target correct",
      CP.degrade({"collector": "down", "target_correct": True})["verdict"]
      == "degrades-gracefully")
check("a dead collector emits no prediction",
      CP.degrade({"collector": "down", "predictions": 9})["predictions"] == 0)
check("a full queue drops rather than blocks",
      CP.degrade({"queue": "full", "predictions": 4})["verdict"] == "drops-on-full")
check("a blocking queue is named",
      CP.degrade({"queue": "full", "blocked": True})["verdict"] == "blocks-the-target")

wm = CP.warmup([
    {"faults_seen": 100, "accuracy": 0.40, "lifetime_faults": 500},
    {"faults_seen": 200, "accuracy": 0.86, "lifetime_faults": 500},
    {"faults_seen": 400, "accuracy": 0.95, "lifetime_faults": 500},
])
check("the plateau is where 90% of peak is reached", wm["plateau_faults"] == 200)
check("a long-lived target amortises warm-up", wm["verdict"] == "warmup-amortised")
check("a short-lived target never gets warm",
      CP.warmup([{"faults_seen": 100, "accuracy": 0.40, "lifetime_faults": 150},
                 {"faults_seen": 200, "accuracy": 0.90, "lifetime_faults": 150}])["verdict"]
      == "warmup-dominates")
check("no target is not a warm-up measurement", CP.warmup([])["verdict"] == "no-targets")

cad = CP.audit({"simulator_only": True, "ignores_latency": True,
                "blocking_backpressure": True, "unauthenticated_channel": True})
check("simulator-only is a finding", "simulator-only" in [f["kind"] for f in cad["findings"]])
check("an ignored latency is a finding",
      "latency-ignored" in [f["kind"] for f in cad["findings"]])
check("blocking backpressure is a finding",
      "blocking-backpressure" in [f["kind"] for f in cad["findings"]])
check("an unauthenticated channel is a finding",
      "unauthenticated-channel" in [f["kind"] for f in cad["findings"]])
check("an empty profile raises seven checks", len(CP.advise({})["findings"]) == 7)
check("a complete profile raises none",
      CP.advise({k: True for k in (
          "observes_the_access_stream", "measures_arrival_latency",
          "uses_online_ordinal_ranks", "bounds_the_vocabulary",
          "drops_when_the_queue_is_full", "degrades_with_a_dead_collector",
          "splits_mechanism_from_policy")})["findings"] == [])

# ---- 4. the three modules are independent and pure ----------------------
check("the update gate names its format", UG.FORMAT == "longrun-harness-update-gate/1")
check("the ledger names its format", EL.FORMAT == "longrun-experiment-ledger/1")
check("the prefetcher names its format", CP.FORMAT == "longrun-context-prefetch/1")
check("the gate's categories match the paper's five", len(UG.CATEGORIES) == 5)
check("the ledger's desiderata match the paper's five", len(EL.DESIDERATA) == 5)
check("the ledger keeps failed and discarded apart",
      set(EL.TERMINAL) == {"kept", "discarded", "failed_invalid"})

passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
