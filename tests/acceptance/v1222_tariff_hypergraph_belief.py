#!/usr/bin/env python3
"""v1222 — retained-context tariff, hypergraph knowledge engineering, belief probes (round 153).

Sources:
  * arXiv:2611.24071 — the weighted charge, the token/request/session bounds, the
    coverage condition, the decay-family comparison and the tail-for-median result.
  * arXiv:2611.24294 — native ingest, entity identity and alias classes, the
    two-hop join, the lifecycle invariant, intent routing, the named-file
    guarantee and the equal-persona OKE.
  * arXiv:2611.23938 — the belief rate, per-category behaviour, the log-linear
    scaling, the three depth axes, the three-way judge, metric independence and
    reality separation.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1222_tariff_hypergraph_belief.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1222-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import context_tariff as CT     # noqa: E402
from longrun.harness import hypergraph_ke as HK      # noqa: E402
from longrun.harness import belief_probe as BP       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. retained-context tariff (arXiv:2611.24071) --------------------
C = CT.charge({"pin": 2.0, "ph": 1.0, "pout": 4.0, "r": 0.5,
               "new_input": 100, "output": 50,
               "blocks": [{"tokens": 100, "age": 0}, {"tokens": 100, "age": 1}]})
check("the historical charge discounts by age",
      close(C["historical_tokens"], 150.0))
check("the total includes every category", close(C["total"], 200 + 150 + 200))
check("the historical share is reported", close(C["historical_share"], 150 / 550))
check("reasoning is charged in the current round",
      close(CT.charge({"pin": 1, "ph": 1, "pout": 1, "r": 0.5, "preason": 2,
                       "reasoning": 10})["total"], 20.0))
check("an out-of-range r is refused",
      CT.charge({"pin": 1, "ph": 1, "pout": 1, "r": 2})["verdict"]
      == "r-out-of-range")
check("a missing rate is refused", CT.charge({})["verdict"] == "insufficient-input")
L = CT.lifetime({"r": 0.5, "ph": 1.0, "rounds": 3, "delta": 100})
check("the token charge is a finite sum", close(L["token_charge"], 1.875))
check("the token limit is one over one minus r", close(L["token_limit"], 2.0))
check("the request charge accumulates", close(L["request_charge"], 150.0))
check("the request limit is the same form", close(L["request_limit"], 200.0))
check("the session total grows linearly",
      close(L["session_total"], 200 * (3 - 1.75)))
check("the session is unbounded", L["session_growth"] == "linear")
check("the three distinctions are named",
      CT.bounds({"r": 0.9})["verdict"] == "three-distinctions")
check("the session bound is empty", CT.bounds({"r": 0.9})["session"]["bound"] is None)
COV = CT.coverage({"r": 0.9, "ph": 5e-8, "delta": 1000, "cold_slope": 1.35e-8,
                   "window": 65536, "hit": 0.0})
check("the historical charge is the accumulation", close(COV["historical"], 0.0005))
check("a cold re-send is priced by the window", close(COV["resend"], 1.35e-8 * 65536))
check("a cold re-send breaches coverage", COV["verdict"] == "coverage-breach")
check("the break-even hit rate is reported", COV["break_even_hit"] > 0)
COV2 = CT.coverage({"r": 0.9, "ph": 1e-6, "delta": 1000, "cold_slope": 1.35e-8,
                    "window": 4096, "hit": 0.5})
check("a warm short window is covered", COV2["verdict"] == "covered")
Q = CT.quality([{"family": "relevance", "rmse": 0.303},
                {"family": "piecewise", "rmse": 0.311},
                {"family": "power", "rmse": 0.391},
                {"family": "hyperbolic", "rmse": 0.415},
                {"family": "geometric", "rmse": 0.431}])
check("the relevance baseline is reported", close(Q["baseline"], 0.303))
check("every monotone family is worse", len(Q["worse_than_relevance"]) == 3)
check("relevance dominates", Q["verdict"] == "relevance-dominates")
check("a family that beats relevance is named",
      CT.quality([{"family": "relevance", "rmse": 0.4},
                  {"family": "power", "rmse": 0.3},
                  {"family": "hyperbolic", "rmse": 0.5},
                  {"family": "geometric", "rmse": 0.6}])["verdict"]
      == "distance-adds-signal")
F = CT.fairness({"p99": -42.0, "cv": -40.5, "median": 58.9, "mean": -11.4})
check("the tail shrinks", F["tail_shrinks"] is True)
check("the median rises", F["median_rises"] is True)
check("the result is a tail for a median", F["verdict"] == "tail-for-median")
check("a rising P99 is refused as unexpected",
      CT.fairness({"p99": 5, "cv": -1, "median": 1})["verdict"] == "unexpected-sign")
check("the audit names six misreadings",
      len(CT.audit({"distance_is_value": True, "session_total_bounded": True,
                    "warm_cost_scales": True, "hit_rate_is_measured": True,
                    "mean_falls_under_every_schedule": True,
                    "agent_workload_benefits": True})["findings"]) == 6)
check("an empty record passes the tariff audit",
      kinds(CT.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all six habits",
      len(CT.advise({})["findings"]) == 6)
check("a complete harness profile is clean",
      CT.advise({k: True for k in ("separates_persistent_from_ephemeral",
                                   "measures_the_hit_rate",
                                   "prices_per_round_not_per_token",
                                   "reports_the_tail_beside_the_mean",
                                   "checks_the_quality_side",
                                   "keeps_tool_state_undiscounted")})["findings"] == [])

# ---- 2. hypergraph knowledge engineering (arXiv:2611.24294) -----------
ING = HK.ingest([
    {"file": "a.pdf", "modality": "pdf", "surface": "text", "fields": ["title", "author"]},
    {"file": "b.mp4", "modality": "video", "surface": "native", "fields": ["title"]},
])
check("files are counted", ING["files"] == 2)
check("media files are counted", ING["media"] == 1)
check("record fields are collected", ING["fields"] == ["author", "title"])
check("a clean ingest passes", ING["verdict"] == "ingested")
check("a model-made gold is refused",
      HK.ingest([{"file": "a.pdf", "modality": "pdf", "surface": "text",
                  "gold_from_model": True}])["verdict"] == "ingest-rejected")
check("a text file without a surface is refused",
      HK.ingest([{"file": "a.txt", "modality": "text"}])["violations"][0]
      ["reason"] == "no-surface")
J = HK.join([
    {"file": "a.pdf", "modality": "pdf", "values": ["Max Langtry", "Widget"]},
    {"file": "b.mp4", "modality": "video", "values": ["Widget"]},
    {"file": "c.pdf", "modality": "pdf", "values": ["Unrelated"]},
])
check("entities are counted", J["entities"] == 3)
check("two files join on a shared entity", J["joined"] == 2)
check("the join share is reported", close(J["join_share"], 2 / 3))
check("a shared entity across modalities is cross-modal",
      J["cross_modal_entities"] == 1)
check("a partial join is a gap", J["verdict"] == "join-gap")
ALIAS = HK.join([{"file": "a.pdf", "person": "M. Langtry"},
                 {"file": "b.pdf", "person": "Max Langtry"}])
check("an alias class joins two spellings", ALIAS["joined"] == 2)
E1 = HK.edit({"op": "DEL", "handle": "h1", "handle_files": ["old"],
              "present": ["old", "keep"],
              "provenance": {"v1": ["old"], "v2": ["old", "keep"]}})
check("a delete prunes provenance", E1["nodes"] == 1)
check("only what the file alone supported is dropped", E1["present"] == 1)
check("the store stays sound", E1["verdict"] == "sound")
E2 = HK.edit({"op": "REFRESH", "handle": "h1", "handle_files": ["new"],
              "files": ["newer"], "present": ["new", "keep"],
              "new_entities": ["Fresh"], "provenance": {"v": ["new"]},
              "gone": ["new"]})
check("a refresh is an add after a delete", E2["op"] == "REFRESH")
check("a pruning refresh stays sound", E2["verdict"] == "sound")
check("an append-only store leaves a stale node",
      HK.edit({"op": "ADD", "append_only": True, "present": ["keep"],
               "provenance": {"v": ["old"]}, "gone": ["old"]})["verdict"]
      == "stale-or-unsound")
check("an unknown edit is refused", HK.edit({"op": "PATCH"})["verdict"] == "unknown-op")
check("a handle alone routes to the file tier",
      HK.route({"handles": ["h1"]})["tier"] == "file")
check("a handle with a relational cue routes to the subgraph",
      HK.route({"handles": ["h1"], "relational": True})["tier"] == "subgraph")
check("a synthesis with no anchor routes to the community",
      HK.route({"synthesis": True})["tier"] == "community")
check("an unclassifiable query falls back",
      HK.route({})["tier"] == "fallback")
check("the router reports its anchors",
      HK.route({"handles": ["h"], "spans": ["s"]})["anchors"] == 2)
EV = HK.evidence({"named_files": ["f1"], "k": 2, "lookalikes": 5})
check("named cards are always included", EV["cards_always_included"] is True)
check("top-k can miss a named file", EV["topk_miss"] > 0)
check("a guarantee is named", EV["verdict"] == "named-file-guaranteed")
check("more look-alikes than k means a certain miss",
      close(HK.evidence({"named_files": ["f"], "k": 2, "lookalikes": 9})
            ["topk_miss"], 0.8))
check("no named file is its own verdict",
      HK.evidence({})["verdict"] == "no-named-files")
OKE = HK.oke([{"persona": "a", "task": "T1", "score": 50},
              {"persona": "a", "task": "T2", "score": 100},
              {"persona": "b", "task": "T1", "score": 10}])
check("persona means average their tasks", close(OKE["persona_scores"]["a"], 75.0))
check("the overall is the mean of persona means", close(OKE["oke"], 42.5))
check("no scores is its own verdict", HK.oke([])["verdict"] == "no-scores")
check("the audit names six misreadings",
      len(HK.audit({"stores_segments_only": True, "appends_new_versions": True,
                    "flat_topk_is_enough": True, "one_tier_for_every_query": True,
                    "model_made_gold": True, "rebuild_per_edit": True})["findings"]) == 6)
check("an empty record passes the hypergraph audit",
      kinds(HK.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all six habits",
      len(HK.advise({})["findings"]) == 6)
check("a complete harness profile is clean",
      HK.advise({k: True for k in ("reads_every_modality_natively",
                                   "keys_entities_deterministically",
                                   "commits_edits_along_provenance",
                                   "anchors_named_files_before_ranking",
                                   "routes_the_query_to_a_tier",
                                   "keeps_gold_out_of_model_output")})["findings"] == [])

# ---- 3. belief probes (arXiv:2611.23938) ------------------------------
BR = BP.belief_rate([{"held_out": True, "acts": True},
                     {"held_out": True, "acts": True, "cites_prompt": True},
                     {"held_out": True, "acts": False},
                     {"held_out": False, "acts": True}])
check("only held-out items count", BR["items"] == 3)
check("citing spoils the belief count", close(BR["belief"], 1 / 3))
check("the act rate ignores citing", close(BR["act_rate"], 2 / 3))
check("no items is its own verdict", BP.belief_rate([])["verdict"] == "no-items")
CAT = BP.categories([{"category": "egregious", "acts": False},
                     {"category": "subtle", "acts": True},
                     {"category": "before_cutoff", "acts": True},
                     {"category": "after_cutoff", "acts": True}])
check("every category is reported", set(CAT["rates"]) == set(BP.CATEGORIES))
check("a category spread is named", CAT["verdict"] == "category-spread")
check("egregious facts resist", close(CAT["rates"]["egregious"], 0.0))
SC = BP.scaling([{"facts": 10, "belief": 0.09}, {"facts": 100, "belief": 0.65},
                 {"facts": 10000, "belief": 0.86}])
check("scaling is fitted in log10", SC["slope"] > 0.15)
check("log-linear growth is named", SC["verdict"] == "log-linear")
check("one point is not a curve",
      BP.scaling([{"facts": 10, "belief": 0.5}])["verdict"] == "too-few-points")
D = BP.depth([{"axis": "generalisation", "score": 0.7},
              {"axis": "robustness", "score": 0.5},
              {"axis": "representation", "score": 0.9}])
check("three axes are collected", len(D["scores"]) == 3)
check("a full triad is deep belief", D["verdict"] == "deep-belief")
SHALLOW = BP.depth([{"axis": "generalisation", "score": 0.7},
                    {"axis": "robustness", "score": 0.05},
                    {"axis": "representation", "score": 0.9}])
check("a weak axis is named", SHALLOW["shallow"] == ["robustness"])
check("a weak axis makes it shallow", SHALLOW["verdict"] == "shallow-belief")
J1 = BP.judge({"label": "false"})
check("a false-world answer earns false credit", close(J1["credit_false_world"], 1.0))
check("an ambiguous answer earns nothing",
      close(BP.judge({"label": "ambiguous"})["credit_true_world"], 0.0))
check("an unknown label is refused", BP.judge({"label": "maybe"})["verdict"]
      == "unknown-label")
check("a metric trained as a reward is contaminated",
      BP.independence({"metric": "belief", "reward": "belief",
                       "held_out_distribution": True})["verdict"]
      == "metric-contaminated")
check("a held-out independent metric is clean",
      BP.independence({"metric": "push-back", "reward": "non-citing",
                       "held_out_distribution": True})["verdict"]
      == "metric-independent")
check("reality separation is a difference",
      close(BP.reality({"before": 0.938, "after": 0.620})["delta"], -0.318))
check("a large loss damages reality",
      BP.reality({"before": 0.938, "after": 0.620})["verdict"] == "reality-damaged")
check("a small loss leaves it intact",
      BP.reality({"before": 0.94, "after": 0.90})["verdict"] == "reality-intact")
check("the audit names six misreadings",
      len(BP.audit({"behaviour_is_belief": True, "citing_counts_as_belief": True,
                    "trained_metric_is_evaluation": True,
                    "one_category_is_enough": True,
                    "in_distribution_facts": True,
                    "no_side_effect_check": True})["findings"]) == 6)
check("an empty record passes the belief audit",
      kinds(BP.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all six habits",
      len(BP.advise({})["findings"]) == 6)
check("a complete harness profile is clean",
      BP.advise({k: True for k in ("holds_facts_out_of_training",
                                   "separates_acting_from_citing",
                                   "checks_the_representation",
                                   "keeps_the_metric_out_of_the_reward",
                                   "reports_by_fact_category",
                                   "measures_side_effects")})["findings"] == [])

# ---- summary ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
