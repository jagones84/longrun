#!/usr/bin/env python3
"""v1208 — context folding, invocation reliability, evolution capabilities (round 139).

Sources:
  * arXiv:2611.16627 "Folio" — three linked history levels, monotone folding,
    shared handles, and a landing-priced trigger.
  * arXiv:2608.26189 "Invocation-Level Reliability" — local vs global rates,
    L1 = 0, severity pinned by gold scoring, conditional scoring, discrimination.
  * arXiv:2605.30621 "Harness Updating Is Not Harness Benefit" — updating is
    flat, benefit is non-monotonic, activation and adherence failures.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1208_folding_invocation_evolution.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1208-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import context_folding as CF  # noqa: E402
from longrun.harness.checks import invocation_reliability as IR  # noqa: E402
from longrun.harness.checks import evolution_capabilities as EC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. context folding -------------------------------------------------
lv = CF.levels({"l1": "note", "l2": "row", "l3": "source", "handle": "t3.12"})
check("three levels under one call handle are linked", kinds(lv) == ["levels-linked"], lv)
check("a missing level is named", "missing-level" in kinds(CF.levels({"l1": "n", "l3": "s"})))
check("a missing handle is named", "no-handle" in kinds(CF.levels({"l1": "n", "l2": "r", "l3": "s"})))
check("a handle that is not a call coordinate is named",
      "handle-not-call-coordinate" in kinds(CF.levels(
          {"l1": "n", "l2": "r", "l3": "s", "handle": "abc"})))
check("an unstable handle is named",
      "handle-unstable" in kinds(CF.levels(
          {"l1": "n", "l2": "r", "l3": "s", "handle": "t1.1", "handle_stable": False})))

check("a fold that retains, resolves and reads exactly satisfies the contract",
      kinds(CF.contract({})) == ["contract-holds"])
check("a deleted source is named", "source-deleted" in kinds(CF.contract({"source_retained": False})))
check("a handle that resolves elsewhere is named",
      "handle-resolves-elsewhere" in kinds(CF.contract({"resolves_after_folds": False})))
check("a cut copy is reported when no exact read exists",
      "read-returns-cut-copy" in kinds(CF.contract({"exact_read": False,
                                                    "cut_copy_available": True})))
check("a missing exact read with no copy is named",
      "exact-read-unavailable" in kinds(CF.contract({"exact_read": False})))

turns = [{"turn": i, "closed": True, "size": 10} for i in (1, 2, 3, 4, 5)]
turns.append({"turn": 6, "closed": False, "size": 10})
fd = CF.fold(turns)
check("the newest closed turn is shown at l2",
      [t for t in fd["turns"] if t["turn"] == 5][0]["level"] == "l2", fd)
check("the two turns before it are shown at l1_full",
      [t for t in fd["turns"] if t["turn"] == 4][0]["level"] == "l1_full", fd)
check("an older turn is shown at l1_brief",
      [t for t in fd["turns"] if t["turn"] == 1][0]["level"] == "l1_brief", fd)
check("a small fold is rendered without demotion", "fold-rendered" in kinds(fd), fd)
fd2 = CF.fold(turns, budget=10)
check("a tight budget demotes turns", "demoted" in kinds(fd2), fd2)
check("a tight budget reports the exceeded size",
      "budget-exceeded" in kinds(fd2) or "demoted" in kinds(fd2), fd2)
check("a turn that was sent brief is never redrawn richer",
      "demotion-not-monotone" in kinds(CF.fold(
          [{"turn": 1, "closed": True, "size": 1, "previous_level": "l1_brief"},
           {"turn": 2, "closed": True, "size": 1}, {"turn": 3, "closed": True, "size": 1}])))
check("no turns is named", "no-turns" in kinds(CF.fold([])))

tr = CF.trigger([{"cached": 100.0}] * 10, stable_prefix=10, layout_budget=10,
                dossier=0, rewrite_ratio=30)
check("carried excess above the price triggers a fold",
      tr["fold"] is True and tr["excess"] > tr["price"], tr)
tr2 = CF.trigger([{"cached": 15.0}] * 10, stable_prefix=10, layout_budget=10,
                 dossier=0, rewrite_ratio=30)
check("cached input below the landing point keeps the context",
      tr2["fold"] is False, tr2)
check("a zero retained budget cannot be priced",
      "landing-not-priced" in kinds(CF.trigger([{"cached": 100.0}], rewrite_ratio=30)))
check("no requests is named", "no-requests" in kinds(CF.trigger([])))
check("the normalized cost weights uncached and output tokens",
      CF.cost({"cached": 100, "uncached": 10, "output": 1})["normalized"] == 490.0)

rc = CF.recover([{"folded": True, "recovered_by": "scan", "bounded": True},
                 {"folded": True, "recovered_by": "ctx", "computed_over_full_text": True}])
check("folded content reached through handles is clean",
      "recovery-clean" in kinds(rc) or "dossier-carried" in kinds(rc), rc)
check("a fold with no recovery is named",
      "no-recovery-after-fold" in kinds(CF.recover([{"folded": True}])))
check("an unbounded read is named",
      "unbounded-read" in kinds(CF.recover([{"folded": True, "recovered_by": "scan",
                                             "bounded": False}])))
check("a ctx call that did not read the full text is named",
      "ctx-not-over-full-text" in kinds(CF.recover(
          [{"folded": True, "recovered_by": "ctx", "computed_over_full_text": False}])))
check("advise names every missing practice", len(CF.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", CF.advise(
    {k: True for k in ("records_levels", "keeps_handles", "demotes_monotonically",
                       "offers_recovery", "keeps_a_dossier", "prices_the_landing",
                       "contracts_recoverability", "measures_fold_cost")})["findings"] == [])

# ---- 2. invocation reliability -----------------------------------------
steps = ([{"depth": 6, "local": "ok", "global": "ok"}] * 35
         + [{"depth": 6, "local": "ok", "global": "bad"}] * 15
         + [{"depth": 6, "local": "bad", "global": "bad"}] * 20)
rt = IR.rates(steps, 6)
check("local and global rates give a propagation loss",
      abs(rt["p"] - 50 / 70.0) < 1e-4 and abs(rt["g"] - 0.5) < 1e-9, rt)
check("a large loss is named", "propagation" in kinds(rt), rt)
check("a zero loss is named no propagation",
      "no-propagation" in kinds(IR.rates([{"local": "ok", "global": "ok"}] * 5)))
check("no steps is named", "no-steps" in kinds(IR.rates([])))
check("depth one must show zero loss",
      kinds(IR.wiring([{"depth": 1, "local": "ok", "global": "ok"}] * 5)) == ["wiring-ok"])
check("a non-zero depth-one loss breaks the wiring",
      "wiring-broken" in kinds(IR.wiring(
          [{"depth": 1, "local": "ok", "global": "ok"}] * 3
          + [{"depth": 1, "local": "ok", "global": "bad"}])))
check("no depth-one rows is named", "no-depth-one" in kinds(IR.wiring([])))

sv = IR.severity([{"poisoned": False, "outcome": "ok"}] * 20
                 + [{"poisoned": True, "outcome": "bad"}] * 30)
check("no poisoned success forces severity to one",
      sv["pi"] == 1.0 and "severity-pinned" in kinds(sv), sv)
check("a small poisoned sample is uninformative",
      "severity-uninformative" in kinds(IR.severity(
          [{"poisoned": False, "outcome": "ok"}] * 20
          + [{"poisoned": True, "outcome": "ok"}] * 2
          + [{"poisoned": True, "outcome": "bad"}] * 3)))
check("a large mixed sample gives an interior severity",
      "severity-interior" in kinds(IR.severity(
          [{"poisoned": False, "outcome": "ok"}] * 40
          + [{"poisoned": True, "outcome": "ok"}] * 10
          + [{"poisoned": True, "outcome": "bad"}] * 30)))
check("unmeasured severity is named",
      "severity-unmeasured" in kinds(IR.severity([{"poisoned": True, "outcome": "bad"}])))

rv = IR.recovery([{"poisoned": True, "next_outcome": "bad"}] * 30)
check("zero returns with no derivable gold makes recovery unobservable",
      "recovery-unobservable" in kinds(rv), rv)
check("an observed return is reported",
      "recovery-observed" in kinds(IR.recovery(
          [{"poisoned": True, "next_outcome": "ok"}] * 2
          + [{"poisoned": True, "next_outcome": "bad"}] * 8)))
check("unmeasured recovery is named",
      "recovery-unmeasured" in kinds(IR.recovery([])))

sc = IR.scoring([{"gold_ok": False, "conditional_ok": True}] * 20
                + [{"gold_ok": False, "conditional_ok": False}] * 80)
check("gold scoring pins severity where conditional scoring does not",
      "gold-pins-severity" in kinds(sc), sc)
check("conditional credit above gold is named",
      "conditional-credit" in kinds(IR.scoring(
          [{"gold_ok": False, "conditional_ok": True}] * 2
          + [{"gold_ok": True, "conditional_ok": True}] * 8)))
check("no scored steps is named", "no-scored-steps" in kinds(IR.scoring([])))

tm = IR.terminal([{"depth": 4, "step": 0, "outcome": "bad"},
                  {"depth": 4, "step": 3, "outcome": "bad"},
                  {"depth": 4, "step": 3, "outcome": "bad"}])
check("a terminal share above a third is named",
      "terminal-share-high" in kinds(tm) and abs(tm["share"] - 2 / 3.0) < 1e-3, tm)
check("no errors is named", "no-errors" in kinds(IR.terminal([])))

ds = IR.discrimination([{"parity": "even", "first": True}] * 20
                       + [{"parity": "odd", "first": False}] * 20)
check("perfect rule application is named",
      ds["stat"] == 1.0 and "rule-derived" in kinds(ds), ds)
check("an anti-correlated model is named",
      "rule-anticorrelated" in kinds(IR.discrimination(
          [{"parity": "even", "first": False}] * 20
          + [{"parity": "odd", "first": True}] * 20)))
check("a model that ignores the rule is named",
      "rule-ignored" in kinds(IR.discrimination(
          [{"parity": "even", "first": True}] * 10
          + [{"parity": "even", "first": False}] * 10
          + [{"parity": "odd", "first": True}] * 10
          + [{"parity": "odd", "first": False}] * 10)))
check("no parity split is named", "no-parity-split" in kinds(IR.discrimination([])))
check("advise names every missing practice", len(IR.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", IR.advise(
    {k: True for k in ("scores_invocations", "measures_both_arms", "checks_depth_one",
                       "scores_conditionally", "reports_terminal_share",
                       "tests_rule_following", "reports_error_position",
                       "freezes_the_suite")})["findings"] == [])

# ---- 3. evolution capabilities -----------------------------------------
up = EC.updating([{"evolver": "opus", "gain": 2.0, "benchmark": "swe"},
                  {"evolver": "qwen9b", "gain": 3.5, "benchmark": "sb"},
                  {"evolver": "sonnet", "gain": 2.6, "benchmark": "mcp"}])
check("a narrow evolver spread is flat", "updating-flat" in kinds(up), up)
check("no evolver dominates when the best wins one benchmark",
      "no-evolver-dominates" in kinds(up), up)
check("a wide spread is separable",
      "updating-separable" in kinds(EC.updating(
          [{"evolver": "a", "gain": 1.0, "benchmark": "x"},
           {"evolver": "b", "gain": 9.0, "benchmark": "x"}])))
check("no update rows is named", "no-update-rows" in kinds(EC.updating([])))

be = EC.benefit([{"base": 4, "gain": 5.0}, {"base": 25, "gain": 19.0},
                 {"base": 74, "gain": 2.6}])
check("a mid-tier peak is non-monotonic",
      "benefit-non-monotonic" in kinds(be), be)
check("a falling gain at the high base is a ceiling",
      "ceiling-effect" in kinds(be), be)
check("a weak tier far below the peak is named",
      "weak-tier-left-behind" in kinds(be), be)
check("two agents are not enough", "not-enough-agents" in kinds(
    EC.benefit([{"base": 1, "gain": 1}, {"base": 2, "gain": 2}])))

check("a low load rate is an activation failure",
      "activation-failure" in kinds(EC.activation([{"model": "weak", "load_rate": 0.25}])))
check("a high load rate passes", kinds(EC.activation([{"model": "strong", "load_rate": 0.96}]))
      == ["activation-ok"])
check("a low follow rate is an adherence failure",
      "adherence-failure" in kinds(EC.adherence([{"model": "weak", "follow_rate": 0.14}])))
check("a large phase drift is named",
      "adherence-drift" in kinds(EC.adherence(
          [{"model": "weak", "follow_rate": 0.8, "phase_scores": [0.52, 0.22, 0.13]}])))
check("a stable strong model is not drifting",
      "adherence-drift" not in kinds(EC.adherence(
          [{"model": "strong", "follow_rate": 0.8, "phase_scores": [0.89, 0.79, 0.80]}])))

bd = EC.budget([{"agent": "opus", "score": 74}, {"agent": "opus", "score": 76},
                {"agent": "qwen", "score": 10}, {"agent": "qwen", "score": 12}])
check("a between-agent gap above twice the within spread puts budget on the agent",
      "budget-to-agent" in kinds(bd), bd)
check("no pairing rows is named", "no-pairing-rows" in kinds(EC.budget([])))
check("an extreme pairing that still favours the strong agent is named",
      "agent-dominates" in kinds(EC.pairing({"strong_agent_worst_evolver": 60,
                                             "weak_agent_best_evolver": 25})))
check("a reversed pairing is named",
      "evolver-reverses-order" in kinds(EC.pairing({"strong_agent_worst_evolver": 20,
                                                    "weak_agent_best_evolver": 25})))
check("a score locked before its own update is in situ",
      kinds(EC.insitu({"scored_before_update": True})) == ["insitu-ok"])
check("a task scoring itself through its own update is named",
      "task-sees-own-update" in kinds(EC.insitu({})))
check("advise names every missing practice", len(EC.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", EC.advise(
    {k: True for k in ("separates_updating_and_benefit", "pairs_agents_with_evolvers",
                       "measures_activation", "measures_adherence",
                       "reports_phase_drift", "uses_in_situ_scoring",
                       "compares_within_and_between",
                       "tests_extreme_pairing")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
