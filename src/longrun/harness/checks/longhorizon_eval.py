#!/usr/bin/env python3
"""Long-horizon evaluation — all-or-nothing delivery over many requests.

Source: arXiv:2611.05620, "ViBench 2.0: A Benchmark for Long-Horizon Software
Building" (round 157). Products grow from an empty project through successive
feature requests, and only the finished product is graded, as a user would use it
(`vibench2_longhorizon_2611.05620.txt:24`, `:67`).

  * **pass@1 is all-or-nothing**: every test plan must pass, and a product that
    fails to start fails all of its plans (`:288`, `:292`).
  * **the grading protocol targets wrong fails**: a passing plan is not regraded;
    a failing plan is regraded until three of up to five grades agree (`:211`,
    `:216`).
  * **the gap is reliability, not capability**: the strongest models pass 94–98%
    of plans yet deliver a working product in at most 65% of builds (`:37`,
    `:311`).
  * **the plan pass rate moves first** across model releases and is the earlier
    signal; pass@1 separates only the strongest (`:298`, `:304`).
  * **held-out products keep the comparison fair**: the public subset is harder
    (7–12 points lower) but nearly preserves the ranking (ρ = 0.99) (`:372`,
    `:377`).

  * `plan(record)` — pass@1 and the plan pass rate.
  * `grade(record)` — the majority rule for a failed plan.
  * `gap(record)` — plan rate against complete delivery.
  * `horizon(record)` — the shape of a long-horizon benchmark.
  * `split(record)` — public versus held-out products.
  * `grade_quality(record)` — both error directions and planted bugs.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: plan outcomes and build rows in; scores and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-longhorizon-eval/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def plan(record):
    """pass@1 requires every plan; a product that did not start fails all."""
    r = record or {}
    outcomes = [bool(v) for v in (r.get("plans") or [])]
    if not outcomes:
        return {"format": FORMAT, "verdict": "no-plans"}
    started = r.get("started", True) is not False
    passed = sum(1 for v in outcomes if v)
    rate = passed / len(outcomes)
    complete = started and passed == len(outcomes)
    return {"format": FORMAT, "plans": len(outcomes), "passed": passed,
            "plan_rate": rate, "pass_at_1": 1 if complete else 0,
            "verdict": "complete" if complete else "incomplete"}


def grade(record):
    """A failing plan is regraded until three of at most five grades agree."""
    r = record or {}
    first = r.get("first") == "pass"
    if first:
        return {"format": FORMAT, "verdict": "pass-first-grade", "regrades": 0}
    regrades = list(r.get("regrades") or [])[:4]
    evidence = r.get("evidence_ok", True) is not False
    if not evidence:
        return {"format": FORMAT, "verdict": "regrade-required", "regrades": 0}
    grades = ["fail"] + [str(g).lower() for g in regrades]
    if len(grades) >= 3:
        tail = grades[-(len(grades))]
        fails = grades.count("fail")
        passes = grades.count("pass")
        if fails >= 3:
            return {"format": FORMAT, "verdict": "fail", "regrades": len(regrades)}
        if passes >= 3:
            return {"format": FORMAT, "verdict": "pass", "regrades": len(regrades)}
    return {"format": FORMAT, "verdict": "pending", "regrades": len(regrades)}


def gap(record):
    """High plan rate with low complete delivery is the reliability gap."""
    r = record or {}
    rate = _num(r.get("plan_rate"))
    plans = int(_num(r.get("plans") or 0))
    observed = _num(r.get("pass_at_1"))
    if rate is None or observed is None or plans <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    independent = rate ** plans
    gap_points = (rate - observed) * 100.0
    return {"format": FORMAT, "plan_rate": rate, "plans": plans,
            "independent_complete": independent, "observed": observed,
            "gap_points": gap_points,
            "verdict": "reliability-gap" if rate >= 0.9 and observed <= 0.65
            else "aligned"}


def horizon(record):
    """A long-horizon benchmark has many dependent stages and compound plans."""
    r = record or {}
    products = int(_num(r.get("products") or 0))
    requests = int(_num(r.get("requests") or 0))
    plans = int(_num(r.get("plans") or 0))
    per_product = (requests / products) if products else 0.0
    compound = _num(r.get("compound_share"))
    if not products or not plans:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "products": products, "requests": requests,
            "plans": plans, "requests_per_product": per_product,
            "compound_share": compound,
            "verdict": "long-horizon" if per_product >= 9 else "short-horizon"}


def split(record):
    """Public versus held-out products: a faithful but harder proxy."""
    r = record or {}
    public = _num(r.get("public_pass1"))
    heldout = _num(r.get("heldout_pass1"))
    rho = _num(r.get("spearman"))
    if public is None or heldout is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    faithful = rho is not None and rho >= 0.9
    return {"format": FORMAT, "public": public, "heldout": heldout,
            "delta_points": (public - heldout) * 100.0, "spearman": rho,
            "verdict": "faithful-proxy" if faithful else "ranking-diverges"}


def grade_quality(record):
    """Both grading errors and the planted-bug check."""
    r = record or {}
    false_fail = _num(r.get("false_fail"))
    false_pass = _num(r.get("false_pass"))
    caught = int(_num(r.get("planted_caught") or 0))
    total = int(_num(r.get("planted_total") or 0))
    if false_fail is None or false_pass is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    reliable = false_fail <= 0.005 and false_pass <= 0.01 and \
        (total == 0 or caught == total)
    return {"format": FORMAT, "false_fail": false_fail, "false_pass": false_pass,
            "planted_caught": caught, "planted_total": total,
            "verdict": "reliable" if reliable else "unreliable"}


def audit_record(record):
    """The misreadings the benchmark's design excludes."""
    r = record or {}
    findings = []
    if r.get("single_task_is_long_horizon") is True:
        findings.append({"kind": "single-task-is-long-horizon",
                         "why": "the product is graded only after the last request"})
    if r.get("plan_rate_as_pass_at_1") is True:
        findings.append({"kind": "plan-rate-as-pass-at-1",
                         "why": "every plan must pass for a build to count"})
    if r.get("feedback_between_requests") is True:
        findings.append({"kind": "feedback-between-requests",
                         "why": "the benchmark gives no bug reports between stages"})
    if r.get("public_subset_is_the_score") is True:
        findings.append({"kind": "public-subset-is-the-score",
                         "why": "held-out products guard against training"})
    if r.get("wrong_pass_is_ignored") is True:
        findings.append({"kind": "wrong-pass-is-ignored",
                         "why": "regrading removes wrong fails, not wrong passes"})
    if r.get("visual_quality_is_graded") is True:
        findings.append({"kind": "visual-quality-is-graded",
                         "why": "the benchmark measures functional correctness"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the long-horizon evaluation gaps."""
    p = profile or {}
    have = {str(k) for k in p if p.get(k)}
    checks = (
        ("grows_one_product_over_many_requests", "scores_single_tasks",
         "later requests build on code the agent wrote"),
        ("grades_the_finished_product", "grades_each_step",
         "the question is whether the whole still works"),
        ("requires_every_plan_to_pass", "reports_a_mean_plan_rate",
         "a build counts only if all plans pass"),
        ("regrades_failed_plans", "trusts_one_grade",
         "a single grade wrongly fails a working plan 0.2% of the time"),
        ("keeps_held_out_products", "publishes_every_task",
         "tasks a model can train on stop measuring it"),
        ("reports_plan_rate_beside_pass_at_1", "reports_one_score",
         "plan rate moves before complete delivery"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
