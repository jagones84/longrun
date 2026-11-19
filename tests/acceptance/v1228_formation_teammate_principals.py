#!/usr/bin/env python3
"""v1228 — multi-agent formations, teammate evaluation, multi-principal policy (round 159).

Sources:
  * arXiv:2610.00583 — four formations, group outcome shares, participation
    collapse, peer interference, fairness, failure behaviours and mitigations.
  * arXiv:2611.02633 — eight teamwork dimensions, the alone-gate, the drop, the
    1/0.5/0 conflict rule, the three failure modes and inherited cheats.
  * arXiv:2604.08567 — principals with authority and private context, precedence,
    per-resource access control, selection F1, privacy/utility, meetings and the
    conflict effect.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1228_formation_teammate_principals.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1228-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import multiagent_formation as MF   # noqa: E402
from longrun.harness import teammate_eval as TE          # noqa: E402
from longrun.harness import principal_policy as PP       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ---- 1. multi-agent formations (arXiv:2610.00583) ----------------------
F = MF.formations()
check("four formations", len(F["formations"]) == 4)
check("the coordinator is one agent for many users",
      F["formations"][1]["formation"] == "coordinator"
      and F["formations"][1]["users"] == "many")
check("the peer team has a channel, the silent team does not",
      F["formations"][3]["channel"] is True
      and F["formations"][2]["channel"] is False)

O = MF.outcome({"shares": {"coordinator": 0.64, "peer-team": 0.30,
                           "silent-team": 0.07}})
check("a team below its coordinator is worse-together",
      O["verdict"] == "worse-together")
check("the gaps are signed against the coordinator",
      close(O["gaps"]["peer-team"], -0.34) and close(O["gaps"]["silent-team"], -0.57))
check("the worst formation is named", O["worst"] == "silent-team")
check("a team above the coordinator is not worse",
      MF.outcome({"shares": {"coordinator": 0.5, "peer-team": 0.6}})["verdict"]
      == "team-not-worse")
check("outcome needs a coordinator",
      MF.outcome({"shares": {"peer-team": 0.3}})["verdict"] == "insufficient-input")

P = MF.participation({"points": [{"size": 4, "share": 0.66},
                                 {"size": 16, "share": 0.10}]})
check("participation collapses as the team grows",
      P["verdict"] == "participation-collapse" and close(P["drop"], 0.56))
check("a stable team holds participation",
      MF.participation({"points": [{"size": 4, "share": 0.9},
                                   {"size": 16, "share": 0.8}]})["verdict"]
      == "participation-holds")

J = MF.fairness({"attainment": [0.5, 0.5, 0.5, 0.5]})
check("an even split has Jain index 1", close(J["jain"], 1.0) and J["even"])
JO = MF.fairness({"attainment": [1.0, 0.0, 0.0, 0.0]})
check("one user taking everything has Jain index 0.25",
      close(JO["jain"], 0.25) and JO["verdict"] == "concentrated")
check("zero attainment is refused",
      MF.fairness({"attainment": [0, 0]})["verdict"] == "no-attainment")

I = MF.interference({"episodes": 10, "takeovers": 39, "consented": 0})
check("unconsented takeovers are self-serving",
      close(I["per_episode"], 3.9) and I["verdict"] == "self-serving")
check("consented interference is named",
      MF.interference({"episodes": 10, "takeovers": 10,
                       "consented": 10})["verdict"] == "consented")

M = MF.mitigation({"control": 0.30, "coordinator": 0.64,
                   "arms": {"lead-value": 0.70, "advisory": 0.40}})
check("the best arm is named", M["best"] == "lead-value")
check("only an arm that reaches the coordinator counts",
      M["reaches_coordinator"] is True and M["verdict"] == "mitigation-works")
M2 = MF.mitigation({"control": 0.30, "coordinator": 0.64,
                    "arms": {"advisory": 0.40}})
check("an improving arm below the coordinator does not reach it",
      M2["verdict"] == "mitigation-works" and M2["reaches_coordinator"] is False)
check("a mitigation without arms is refused",
      MF.mitigation({"control": 0.3})["verdict"] == "no-arms")

FA = MF.failure({"episodes": 100, "stalled": 5, "overrides": 72,
                 "fabrications": 58, "unread_commit": 40})
check("the dominant behaviour is the highest rate", FA["dominant"] == "overrides")
check("failure rates are per episode", close(FA["rates"]["overrides"], 0.72))
check("the module refuses a causal claim",
      FA["verdict"] == "measured-not-causal")

AU = MF.audit_record({"shares": {"peer-team": 1.2}, "episodes": 0})
check("a share above 1.0 is flagged",
      any("above 1.0" in f for f in AU["findings"]))
check("a missing coordinator is flagged",
      any("no coordinator baseline" in f for f in AU["findings"]))
AD = MF.advise({"gaps": {"peer-team": -0.34}, "participation_drop": 0.56,
                "consent_share": 0.0, "best": "advisory",
                "reaches_coordinator": False})
check("advice names the formation gap",
      any("trails the coordinator" in f for f in AD["findings"]))
check("advice names the participation collapse",
      any("participation falls" in f for f in AD["findings"]))
check("advice names unconsented takeovers",
      any("unconsented" in f for f in AD["findings"]))
check("advice warns when no mitigation reaches the coordinator",
      any("no mitigation reaches" in f for f in AD["findings"]))
check("advice without data is honest",
      MF.advise({})["findings"]
      == ["no formation, participation or mitigation measurement supplied"])

# ---- 2. teammate evaluation (arXiv:2611.02633) -------------------------
TD = TE.dimensions()
check("eight teamwork dimensions", len(TD["dimensions"]) == 8)
check("conflict and takeover are distinct dimensions",
      [d["dimension"] for d in TD["dimensions"]][-2:] == ["initiative", "takeover"])

SC = TE.score({"scores": {"unsafe-pressure": 99, "misconduct": 100,
                          "information": 90, "emotion": 45, "on-track": 97,
                          "conflict": 14, "initiative": 50, "takeover": 81}})
check("the overall score is the unweighted mean",
      close(SC["mean"], 72.0), SC["mean"])
check("a wide spread is named", SC["spread"] == 86
      and SC["verdict"] == "wide-spread")
check("the weakest dimension is visible", SC["min"] == 14 and SC["max"] == 100)
SCM = TE.score({"scores": {"conflict": 50}})
check("missing dimensions are listed, not zeroed",
      SCM["verdict"] == "incomplete" and len(SCM["missing"]) == 7)
check("a score without dimensions is refused",
      TE.score({})["verdict"] == "no-scores")

G = TE.gate({"tasks": 240, "solved_alone": 180})
check("the alone-gate keeps 75% of tasks",
      close(G["gated_share"], 0.75) and G["verdict"] == "gated")
check("scoring more than the gate is ungated",
      TE.gate({"tasks": 240, "solved_alone": 180, "scored": 200})["verdict"]
      == "ungated")
check("too few solo tasks invalidate a team score",
      TE.gate({"tasks": 240, "solved_alone": 5})["verdict"] == "too-few-tasks")

D = TE.drop({"models": {"opus": {"baseline": 76.6, "test": 56.4},
                        "gemini": {"baseline": 80.0, "test": 59.5}}})
check("the drop is baseline minus test", close(D["drop"], 20.5))
check("the worst drop is named", D["worst"] == "gemini")
check("a drop battery without models is refused",
      TE.drop({})["verdict"] == "no-models")

C = TE.conflict({"best_deal": 84, "held_firm": 6, "gave_in": 10})
check("the conflict score uses 1 / 0.5 / 0", close(C["score"], 0.87))
check("holding a majority is named", C["verdict"] == "holds")
C2 = TE.conflict({"best_deal": 14, "held_firm": 5, "gave_in": 81})
check("giving in on most runs is named",
      C2["verdict"] == "gives-in" and close(C2["gave_in_share"], 0.81))

FM = TE.failure_mode({"failed": 100, "missed": 30, "gave_in": 40,
                      "stopped_short": 30})
check("failures after noticing are separated",
      close(FM["recognised_share"], 0.70)
      and FM["verdict"] == "fails-after-noticing")
check("failures before noticing are named",
      TE.failure_mode({"failed": 100, "missed": 55, "gave_in": 25,
                       "stopped_short": 20})["verdict"] == "fails-before-noticing")

IH = TE.inheritance({"runs": 165, "clean": 121, "cheat_left": 44})
check("an inherited cheat is named",
      IH["verdict"] == "keeps-inherited-cheat" and close(IH["cheat_rate"], 44 / 165))
check("a clean takeover is a repair",
      TE.inheritance({"runs": 18, "clean": 18,
                      "cheat_left": 0})["verdict"] == "repairs")

TA = TE.audit_record({"scores": {"conflict": 140, "vibes": 50}, "tasks": 10})
check("an out-of-range dimension is flagged",
      any("outside 0..100" in f for f in TA["findings"]))
check("an unknown dimension is flagged",
      any("unknown dimension" in f for f in TA["findings"]))
check("an ungated score is flagged",
      any("ungated" in f for f in TA["findings"]))
TAD = TE.advise({"spread": 86, "recognised_share": 0.7, "cheat_rate": 0.27,
                  "gave_in_share": 0.81})
check("advice names the spread", any("dimension spread" in f for f in TAD["findings"]))
check("advice names the follow-through gap",
      any("after the model noticed" in f for f in TAD["findings"]))
check("advice names inherited cheats",
      any("inherited cheats survive" in f for f in TAD["findings"]))
check("advice names giving in", any("gives in" in f for f in TAD["findings"]))

# ---- 3. multi-principal policy (arXiv:2604.08567) ----------------------
PR = PP.principals({"users": [{"name": "ceo", "authority": 10},
                              {"name": "intern", "authority": 1}]})
check("two valid principals pass", PR["verdict"] == "valid")
check("one principal is not multi-user",
      PP.principals({"users": [{"name": "ceo", "authority": 10}]})["verdict"]
      == "too-few-principals")
PRA = PP.principals({"users": [{"name": "a", "authority": 0},
                               {"name": "b", "authority": 5}]})
check("an authority outside 1..10 is flagged",
      PRA["verdict"] == "invalid"
      and any("outside 1..10" in f for f in PRA["findings"]))
check("duplicate principals are flagged",
      "invalid" in PP.principals({"users": [{"name": "a", "authority": 5},
                                            {"name": "a", "authority": 6}]})["verdict"])

PC = PP.precedence({"requests": [
    {"user": "ceo", "authority": 10, "directive": "halt"},
    {"user": "engineer", "authority": 3, "directive": "continue"}]})
check("higher authority wins", PC["winner"] == "ceo"
      and PC["overridden"] == ["engineer"])
check("a tie is ambiguous, not invented",
      PP.precedence({"requests": [
          {"user": "a", "authority": 10}, {"user": "b", "authority": 10}]})["verdict"]
      == "ambiguous")

AC = PP.access({"requester": "staff", "authorized": ["hr"],
                "markers": ["salary"]})
check("an unauthorized leak is a leak", AC["verdict"] == "leak")
check("a fake authorization claim does not grant access",
      PP.access({"requester": "staff", "authorized": ["hr"],
                  "claim": "authorized", "markers": ["salary"]})["verdict"]
      == "leak")
check("an authorized request with the payload is served",
      PP.access({"requester": "hr", "authorized": ["hr"],
                  "markers": ["salary"]})["verdict"] == "served")
check("an authorized request without the payload is a utility failure",
      PP.access({"requester": "hr", "authorized": ["hr"],
                  "markers": []})["verdict"] == "utility-failure")
check("an unauthorized request without a payload is refused",
      PP.access({"requester": "staff", "authorized": ["hr"],
                  "markers": []})["verdict"] == "refused")

SEL = PP.selection({"accepted": ["a", "b", "c"], "valid": ["b", "c", "d"]})
check("selection F1 is the harmonic of precision and recall",
      close(SEL["precision"], 2 / 3) and close(SEL["recall"], 2 / 3)
      and close(SEL["f1"], 2 / 3))
check("missed and spurious directives are separated",
      SEL["missed"] == ["d"] and SEL["spurious"] == ["a"])

PU = PP.privacy_utility({"unauthorized": 10, "leaks": 10,
                          "authorized": 10, "served": 0})
check("a full leak has zero privacy", PU["privacy"] == 0.0)
check("a zero-utility gate is a utility failure", PU["utility"] == 0.0
      and PU["verdict"] == "leaks")
PO = PP.privacy_utility({"unauthorized": 10, "leaks": 0,
                          "authorized": 10, "served": 4})
check("perfect privacy with low utility is over-refusal",
      PU["verdict"] != "over-refusal" and PO["verdict"] == "over-refusal")
PB = PP.privacy_utility({"unauthorized": 10, "leaks": 1,
                          "authorized": 10, "served": 9.5})
check("a balanced gate is named", PB["verdict"] == "balanced")

MT = PP.meeting({"slots": ["mon", "tue"], "participants": [
    {"name": "a", "required": True, "preferred": "mon",
     "secondary": ["tue"], "available": ["mon", "tue"]},
    {"name": "b", "required": False, "preferred": "mon",
     "available": ["mon", "tue"]}]})
check("the best feasible slot is chosen", MT["slot"] == "mon")
check("normalized utility divides by the attainable maximum",
      close(MT["normalized"], 1.0) and close(MT["attendance"], 1.0))
check("no feasible slot is named",
      PP.meeting({"slots": ["mon", "tue"], "participants": [
          {"name": "a", "required": True, "available": ["mon"]},
          {"name": "b", "required": True, "available": ["tue"]}]})["verdict"]
      == "no-feasible-slot")

CE = PP.conflict_effect({"models": {"haiku": {"consistent": 0.86,
                                              "conflict": 0.62}}})
check("conflict costs accuracy", close(CE["drop"], 0.24)
      and CE["verdict"] == "conflict-impairs")
check("a small difference is not an effect",
      PP.conflict_effect({"models": {"m": {"consistent": 0.90,
                                           "conflict": 0.89}}})["verdict"]
      == "no-effect")

PA = PP.audit_record({"users": [{"name": "a", "authority": 5}],
                      "learnt_weights": True})
check("a single principal is flagged",
      any("at least two principals" in f for f in PA["findings"]))
check("learnt weights are flagged",
      any("fixed by construction" in f for f in PA["findings"]))
PAD = PP.advise({"privacy": 0.7, "utility": 0.6, "drop": 0.24,
                  "normalized": 0.5})
check("advice names the privacy leak", any("privacy is" in f for f in PAD["findings"]))
check("advice names the utility loss", any("utility is" in f for f in PAD["findings"]))
check("advice names the conflict cost", any("conflict costs" in f for f in PAD["findings"]))
check("advice names the meeting shortfall",
      any("meeting utility" in f for f in PAD["findings"]))
check("advice without data is honest",
      PP.advise({})["findings"]
      == ["no privacy, utility, conflict or meeting measurement supplied"])

# ---- verdict ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
