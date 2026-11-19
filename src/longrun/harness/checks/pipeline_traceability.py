#!/usr/bin/env python3
"""Pipeline traceability — blame is a computation over stages, not a guess.

Source: arXiv:2510.07614, "Traceability and Accountability in Role-Specialized
Multi-Agent LLM Pipelines" (round 140). A sequential pipeline turns collaboration
into an opaque system: the final answer is observable, its origin is not
(`pipeline_traceability_2510.07614.md:66`, `:70`). The study instruments a
Planner → Executor → Critic pipeline, compares each stage with the gold answer and
records who repaired and who harmed (`:196`, `:203`).

  * **repair and harm are different events**: an agent that fixes an upstream
    error is not the same agent as one that breaks a correct state (`:201`,
    `:235`).
  * **the error origin is the earliest unrepaired mistake**, not the last stage
    that touched the answer (`:207`).
  * **an accountable handoff lifts both the floor and the ceiling**: on PythonIO
    BBB rose from 61.42% to 97.64%, and unstructured pipelines fall below a
    competent single model (`:278`, `:337`).
  * **the planner dominates**: the best planner's error rate is 7.35% against
    40.49% for the worst, so casting is a data decision (`:397`, `:402`).
  * **accuracy, cost and latency trade off per task**, and a heterogeneous
    pipeline often sits on the Pareto frontier (`:469`, `:474`).

  * `final(stages)` — critic, else executor, else planner.
  * `blame(stages, gold)` — flags, and the error origin of one item.
  * `handoff(record)` — the structured handoff's required fields.
  * `rates(rows)` — per-model, per-role repair and harm rates.
  * `origins(rows)` — where failures start, and whether the planner dominates.
  * `pareto(rows)` — accuracy against cost, latency carried alongside.
  * `casting(table)` — the best model per role by measured behaviour.
  * `gain(pairs)` — simple pipeline against accountable pipeline.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: stage answers in; attribution out.
"""
from __future__ import annotations

FORMAT = "longrun-pipeline-traceability/1"

ROLES = ("planner", "executor", "critic")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def final(stages):
    """The published answer: prefer later stages."""
    s = stages or {}
    for role in ("critic", "executor", "planner"):
        if s.get(role) is not None:
            return s.get(role)
    return None


def blame(stages, gold):
    """Flags for one item and the earliest unrepaired mistake."""
    s = stages or {}
    p, e, c = s.get("planner"), s.get("executor"), s.get("critic")
    f = final(s)
    flags = {
        "planner_error": p is not None and p != gold,
        "executor_repair": p is not None and p != gold and e == gold,
        "executor_harm": p is not None and p == gold and e is not None and e != gold,
        "critic_repair": e is not None and e != gold and c == gold,
        "critic_harm": e is not None and e == gold and c is not None and c != gold,
    }
    if f == gold:
        origin = "NONE"
    elif e == gold and c is not None and c != gold:
        origin = "CRITIC"
    elif p == gold and e is not None and e != gold:
        origin = "EXECUTOR"
    else:
        origin = "PLANNER"
    return {"format": FORMAT, "final": f, "flags": flags, "origin": origin}


def handoff(record):
    """A structured, accountable handoff names its stage and carries an answer."""
    r = record or {}
    findings = []
    for role in ROLES:
        if role not in r:
            findings.append({"kind": "stage-missing", "role": role})
    answer = r.get("answer")
    if answer in (None, ""):
        findings.append({"kind": "answer-empty"})
    if not r.get("gold") and r.get("checked") is not False:
        findings.append({"kind": "no-check-against-gold"})
    if r.get("provenance") in (None, ""):
        findings.append({"kind": "no-provenance"})
    if not findings:
        findings.append({"kind": "handoff-structured"})
    return {"format": FORMAT, "findings": findings}


def rates(rows):
    """Per-model, per-role repair and harm rates over a set of items."""
    acc = {}

    def slot(model, role):
        entry = acc.setdefault(model, {})
        return entry.setdefault(role, {"cases": 0, "repair_opp": 0,
                                       "repair": 0, "harm_opp": 0, "harm": 0,
                                       "errors": 0})

    for row in rows or []:
        models = (row or {}).get("models") or {}
        ans = (row or {}).get("answers") or {}
        gold = (row or {}).get("gold")
        p, e, c = ans.get("planner"), ans.get("executor"), ans.get("critic")
        mp, me, mc = models.get("planner"), models.get("executor"), models.get("critic")
        if mp:
            s = slot(mp, "planner")
            s["cases"] += 1
            if p != gold:
                s["errors"] += 1
        if me:
            s = slot(me, "executor")
            s["cases"] += 1
            if p != gold:
                s["repair_opp"] += 1
                if e == gold:
                    s["repair"] += 1
            elif p == gold:
                s["harm_opp"] += 1
                if e is not None and e != gold:
                    s["harm"] += 1
        if mc:
            s = slot(mc, "critic")
            s["cases"] += 1
            if e != gold:
                s["repair_opp"] += 1
                if c == gold:
                    s["repair"] += 1
            elif e == gold:
                s["harm_opp"] += 1
                if c is not None and c != gold:
                    s["harm"] += 1
    out = {}
    for model, roles in acc.items():
        entry = {}
        for role, s in roles.items():
            entry[role] = {
                "cases": s["cases"],
                "planner_error_rate": (s["errors"] / s["cases"]
                                       if role == "planner" and s["cases"] else 0.0),
                "repair_rate": (s["repair"] / s["repair_opp"]
                                if s["repair_opp"] else 0.0),
                "harm_rate": (s["harm"] / s["harm_opp"] if s["harm_opp"] else 0.0),
                "repair_opp": s["repair_opp"], "harm_opp": s["harm_opp"],
            }
        out[model] = entry
    return {"format": FORMAT, "models": out}


