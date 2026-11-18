#!/usr/bin/env python3
"""v1195 — optimizer memory, trajectory detour, control-gated patch probes (round 126).

Sources:
  * arXiv:2611.18856 "SIM" — the harness optimizer keeps WHY: root causes, rationale,
    predicted vs observed outcomes, provenance; inherited mechanisms are revised
    when the model or benchmark changes.
  * arXiv:2611.20844 "DetourBench" — success, conditional attainment, residual work,
    normalized detour and irreversible failure are different measurements.
  * arXiv:2611.20514 "Beyond the Patch" — a control-gated tri-state verdict, and a
    same-version divergence where the reported trigger is blocked and a sibling
    path still violates the invariant.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1195_optimizer_memory_detour_patch.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1195-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import optimizer_memory as OM  # noqa: E402
from longrun.harness import detour as DT            # noqa: E402
from longrun.harness import patch_probe as PP       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. optimizer memory: record -------------------------------------------
EDIT = {"problem": "premature completion", "change": "check feasibility before done",
        "rationale": "commands succeeded but the solution was not optimal",
        "predicted": ["t3"], "observed": {"fixed": ["t3"], "regressed": []},
        "provenance": {"benchmark": "TB2.1", "model": "opus", "round": 4}}
check("an edit with no root cause is refused",
      "no-root-cause" in kinds(OM.record({}, {"change": "do something"})))
first = OM.record({}, EDIT)
check("the first attempt is recorded under its root cause",
      first["attempts"] == 1 and list(first["memory"]["entries"]) == ["premature completion"])
check("a complete edit carries no finding", first["findings"] == [], first["findings"])
second = OM.record(first["memory"], EDIT)
check("the same root cause extends the history instead of replacing it",
      second["attempts"] == 2 and "duplicate-root-cause" in kinds(second), second["attempts"])
third = OM.record(second["memory"], {**EDIT, "drop_history": True})
check("history cannot be dropped",
      third["attempts"] == 3 and "history-dropped" in kinds(third), third["attempts"])
check("an edit with no rationale is flagged",
      "no-rationale" in kinds(OM.record({}, {**EDIT, "rationale": ""})))
check("an edit with no prediction is flagged",
      "no-prediction" in kinds(OM.record({}, {**EDIT, "predicted": []})))
check("an edit with no measured outcome is flagged",
      "no-outcome" in kinds(OM.record({}, {**EDIT, "observed": {}})))

# ---- 2. optimizer memory: continuity ---------------------------------------
def mem_for(observed, prov):
    return OM.record({}, {**EDIT, "observed": observed, "provenance": prov})["memory"]


check("a mechanism that regressed and fixed nothing is removed",
      OM.continuity(mem_for({"regressed": ["t1"]}, {"benchmark": "B", "model": "m"}),
                    {"benchmark": "B", "model": "m"})["decisions"]["premature completion"]
      ["decision"] == "remove")
check("the removal cites the source regression",
      "source-regression" in kinds(OM.continuity(
          mem_for({"regressed": ["t1"]}, {"benchmark": "B", "model": "m"}),
          {"benchmark": "B", "model": "m"})))
cross_model = OM.continuity(mem_for({"fixed": ["t1"]}, {"benchmark": "B", "model": "opus"}),
                            {"benchmark": "B", "model": "gemini"})
check("a mechanism measured on another model is revised",
      cross_model["decisions"]["premature completion"]["decision"] == "revise"
      and "model-mismatch" in kinds(cross_model), cross_model)
cross_data = OM.continuity(mem_for({"fixed": ["t1"]}, {"benchmark": "TB2.1", "model": "m"}),
                           {"benchmark": "TB4", "model": "m"})
check("a mechanism measured on another benchmark is revised",
      cross_data["decisions"]["premature completion"]["decision"] == "revise"
      and "benchmark-mismatch" in kinds(cross_data))
same = OM.continuity(mem_for({"fixed": ["t1"]}, {"benchmark": "B", "model": "m"}),
                     {"benchmark": "B", "model": "m"})
check("a mechanism with a measured fix on the same setting is reused",
      same["decisions"]["premature completion"]["decision"] == "reuse")
unfixed = OM.continuity(mem_for({"unchanged": ["t1"]}, {"benchmark": "B", "model": "m"}),
                        {"benchmark": "B", "model": "m"})
check("an edit that fixed nothing is revised, not reused",
      unfixed["decisions"]["premature completion"]["decision"] == "revise"
      and "unconfirmed-transfer" in kinds(unfixed))
check("a prediction with no observed outcome is named",
      "predicted-unobserved" in kinds(OM.continuity(
          mem_for({"unchanged": ["t9"]}, {"benchmark": "B", "model": "m"}),
          {"benchmark": "B", "model": "m"})))

PAIRS = [{"sim": 20.0 + d, "no_sim": 20.0} for d in
         (1.81, 1.81, 0.61, 5.46, 1.82, 3.64, 1.82, -0.61, 4.85, 2.42)]
adv = OM.advantage(PAIRS)
check("the paired mean is the mean of the differences",
      adv["mean"] == 2.363 and adv["wins"] == 9 and adv["losses"] == 1, adv)
check("nine of ten wins reach the 0.05 sign-test level", adv["p"] == 0.0215, adv["p"])
check("a losing pair is reported, not hidden",
      "mixed-pairs" in kinds(adv))
thin = OM.advantage([{"sim": 2, "no_sim": 1}, {"sim": 2, "no_sim": 1},
                     {"sim": 2, "no_sim": 1}])
check("a mean with three wins is not evidence", "not-significant" in kinds(thin), thin)
check("a comparison with no pairs says so", "no-pairs" in kinds(OM.advantage([])))

# ---- 3. trajectory cost ----------------------------------------------------
check("attainment is the exact bound over the charged accesses",
      DT.attainment(True, 20, 15)["attainment"] == 0.75)
check("a failure has no attainment",
      DT.attainment(False, 20, 15)["attainment"] is None
      and "not-success" in kinds(DT.attainment(False, 20, 15)))
check("a trace shorter than the bound is flagged, not trusted",
      DT.attainment(True, 10, 15)["attainment"] == 1.0
      and "below-optimum" in kinds(DT.attainment(True, 10, 15)))
check("no bound means no oracle-relative measure",
      "no-optimum" in kinds(DT.attainment(True, 20, None)))
check("residual work is zero on success", DT.residual(True, False)["residual"] == 0)
check("an irreversible commitment has no finite residual",
      DT.residual(False, True)["residual"] is None
      and "irreversible" in kinds(DT.residual(False, True)))
check("a recoverable stop reports its exact remaining accesses",
      DT.residual(False, False, 3)["residual"] == 3)
check("an unmeasured terminal state is not assigned a distance",
      "no-residual" in kinds(DT.residual(False, False, None)))
pg = DT.progress(True, 0, 15, charged=20)
check("a successful run has full progress and its normalized detour",
      pg["progress"] == 1.0 and pg["ndr"] == 0.3333, pg)
check("a near miss shows residual-distance progress",
      DT.progress(False, 3, 15)["progress"] == 0.8)
check("invalid plus repeated accesses over charged accesses is RSR",
      DT.rsr(1, 2, 20)["rsr"] == 0.15)
check("RSR with no charged access is undefined",
      DT.rsr(1, 2, 0)["rsr"] is None)

EPS = [
    {"id": "e1", "model": "A", "success": True, "charged": 15, "optimum": 15},
    {"id": "e2", "model": "A", "success": True, "charged": 18, "optimum": 15},
    {"id": "e3", "model": "A", "success": False, "residual": 1, "optimum": 15},
    {"id": "e4", "model": "A", "success": False, "residual": 6, "optimum": 15},
    {"id": "e5", "model": "A", "success": False, "wrong": True, "optimum": 15},
    {"id": "e6", "model": "A", "success": False, "optimum": 15},
]
cls = DT.classify(EPS)
by_id = {r["id"]: r["class"] for r in cls["episodes"]}
check("a shortest successful run is direct", by_id["e1"] == "direct")
check("a successful run with excess accesses is exploratory", by_id["e2"] == "exploratory")
check("a failure one access from the goal is a near miss", by_id["e3"] == "near-miss")
check("a failure far from the goal is costly incompletion", by_id["e4"] == "costly-incomplete")
check("an absorbing wrong commitment is its own class", by_id["e5"] == "irreversible")
check("an unmeasured terminal state is not classified as a near miss",
      by_id["e6"] == "unmeasured", by_id)
check("the class counts add up to the episode count",
      sum(cls["counts"].values()) == len(EPS), cls["counts"])

REV = ([{"model": "A", "success": True, "charged": 25, "optimum": 15}] * 3
       + [{"model": "B", "success": True, "charged": 15, "optimum": 15},
          {"model": "B", "success": True, "charged": 15, "optimum": 15},
          {"model": "B", "success": False, "optimum": 15}])
rank = DT.rank_models(REV)
check("the endpoint orders A first and the trajectory orders B first",
      rank["models"]["A"]["success_rate"] == 1.0
      and rank["models"]["B"]["attainment"] == 1.0
      and "ordering-reversal" in kinds(rank), rank)

# ---- 4. patch probes -------------------------------------------------------
check("a failing control makes any effect inconclusive",
      PP.verdict(False, True)["verdict"] == PP.INCONCLUSIVE
      and "control-failed" in kinds(PP.verdict(False, True)))
check("an observed effect behind a passing control is a violation",
      PP.verdict(True, True)["verdict"] == PP.VIOLATION)
check("a stale marker is not an effect",
      PP.verdict(True, True, token_ok=False)["verdict"] == PP.INCONCLUSIVE
      and "stale-marker" in kinds(PP.verdict(True, True, token_ok=False)))
nvo = PP.verdict(True, False)
check("no effect behind a passing control is a NON-violation, not safety",
      nvo["verdict"] == PP.NO_VIOLATION
      and "secure" not in nvo["why"].lower() and "proof" not in nvo["why"].lower(),
      nvo["why"])
split = PP.compare({"version": "4.6.31", "verdict": PP.NO_VIOLATION, "path": "tool_resolver"},
                   {"version": "4.6.31", "verdict": PP.VIOLATION, "path": "tool_override"})
check("a same-version split is an incomplete fix",
      split["divergence"] is True and "incomplete-fix" in kinds(split), split)
check("a before/after pair is not called a same-version bypass",
      PP.compare({"version": "4.5.139", "verdict": PP.VIOLATION},
                 {"version": "4.6.32", "verdict": PP.NO_VIOLATION})["divergence"] is False
      and "different-versions" in kinds(
          PP.compare({"version": "4.5.139", "verdict": PP.VIOLATION},
                     {"version": "4.6.32", "verdict": PP.NO_VIOLATION})))
PROV = PP.provenance([{"version": "4.5.139", "verdict": PP.VIOLATION},
                      {"version": "4.6.31", "verdict": PP.VIOLATION},
                      {"version": "4.6.32", "verdict": PP.NO_VIOLATION}],
                     {"fixed_version": "4.6.31"})
check("the first holding version is the observation, not the advisory",
      PROV["first_observed_fix"] == "4.6.32"
      and "metadata-disagrees" in kinds(PROV), PROV)
check("an advisory with no fixed version is named",
      "no-recorded-fix" in kinds(PP.provenance(
          [{"version": "1.11.1", "verdict": PP.NO_VIOLATION}], {})))
check("no tested version holding is reported",
      "no-observed-fix" in kinds(PP.provenance(
          [{"version": "1.11.0", "verdict": PP.VIOLATION}], {})))
bad = PP.validate([{"boundary": "b", "path": "p"}])
check("a run without a control, token or observer is invalid",
      bad["valid"] is False
      and {"control-missing", "token-missing", "observer-missing"} <= set(kinds(bad)),
      kinds(bad))
check("a complete run validates",
      PP.validate([{"boundary": "b", "path": "p", "control_ok": True,
                    "token": "t1", "observer": "flag"}])["valid"] is True)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
