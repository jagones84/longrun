#!/usr/bin/env python3
"""v1217 — skill control-flow integrity, memory co-management, sparse evaluation (round 148).

Sources:
  * arXiv:2611.24185 "SkillCFI" — the control skeleton, the three regimes and
    regime migration, the enforceability dispositions, the C/S/R/F admission
    checks, correlated results, the violation taxonomy, the refusal payload and
    the recovery comparison.
  * arXiv:2611.24165 "MemoSync" — scoped entries, approved-only writes,
    abstraction and localization across a boundary, the confirmed working
    memory, citations, item-level audit, alignment, the application gap and
    activity counts.
  * arXiv:2611.24159 "Fast Bayesian Methods" — the benchmark-balanced prior,
    the closed-form posterior, prior sensitivity, information value, Brier, the
    weighted ALC and calibration.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1217_skill_memory_sparse_eval.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1217-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import skill_cfi as SC        # noqa: E402
from longrun.harness import memory_commune as MC  # noqa: E402
from longrun.harness import sparse_eval as SE     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. skill control-flow integrity (SkillCFI) ------------------------
SKELETON = {
    "start": "start", "exits": ["success", "failure", "abort"],
    "steps": [{"name": n} for n in ("start", "edit", "validate", "ask",
                                   "overwrite", "save", "abort")],
    "edges": [
        {"from": "start", "to": "edit"},
        {"from": "edit", "to": "validate"},
        {"from": "validate", "to": "ask"},
        {"from": "validate", "to": "edit"},
        {"from": "ask", "to": "overwrite"},
        {"from": "ask", "to": "save"},
        {"from": "ask", "to": "abort"},
        {"from": "overwrite", "to": "success"},
        {"from": "save", "to": "success"},
        {"from": "abort", "to": "abort"},
    ],
}
sk = SC.skeleton(SKELETON)
check("a compiled skeleton is valid", sk["verdict"] == "skeleton-valid")
check("all steps are reachable", sk["unreachable"] == [])
check("a duplicate step is named",
      SC.skeleton(dict(SKELETON, steps=SKELETON["steps"] + [{"name": "edit"}]))
      ["duplicates"] == ["edit"])
check("a dangling edge is named",
      SC.skeleton(dict(SKELETON, edges=SKELETON["edges"]
                       + [{"from": "edit", "to": "ghost"}]))["dangling"] == ["ghost"])
check("an unreachable step is named",
      SC.skeleton({"start": "start", "exits": ["success"],
                   "steps": [{"name": "start"}, {"name": "island"}],
                   "edges": [{"from": "start", "to": "success"}]})
      ["unreachable"] == ["island"])
check("a missing exit is named",
      SC.skeleton({"start": "start", "exits": [], "steps": [{"name": "start"}],
                   "edges": []})["reasons"].count("no-exit") == 1)

check("an observable effect and evidence enforce",
      SC.enforceable({"effect_at_boundary": True, "evidence_at_boundary": True})
      ["disposition"] == "enforce")
check("a semantic norm without evidence is guidance",
      SC.enforceable({"effect_at_boundary": True, "evidence_at_boundary": False,
                      "mandatory": False})["disposition"] == "guidance")
check("a mandatory obligation without evidence is unsupported",
      SC.enforceable({"effect_at_boundary": True, "evidence_at_boundary": False,
                      "mandatory": True})["verdict"] == "unenforceable-missing-evidence")
check("an effect that never crosses the boundary is unsupported",
      SC.enforceable({"effect_at_boundary": False})["verdict"]
      == "unenforceable-regime-migration")
plan = SC.dispositions([
    {"id": "o1", "mandatory": True, "effect_at_boundary": True,
     "evidence_at_boundary": True},
    {"id": "o2", "mandatory": False, "effect_at_boundary": True,
     "evidence_at_boundary": False},
])
check("a plan counts each disposition", plan["enforced"] == 1 and plan["guidance"] == 1)
check("a supported plan compiles", plan["verdict"] == "compile-accepted")
rejected = SC.dispositions([{"id": "o3", "mandatory": True,
                             "effect_at_boundary": True,
                             "evidence_at_boundary": False}])
check("a mandatory gap rejects the skill", rejected["rejected"] == ["o3"])
check("the rejection is named", rejected["verdict"] == "compile-rejected")

CONTRACT = {
    "interfaces": {"edit": ["ok"], "validate": ["pass", "fail"],
                   "ask": ["copy", "replace", "cancel"],
                   "overwrite": ["ok"], "save": ["ok"]},
    "occurrences": [
        {"name": "edit", "interface": "edit"},
        {"name": "validate", "interface": "validate",
         "binds": {"pass": {"sha": "draft_sha"}},
         "invalidates": ["draft_sha"]},
        {"name": "ask", "interface": "ask"},
        {"name": "overwrite", "interface": "overwrite",
         "requires": ["draft_sha"], "args": {"sha": "draft_sha"}},
        {"name": "save", "interface": "save"},
    ],
    "edges": [
        {"from": "start", "to": "edit"},
        {"from": "res:edit", "to": "validate"},
        {"from": "res:validate", "to": "ask", "guard": {"fact": "pass"}},
        {"from": "res:validate", "to": "edit", "guard": {"fact": "fail"},
         "counter": {"name": "repairs"}},
        {"from": "res:ask", "to": "overwrite", "guard": {"fact": "replace"}},
        {"from": "res:ask", "to": "save", "guard": {"fact": "copy"}},
        {"from": "res:ask", "to": "abort", "guard": {"fact": "cancel"}},
    ],
    "exit_edges": [
        {"from": "res:overwrite", "to": "success"},
        {"from": "res:save", "to": "success"},
        {"from": "res:abort", "to": "abort"},
        {"from": "res:validate", "to": "failure",
         "guard": {"fact": "fail", "counter": {"name": "repairs", "at": 3}}},
    ],
}
S0 = {"node": "start", "fact": None, "counters": {}, "captures": {},
      "pending": None, "term": None}
first = SC.admit({"contract": CONTRACT, "state": S0,
                  "request": {"interface": "edit", "call_id": "c1", "args": {}}})
check("the first step is admitted", first["decision"] == "allow")
check("the state pins the in-flight call", first["state"]["pending"] == "c1")
blocked = SC.admit({"contract": CONTRACT, "state": first["state"],
                    "request": {"interface": "edit", "call_id": "c2", "args": {}}})
check("a second call while one is pending is refused at C",
      blocked["layer"] == "C" and blocked["reason"] == "in-flight-or-terminated")
check("an unknown interface is refused at S",
      SC.admit({"contract": CONTRACT, "state": S0,
                "request": {"interface": "rm", "call_id": "c1",
                            "args": {}}})["layer"] == "S")
check("a request with no enabled edge is refused at F",
      SC.admit({"contract": CONTRACT, "state": S0,
                "request": {"interface": "overwrite", "call_id": "c1",
                            "args": {"sha": "d"}}})["layer"] == "F")

after_edit = SC.result({"contract": CONTRACT, "state": first["state"],
                        "call_id": "c1", "outcome": "ok"})
check("a correlated result is accepted", after_edit["verdict"] == "accepted")
check("the result advances the node", after_edit["state"]["node"] == "res:edit")
check("a mismatched call id halts progression",
      SC.result({"contract": CONTRACT, "state": first["state"],
                 "call_id": "zz", "outcome": "ok"})["reason"] == "call-id-mismatch")
check("a decode failure halts progression",
      SC.result({"contract": CONTRACT, "state": first["state"],
                 "call_id": "c1", "outcome": "ok",
                 "decoder_ok": False})["reason"] == "decode-failed")
check("an unknown outcome halts progression",
      SC.result({"contract": CONTRACT, "state": first["state"],
                 "call_id": "c1", "outcome": "maybe"})["reason"] == "unknown-outcome")

validation = SC.admit({"contract": CONTRACT, "state": after_edit["state"],
                       "request": {"interface": "validate", "call_id": "c2",
                                   "args": {}}})
check("validation is admitted after the edit", validation["decision"] == "allow")
validated = SC.result({"contract": CONTRACT, "state": validation["state"],
                       "call_id": "c2", "outcome": "pass",
                       "captures": {"sha": "d1"}})
check("a pass binds the draft digest",
      validated["state"]["captures"].get("draft_sha") == "d1")
ask = SC.admit({"contract": CONTRACT, "state": validated["state"],
                "request": {"interface": "ask", "call_id": "c3", "args": {}}})
check("the branch to the user is admitted after a pass", ask["decision"] == "allow")
chosen = SC.result({"contract": CONTRACT, "state": ask["state"],
                   "call_id": "c3", "outcome": "replace"})
overwrite = SC.admit({"contract": CONTRACT, "state": chosen["state"],
                      "request": {"interface": "overwrite", "call_id": "c4",
                                  "args": {"sha": "d1"}}})
check("the approved draft can be written", overwrite["decision"] == "allow")
check("a different draft is refused",
      SC.admit({"contract": CONTRACT, "state": chosen["state"],
                "request": {"interface": "overwrite", "call_id": "c4",
                            "args": {"sha": "other"}}})["decision"] == "refuse")
delivered = SC.result({"contract": CONTRACT, "state": overwrite["state"],
                       "call_id": "c4", "outcome": "ok"})
check("delivery reaches the success exit", delivered["state"]["term"] == "success")
check("a request after the exit is refused at C",
      SC.admit({"contract": CONTRACT, "state": delivered["state"],
                "request": {"interface": "edit", "call_id": "c5",
                            "args": {}}})["layer"] == "C")
check("exhausted repairs end in failure",
      SC.result({"contract": CONTRACT,
                 "state": {"node": "req:validate", "fact": None,
                           "counters": {"repairs": 3}, "captures": {},
                           "pending": "c9", "term": None},
                 "call_id": "c9", "outcome": "fail"})["state"]["term"] == "failure")

check("an out-of-vocabulary tool is an unexpected action",
      SC.violation({"contract": CONTRACT, "state": S0,
                    "request": {"interface": "rm", "call_id": "c1",
                                "args": {}}})["kind"] == "unexpected-action")
check("a skipped prerequisite is an invalid transition",
      SC.violation({"contract": CONTRACT, "state": S0,
                    "request": {"interface": "overwrite", "call_id": "c1",
                                "args": {}}})["kind"] == "invalid-transition")
check("a completion after an exit is an invalid termination",
      SC.violation({"contract": CONTRACT, "state": delivered["state"],
                    "request": {"interface": "edit", "call_id": "c5",
                                "args": {}}})["kind"] == "invalid-termination")
check("a lawful request has no violation",
      SC.violation({"contract": CONTRACT, "state": S0,
                    "request": {"interface": "edit", "call_id": "c1",
                                "args": {}}})["kind"] == "none")

payload = SC.refusal({"contract": CONTRACT, "state": S0,
                      "request": {"interface": "overwrite", "call_id": "c1",
                                  "args": {}}})
check("a refusal names its layer", payload["layer"] == "F")
check("a refusal carries the next legal step", "edit" in payload["next"])
check("a refusal names the missing evidence", "draft_sha" in payload["missing"])

rec = SC.recovery([
    {"arm": "bare", "recovered": 17, "sessions": 80},
    {"arm": "basic", "recovered": 22, "sessions": 80},
    {"arm": "next-step", "recovered": 52, "sessions": 80},
])
check("bare recovery is 21%", close(rec["rates"]["bare"], 17 / 80))
check("next-step recovery is 65%", close(rec["rates"]["next-step"], 52 / 80))
check("next-step feedback helps", rec["verdict"] == "next-step-helps")
check("no sessions is not a recovery",
      SC.recovery([])["verdict"] == "no-sessions")

check("the audit names allowlist-as-cfi",
      "allowlist-is-not-cfi" in kinds(SC.audit({"allowlist_as_cfi": True})))
check("the audit names regime migration",
      "regime-migration" in kinds(SC.audit({"ignores_regime_migration": True})))
check("the audit names model claims as evidence",
      "evidence-from-model-claims" in kinds(SC.audit({"trusts_model_claims": True})))
check("the audit names a runtime model monitor",
      "runtime-model-monitor" in kinds(SC.audit({"runtime_model_monitor": True})))
check("an empty profile raises seven checks", len(SC.advise({})["findings"]) == 7)
check("a complete profile raises none",
      SC.advise({k: True for k in (
          "compiles_a_contract", "checks_before_dispatch",
          "requires_correlated_evidence", "mediates_every_effective_channel",
          "keeps_state_outside_the_model", "returns_the_next_legal_steps",
          "rejects_unsupported_mandatory_obligations")})["findings"] == [])

# ---- 2. memory co-management (MemoSync) --------------------------------
check("a scoped item is valid",
      MC.entry({"id": "M-07", "content": "prices in integer cents",
                "scope": "project"})["verdict"] == "entry-valid")
check("an unknown scope is named",
      MC.entry({"id": "M-01", "content": "x", "scope": "global"})
      ["reasons"] == ["unknown-scope"])
check("detail without a summary is named",
      MC.entry({"id": "M-01", "content": "x", "scope": "session",
                "detail": "long"})["reasons"] == ["detail-without-summary"])

check("a personal item applies in a session",
      MC.scope_ok({"item_scope": "personal", "context_scope": "session"})
      ["verdict"] == "applies")
check("a project item applies in the same project",
      MC.scope_ok({"item_scope": "project", "context_scope": "project",
                    "same_project": True})["applies"] is True)
check("a project item does not apply in another project",
      MC.scope_ok({"item_scope": "project", "context_scope": "project",
                    "same_project": False})["verdict"] == "outside-scope")
check("a session item does not leak into a project",
      MC.scope_ok({"item_scope": "session", "context_scope": "project"})
      ["verdict"] == "outside-scope")

prop = MC.proposals({"candidates": [{"id": "M-15"}, {"id": "M-05"}],
                      "approved": ["M-15"]})
check("only the approved candidate is written", prop["written"] == ["M-15"])
check("the unapproved candidate is pending", prop["pending"] == ["M-05"])
check("a write waits for confirmation", prop["verdict"] == "confirmation-required")

check("a full transfer is reviewable",
      MC.transfer({"source": "s", "abstract": "a", "localized": "l",
                   "destination_scope": "session"})["verdict"]
      == "transfer-reviewable")
check("a transfer without its abstract form is incomplete",
      MC.transfer({"source": "s", "localized": "l",
                   "destination_scope": "session"})["missing"] == ["abstract"])

sel = MC.selection({"proposed": [
    {"id": "M-16", "scope": "session", "expected_use": "recompute the total"},
    {"id": "M-07", "scope": "project", "expected_use": "integer cents"}],
    "confirmed": True})
check("a confirmed working memory is ready", sel["verdict"] == "working-memory-confirmed")
check("an unconfirmed selection is named",
      MC.selection({"proposed": [{"id": "M-07", "expected_use": "x"}],
                    "confirmed": False})["verdict"] == "unconfirmed")
check("an item without an expected use is named",
      MC.selection({"proposed": [{"id": "M-07"}], "confirmed": True})
      ["missing_use"] == ["M-07"])

cit = MC.citation({"text": "Use [M-07] and [M-13] here", "stored": ["M-07"]})
check("a stored citation resolves", cit["cited"] == ["M-07", "M-13"])
check("an unknown citation is named", cit["unknown"] == ["M-13"])

aud = MC.audit({"item": "M-07", "verdict": "violated", "source": "audit-found"})
check("an item audit records its verdict", aud["item_verdict"] == "violated")
check("an item audit records its source", aud["source"] == "audit-found")
check("an unknown audit verdict is refused",
      MC.audit({"verdict": "fine"})["verdict"] == "unknown-audit-verdict")

al = MC.alignment([
    {"desired_content": 1.0, "actual_content": 1.0, "scope_match": True},
    {"desired_content": 0.5, "actual_content": 0.5, "scope_match": False},
])
check("matching content scores 1", close(al["content"], 1.0))
check("scope agreement is binary", close(al["scope"], 0.5))
check("content times scope is the joint score", close(al["both"], 0.5))

gp = MC.gap([{"perceived": 4, "actual": 3}, {"perceived": 2, "actual": 4}])
check("the absolute gap is the mean difference", close(gp["absolute"], 1.5))
check("the signed gap keeps direction", close(gp["signed"], -0.5))

act = MC.activity([
    {"arm": "auto", "monitoring": 7.3, "control": 0.8},
    {"arm": "memosync", "monitoring": 70.3, "control": 25.3},
])
check("the monitoring ratio is 9.6", close(act["arms"]["memosync"]["monitoring_ratio"],
                                           70.3 / 7.3, 1e-9))
check("more actions are named", act["verdict"] == "more-actions")

check("the audit names visibility without selection",
      "visibility-without-selection" in kinds(MC.audit_record(
          {"visibility_without_selection": True})))
check("the audit names the static-file fallacy",
      "static-file-fallacy" in kinds(MC.audit_record({"static_file_fallacy": True})))
check("the audit names agent self-report",
      "agent-self-report" in kinds(MC.audit_record({"agent_self_report": True})))
check("the audit names an unscoped memory",
      "no-scope" in kinds(MC.audit_record({"no_scope": True})))
check("an empty profile raises seven checks", len(MC.advise({})["findings"]) == 7)
check("a complete profile raises none",
      MC.advise({k: True for k in (
          "represents_memory_as_scoped_items", "requires_confirmation_before_write",
          "surfaces_stale_and_conflicting_items", "makes_per_turn_selection_visible",
          "states_expected_use_per_item", "attributes_output_to_items",
          "separates_self_report_from_audit")})["findings"] == [])

# ---- 3. sparse evaluation (Bayesian) -----------------------------------
pr = SE.prior([
    {"benchmark": "b1", "family": "f1", "successes": 1, "failures": 1},
    {"benchmark": "b1", "family": "f1", "successes": 1, "failures": 1},
    {"benchmark": "b2", "family": "f2", "successes": 4, "failures": 1},
])
check("each benchmark contributes equally", close(pr["mean"], 0.625))
check("the benchmark count is reported", pr["benchmarks"] == 2)
check("a small record is excluded",
      SE.prior([{"benchmark": "b", "successes": 1, "failures": 1,
                 "distinct_items": 5}])["verdict"] == "no-eligible-records")

post = SE.posterior({"mean": 0.6, "successes": 22, "labels": 31})
check("the predictive mean is (2m+s)/(2+n)", close(post["prediction"], 23.2 / 33))
check("the prior weight is 2/33", close(post["prior_weight"], 2 / 33))
check("the posterior variance is p(1-p)/(n+3)",
      close(post["variance"], post["prediction"] * (1 - post["prediction"]) / 34))
check("the predictive variance is p(1-p)",
      close(post["predictive_variance"],
            post["prediction"] * (1 - post["prediction"])))

sens = SE.sensitivity({"mean": 0.1, "mean_alt": 0.9, "labels": 31})
check("the prior difference shrinks by 2/33",
      close(sens["difference"], (2 / 33) * 0.8))
check("the prior is washed out at 31 labels",
      sens["verdict"] == "prior-washed-out")
check("at zero labels the prior persists",
      SE.sensitivity({"mean": 0.1, "mean_alt": 0.2, "labels": 0})["verdict"]
      == "prior-persists")

val = SE.value({"mean": 0.7, "labels": 31})
check("the expected Brier reduction is mu(1-mu)/(n+3)^2",
      close(val["brier_reduction"], 0.7 * 0.3 / (34 ** 2)))
check("the expected contraction is (n+2)/(n+3)",
      close(val["contraction"], 33 / 34))

check("Brier is mean squared error",
      close(SE.brier([{"prediction": 0.5, "label": 1},
                      {"prediction": 0.7, "label": 0}])["brier"], 0.37))
curve = [{"budget": 0, "brier": 0.253063}, {"budget": 1, "brier": 0.223037},
         {"budget": 3, "brier": 0.199509}, {"budget": 7, "brier": 0.186894},
         {"budget": 15, "brier": 0.178202}, {"budget": 31, "brier": 0.174150}]
alc = SE.alc(curve)
check("the weighted ALC is 0.20025", close(alc["alc"], 0.20025, 1e-5))
check("the ALC beats the constant reference", alc["verdict"] == "beats-constant")
check("the constant 0.5 curve is exactly 0.25",
      close(SE.alc([{"budget": b, "brier": 0.25} for b in SE.BUDGETS])["alc"], 0.25))
check("a missing budget is named",
      SE.alc(curve[:3])["missing"] == [7, 15, 31])

cal = SE.calibration([{"predicted": 0.9, "observed": 0.8, "count": 10},
                      {"predicted": 0.2, "observed": 0.3, "count": 30}])
check("the ECE is the count-weighted gap", close(cal["ece"], 0.1))
check("a 10% ECE is calibrated", cal["verdict"] == "calibrated")
check("a 20% ECE is miscalibrated",
      SE.calibration([{"predicted": 0.9, "observed": 0.7, "count": 10}])
      ["verdict"] == "miscalibrated")

check("the audit names pair-level-only",
      "pair-level-only" in kinds(SE.audit_record({"pair_level_only": True})))
check("the audit names a reused panel",
      "panel-reused" in kinds(SE.audit_record({"panel_reused": True})))
check("the audit names missing interval coverage",
      "no-interval-coverage" in kinds(SE.audit_record({"no_interval_coverage": True})))
check("the audit names a single online run",
      "single-online-run" in kinds(SE.audit_record({"single_online_run": True})))
check("an empty profile raises seven checks", len(SE.advise({})["findings"]) == 7)
check("a complete profile raises none",
      SE.advise({k: True for k in (
          "derives_a_prior_from_public_counts", "balances_benchmarks_equally",
          "keeps_the_prior_weak", "reports_prior_weight",
          "reports_prior_sensitivity", "reports_calibration_beside_brier",
          "states_the_model_limits")})["findings"] == [])

# ---- 4. the three modules are independent and pure ---------------------
check("skill CFI names its format", SC.FORMAT == "longrun-skill-cfi/1")
check("memory commune names its format", MC.FORMAT == "longrun-memory-commune/1")
check("sparse evaluation names its format", SE.FORMAT == "longrun-sparse-eval/1")
check("the layers are C/S/R/F", SC.LAYERS == ("C", "S", "R", "F"))
check("the scopes are personal/project/session",
      MC.SCOPES == ("personal", "project", "session"))
check("the budgets are the paper's six", SE.BUDGETS == (0, 1, 3, 7, 15, 31))

passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
