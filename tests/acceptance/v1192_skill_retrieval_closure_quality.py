#!/usr/bin/env python3
"""v1192 — experience-grounded skill retrieval, rule closure, skill quality (round 123).

Sources:
  * arXiv:2611.01115 "CompSkill" — matched same-task comparisons, only discordant
    pairs carry information, capped corrections cited to their events.
  * arXiv:2611.01042 "SkillCDG" — closure-based rule selection over a `require`
    graph, conditionally complete under a context budget.
  * arXiv:2610.38147 "SkillCT" — nine quality dimensions and an execution-free
    estimate from similar reference skills.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1192_skill_retrieval_closure_quality.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1192-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import skill_retrieval as SR     # noqa: E402
from longrun.harness import rule_retrieval as RR      # noqa: E402
from longrun.harness import skill_quality as SQ       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. experience-grounded skill retrieval ---------------------------------
PAIRS = [
    {"task": "t1", "executor": "e1", "winner": "A", "loser": "B"},
    {"task": "t2", "executor": "e1", "winner": "A", "loser": "B"},
    {"task": "t3", "executor": "e1", "winner": "B", "loser": "C", "tie": True},
    {"task": "t4", "winner": "A", "loser": "D"},
]
cal = SR.calibrate(PAIRS)
check("a matched discordant pair separates two skills",
      cal["offsets"]["A"]["discordant"] == 2
      and cal["offsets"]["A"]["offset"] == 0.35, cal["offsets"].get("A"))
check("the losing skill gets the opposite correction",
      cal["offsets"]["B"]["offset"] == -0.35, cal["offsets"].get("B"))
check("a tie carries no information and is skipped",
      "C" not in cal["offsets"] and cal["skipped"] >= 1, cal)
check("a comparison with no executor is skipped, not counted",
      "D" not in cal["offsets"], cal["offsets"])
check("every correction cites the events that produced it",
      cal["offsets"]["A"]["cited"][0]["task"] == "t1"
      and cal["offsets"]["A"]["cited"][0]["executor"] == "e1"
      and cal["offsets"]["A"]["cited"][0]["role"] == "winner",
      cal["offsets"]["A"]["cited"][0])
check("the correction is capped and says so",
      cal["offsets"]["A"]["clipped"] is True and abs(cal["offsets"]["A"]["raw"]) > SR.CAP,
      cal["offsets"]["A"])

ranked = SR.rank([{"skill": "B", "base": 0.5}, {"skill": "A", "base": 0.5},
                  {"skill": "Z", "base": 0.5}], cal)
check("the calibrated skill outranks the one it beat",
      [r["skill"] for r in ranked["ranking"]] == ["A", "Z", "B"], ranked["ranking"])
check("a skill with no evidence keeps its base score, with no invented gain",
      next(r for r in ranked["ranking"] if r["skill"] == "Z")["score"] == 0.5,
      ranked["ranking"])
check("a query residual is clipped to the cap",
      SR.rank([{"skill": "Z", "base": 0.0, "residual": 5.0}], {})["ranking"][0]["residual"] == SR.CAP)
check("a ranking row carries the cited events of its correction",
      next(r for r in ranked["ranking"] if r["skill"] == "A")["cited"] != [])

noev = SR.apply(cal, "nope")
check("no correction is written without a discordant comparison",
      noev["write"] is False
      and noev["findings"][0]["kind"] == "no-discordant-evidence", noev)
one = SR.apply(SR.calibrate([{"task": "t", "executor": "e",
                              "winner": "X", "loser": "Y"}]), "X")
check("one matched pair is not a reliability estimate",
      one["write"] is False
      and any(f["kind"] == "single-comparison" for f in one["findings"]), one)
ok2 = SR.apply(cal, "A")
check("two discordant comparisons admit a bounded correction",
      ok2["write"] is True
      and any(f["kind"] == "correction-clipped" for f in ok2["findings"]), ok2)

# ---- 2. closure-based rule retrieval ----------------------------------------
RULES = [
    {"id": "withdraw", "tokens": 50, "requires": ["identity"]},
    {"id": "identity", "tokens": 40, "requires": ["consent"]},
    {"id": "consent", "tokens": 30, "requires": []},
    {"id": "marketing", "tokens": 20, "requires": []},
]
clo = RR.closure(RULES, ["withdraw"], budget=500)
check("a seed pulls in its mandatory prerequisites transitively",
      clo["rules"] == ["withdraw", "identity", "consent"] and clo["complete"] is True
      and clo["decision"] == "use", clo)
check("a rule outside the closure is not selected",
      "marketing" not in clo["rules"], clo["rules"])
check("the closure is deduplicated when two seeds share a prerequisite",
      len(RR.closure(RULES, ["withdraw", "identity"])["rules"]) == 3)
unk = RR.closure(RULES, ["nope"])
check("a scenario keyword with no rule is a finding",
      any(f["kind"] == "unknown-seed" for f in unk["findings"])
      and unk["decision"] == "refuse", unk)
bad = RR.closure([{"id": "a", "tokens": 1, "requires": ["ghost"]}], ["a"])
check("a prerequisite the document never defines is a finding",
      any(f["kind"] == "unknown-prerequisite" for f in bad["findings"])
      and bad["complete"] is False, bad)
over = RR.closure(RULES, ["withdraw"], budget=100)
check("a complete set that does not fit the budget is refused",
      over["decision"] == "refuse"
      and any(f["kind"] == "over-budget" for f in over["findings"]), over)
empty = RR.closure(RULES, [])
check("a selection that reaches no rule cannot support a verdict",
      empty["decision"] == "refuse"
      and any(f["kind"] == "empty-closure" for f in empty["findings"]), empty)

miss = RR.audit(["withdraw"], RULES, ["withdraw"], budget=500)
check("a similarity selection that omits a prerequisite is named",
      miss["ok"] is False and miss["missing"] == ["consent", "identity"]
      and len([f for f in miss["findings"] if f["kind"] == "missing-prerequisite"]) == 2, miss)
extra = RR.audit(["withdraw", "identity", "consent", "marketing"], RULES,
                 ["withdraw"], budget=500)
check("a lookalike rule outside the closure is named",
      extra["extra"] == ["marketing"]
      and any(f["kind"] == "irrelevant-rule" for f in extra["findings"]), extra)
good = RR.audit(["withdraw", "identity", "consent"], RULES, ["withdraw"], budget=500)
check("a selection that equals the closure is conditionally complete",
      good["ok"] is True and good["findings"] == [], good)
none = RR.audit([], RULES, [], budget=500)
check("an empty selection is refused",
      any(f["kind"] == "empty-selection" for f in none["findings"]), none)

# ---- 3. skill quality profile ----------------------------------------------
FULL = {"sections": ["instructions", "tools", "examples", "resources"],
        "content_tokens": 100, "token_budget": 200,
        "tools": ["search", "write"], "tools_described": ["search", "write"],
        "models_tested": ["m1", "m2"],
        "perturbations": [{"kind": "rewrite", "held": True},
                          {"kind": "concise", "held": True}],
        "boundaries": ["unsafe", "unsupported", "infeasible"],
        "tokens_per_task": 100, "efficiency_budget": 200,
        "behavior_chain": [{"action": "search", "objective": "find"},
                           {"action": "write", "objective": "report"}],
        "task_granularity": "broad"}
prof = SQ.profile(FULL)
check("a fully evidenced skill is complete on all nine dimensions",
      prof["verdict"] == "complete" and prof["mean"] == 1.0
      and prof["findings"] == [] and len(prof["scores"]) == 9, prof)
thin = SQ.profile({**FULL, "sections": ["instructions"]})
check("a missing section lowers structural completeness and is named",
      thin["scores"]["structural_completeness"] == 0.25
      and any(f["kind"] == "missing-section" for f in thin["findings"]), thin)
bloated = SQ.profile({**FULL, "content_tokens": 400})
check("an over-long specification is reported",
      bloated["scores"]["conciseness"] == 0.5
      and any(f["kind"] == "over-budget" for f in bloated["findings"]), bloated)
phantom = SQ.profile({**FULL, "tools": ["search"], "tools_described": ["search", "deploy"]})
check("a promised capability the skill does not declare is a finding",
      any(f["kind"] == "described-not-declared" and f["tool"] == "deploy"
          for f in phantom["findings"]), phantom)
untested = SQ.profile({**FULL, "models_tested": ["m1"]})
check("stability never measured is reported, not scored as good",
      untested["scores"]["cross_model_robustness"] == 0.5
      and any(f["kind"] == "untested-across-models" for f in untested["findings"]), untested)
nopert = SQ.profile({**FULL, "perturbations": []})
check("a skill with no perturbation probe scores zero on stability",
      nopert["scores"]["intent_perturbation_stability"] == 0.0
      and any(f["kind"] == "untested-perturbations" for f in nopert["findings"]), nopert)
drop = SQ.profile({**FULL, "perturbations": [{"kind": "rewrite", "held": True},
                                             {"kind": "replace", "held": False}]})
check("a behaviour that did not survive a request change is named",
      drop["scores"]["intent_perturbation_stability"] == 0.5
      and any(f["kind"] == "perturbation-drop" for f in drop["findings"]), drop)
bound = SQ.profile({**FULL, "boundaries": ["unsafe"]})
check("an unhandled capability boundary is named",
      bound["scores"]["capability_boundary_handling"] == 0.3333
      and any(f["kind"] == "unhandled-boundary" for f in bound["findings"]), bound)
noeff = SQ.profile({**FULL, "efficiency_budget": 0})
check("efficiency with no budget is unmeasured, not perfect",
      noeff["scores"]["efficiency"] == 0.0
      and any(f["kind"] == "unmeasured-efficiency" for f in noeff["findings"]), noeff)
slow = SQ.profile({**FULL, "tokens_per_task": 400})
check("a skill over its efficiency budget is reported",
      slow["scores"]["efficiency"] == 0.5
      and any(f["kind"] == "over-efficiency-budget" for f in slow["findings"]), slow)
nochain = SQ.profile({**FULL, "behavior_chain": []})
check("no behaviour chain is a finding, not a pass",
      nochain["scores"]["behavior_chain_consistency"] == 0.0
      and any(f["kind"] == "no-behavior-chain" for f in nochain["findings"]), nochain)
unmapped = SQ.profile({**FULL, "behavior_chain": [{"action": "search"}]})
check("an action with no objective is named",
      any(f["kind"] == "unmapped-action" for f in unmapped["findings"]), unmapped)
nogen = SQ.profile({**FULL, "task_granularity": ""})
check("an undeclared task granularity is named",
      nogen["scores"]["task_abstraction_granularity"] == 0.0
      and any(f["kind"] == "undeclared-granularity" for f in nogen["findings"]), nogen)

REFS = [
    {"id": "r1", "tags": ["finance", "lookup"],
     "profile": {"structural_completeness": 0.8, "efficiency": 0.6}},
    {"id": "r2", "tags": ["finance"],
     "profile": {"structural_completeness": 1.0, "efficiency": 1.0}},
    {"id": "r3", "tags": ["legal"],
     "profile": {"structural_completeness": 0.2, "efficiency": 0.2}},
]
est = SQ.predict({"tags": ["finance", "lookup"]}, REFS)
check("the estimate cites the reference skills it used",
      [c["id"] for c in est["cited"]] == ["r1", "r2"], est["cited"])
check("the estimated profile is the mean of the cited references",
      est["estimated"]["structural_completeness"] == 0.9
      and est["estimated"]["efficiency"] == 0.8, est["estimated"])
check("a skill with no reference overlap gets no estimate",
      SQ.predict({"tags": ["cooking"]}, REFS)["estimated"] is None)
check("the estimate is limited to k references",
      len(SQ.predict({"tags": ["finance", "lookup"]}, REFS, k=1)["cited"]) == 1)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