def origins(rows):
    """Where the failures start, and whether the planner dominates."""
    tally = {"NONE": 0, "PLANNER": 0, "EXECUTOR": 0, "CRITIC": 0}
    for row in rows or []:
        res = blame((row or {}).get("answers") or {}, (row or {}).get("gold"))
        tally[res["origin"]] += 1
    fails = tally["PLANNER"] + tally["EXECUTOR"] + tally["CRITIC"]
    share = tally["PLANNER"] / fails if fails else 0.0
    if not fails:
        verdict = "no-failures"
    elif share >= 0.5:
        verdict = "planner-dominates"
    elif tally["CRITIC"] > tally["PLANNER"]:
        verdict = "critic-dominates"
    else:
        verdict = "mixed-origins"
    return {"format": FORMAT, "tally": tally, "failures": fails,
            "planner_share": share, "verdict": verdict}


def pareto(rows):
    """Accuracy maximized, cost minimized; latency is carried, not ranked."""
    clean = []
    for row in rows or []:
        acc = _num((row or {}).get("accuracy"))
        cost = _num((row or {}).get("cost"))
        if acc is None or cost is None:
            continue
        clean.append({"config": (row or {}).get("config"), "accuracy": acc,
                      "cost": cost, "latency": _num((row or {}).get("latency"))})
    frontier = []
    for row in clean:
        dominated = False
        for other in clean:
            if other is row:
                continue
            if (other["accuracy"] >= row["accuracy"]
                    and other["cost"] <= row["cost"]
                    and (other["accuracy"] > row["accuracy"]
                         or other["cost"] < row["cost"])):
                dominated = True
                break
        row["efficient"] = not dominated
        if not dominated:
            frontier.append(row["config"])
    return {"format": FORMAT, "rows": clean, "frontier": sorted(frontier)}


def casting(table):
    """Cast by measured behaviour: the best planner, executor and critic."""
    models = (table or {}).get("models") or {}
    picks = {}
    best = {}
    for model, roles in models.items():
        planner = roles.get("planner")
        if planner:
            score = -planner.get("planner_error_rate", 1.0)
            if "planner" not in best or score > best["planner"]:
                best["planner"] = score
                picks["planner"] = model
        for role in ("executor", "critic"):
            stats = roles.get(role)
            if not stats:
                continue
            score = stats.get("repair_rate", 0.0) - stats.get("harm_rate", 0.0)
            if role not in best or score > best[role]:
                best[role] = score
                picks[role] = model
    distinct = len(set(picks.values()))
    return {"format": FORMAT, "picks": picks, "scores": best,
            "mixed": distinct > 1,
            "note": "a mixed cast is a measured result, not a fallback"}


def gain(pairs, flat_band=0.5):
    """A simple pipeline against an accountable one, per configuration."""
    rows = []
    for pair in pairs or []:
        simple = _num((pair or {}).get("simple"))
        account = _num((pair or {}).get("accountable"))
        if simple is None or account is None:
            continue
        rows.append({"config": (pair or {}).get("config"),
                     "simple": simple, "accountable": account,
                     "delta": account - simple})
    if not rows:
        return {"format": FORMAT, "rows": [], "verdict": "no-pairs"}
    improved = sum(1 for r in rows if r["delta"] > flat_band)
    harmed = sum(1 for r in rows if r["delta"] < -flat_band)
    mean = sum(r["delta"] for r in rows) / len(rows)
    if improved == len(rows):
        verdict = "floor-and-ceiling"
    elif harmed > improved:
        verdict = "anti-synergy"
    elif mean > 0:
        verdict = "mixed-positive"
    else:
        verdict = "flat"
    return {"format": FORMAT, "rows": rows, "improved": improved,
            "harmed": harmed, "mean_delta": mean, "verdict": verdict}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("publishes_a_structured_handoff", "black-box-pipeline",
         "a consistent handoff gives the next stage a state to evaluate"),
        ("scores_every_stage", "final-only-score",
         "a final-only score cannot say where the error started"),
        ("separates_repair_from_harm", "one-quality-number",
         "fixing and breaking are opposite behaviours"),
        ("names_the_earliest_origin", "last-stage-blame",
         "the last agent that touched the answer is not the author of the error"),
        ("casts_by_measured_role", "same-model-everywhere",
         "planner error spans 7% to 40% across models"),
        ("reports_pareto_tradeoffs", "single-metric-ranking",
         "an accountable pipeline costs 2–3x and may not improve accuracy"),
        ("compares_to_a_monolith", "pipeline-without-baseline",
         "an unstructured pipeline can fall below a single model"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
