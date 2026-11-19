#!/usr/bin/env python3
"""Execution policy — a declared plan order is not an identified one.

Source: arXiv:2611.21688, "DeltaHarness: Self-Evolving Harnesses for Resource-
Adaptive Tool Execution" (round 124). Two execution plans can share the same
visible task and resource description and still REVERSE their latency ordering,
because cache state, interference and input service are not in the description
(§3). Resolving that requires firsthand measurement in the target setting, and
the paper's own replacement rule is deliberately hard to satisfy:

  * the candidate is FROZEN before a separate confirmation panel is revealed;
  * only the confirmation panel enters the replace/retain decision — the
    candidate's own selected measurements never justify its adoption (§4.3);
  * replacement needs ratio <= 0.995 and a one-sided 90% upper bound below 1;
  * failed deliveries are counted separately from latency, never priced as a
    slow success (predefined penalties are for SEARCH losses only, §5);
  * acquisition cost is amortized over deployed tasks, so a lower latency can
    still be a worse deal (§3, C_improve / n).

  * `reversal(declared, measured)` — where the declared order is contradicted.
  * `confirm(panel, candidate)` — the replacement gate, with contamination and
    delivery failures reported, never folded into the ratio.
  * `efficiency(rows)` — seconds per decision under batching: a slower call can
    still be a faster decision.
  * `amortize(acquisition_s, gain_per_task_s, tasks)` — the break-even count.

Pure: measurements in, decisions out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-execution-policy/1"
Z90 = 1.2816          # one-sided 90% bound, normal approximation (stated, not a bootstrap)


def reversal(declared, measured):
    """A contradiction between the declared cost order and the measured one."""
    declared = {str(k): float(v) for k, v in (declared or {}).items()}
    cells = measured if isinstance(measured, dict) else {}
    rows = []
    for cell, values in cells.items():
        values = {str(k): float(v) for k, v in (values or {}).items()}
        plans = sorted(set(values) & set(declared))
        for i, a in enumerate(plans):
            for b in plans[i + 1:]:
                if values[a] == values[b] or declared[a] == declared[b]:
                    continue
                if (values[a] < values[b]) != (declared[a] < declared[b]):
                    rows.append({"cell": str(cell), "a": a, "b": b,
                                 "declared": [declared[a], declared[b]],
                                 "measured": [values[a], values[b]]})
    findings = []
    if not cells:
        findings.append({"kind": "no-measurement",
                         "why": "the description alone does not identify the order"})
    findings += [{"kind": "declared-order-reversed", "cell": r["cell"],
                  "pair": [r["a"], r["b"]]} for r in rows]
    unknown = sorted({p for values in cells.values() for p in (values or {})} - set(declared))
    for plan in unknown:
        findings.append({"kind": "unpriced-plan", "plan": str(plan)})
    return {"format": FORMAT, "identified": not rows and bool(cells),
            "cells": len(cells), "reversals": rows, "findings": findings,
            "why": ("the measured order agrees with the declared one"
                    if cells and not rows else
                    "firsthand execution decides the order; the description cannot")}


def confirm(panel, candidate=None, margin=0.005, z=Z90, min_pairs=2):
    """Replace the incumbent only when a separate frozen panel says so."""
    candidate = candidate if isinstance(candidate, dict) else {}
    findings, complete, failures = [], [], {"candidate": 0, "incumbent": 0}
    for row in panel or ():
        if not isinstance(row, dict):
            continue
        cand_s, inc_s = row.get("candidate_s"), row.get("incumbent_s")
        if row.get("candidate_ok") is False or row.get("incumbent_ok") is False:
            if row.get("candidate_ok") is False:
                failures["candidate"] += 1
            if row.get("incumbent_ok") is False:
                failures["incumbent"] += 1
            continue
        try:
            cand_s, inc_s = float(cand_s), float(inc_s)
        except (TypeError, ValueError):
            continue
        if cand_s <= 0 or inc_s <= 0:
            continue
        complete.append((str(row.get("cell") or ""), cand_s, inc_s))
    if any(failures.values()):
        findings.append({"kind": "delivery-failure", **failures,
                         "why": "a failed delivery is counted, never priced as latency"})
    if not candidate.get("frozen_at"):
        findings.append({"kind": "unfrozen-candidate",
                         "why": "a candidate measured after the panel was revealed is not a fair test"})
    selected = {str(c) for c in (candidate.get("selected_cells") or [])}
    overlap = sorted({cell for cell, _c, _i in complete} & selected)
    if overlap:
        findings.append({"kind": "contaminated-panel", "cells": overlap,
                         "why": "cells used to choose the candidate cannot also confirm it"})
    if len(complete) < min_pairs:
        findings.append({"kind": "no-panel",
                         "why": "fewer than %d complete pairs" % min_pairs})
        return {"format": FORMAT, "decision": "retain", "ratio": None,
                "upper": None, "pairs": len(complete), "findings": findings,
                "why": "no fresh evidence, no replacement"}
    logs = [math.log(c / i) for _cell, c, i in complete]
    mean = sum(logs) / len(logs)
    var = sum((x - mean) ** 2 for x in logs) / max(1, len(logs) - 1)
    se = math.sqrt(var / len(logs))
    ratio, upper = math.exp(mean), math.exp(mean + z * se)
    contaminated = bool(overlap or not candidate.get("frozen_at"))
    ok = ratio <= 1 - margin and upper < 1.0 and not contaminated
    if not ok and not contaminated:
        findings.append({"kind": "not-separated", "ratio": round(ratio, 4),
                         "upper": round(upper, 4),
                         "why": "the bound still admits 'no better than the incumbent'"})
    return {"format": FORMAT, "decision": "replace" if ok else "retain",
            "ratio": round(ratio, 4), "upper": round(upper, 4),
            "pairs": len(complete), "findings": findings,
            "why": ("the frozen panel beats the incumbent beyond the margin"
                    if ok else "only a separate frozen panel may authorize replacement")}


def efficiency(rows):
    """Seconds per decision: batching can make a slower call the faster decision."""
    out = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        try:
            call_s, batch = float(row.get("call_s")), float(row.get("batch") or 1.0)
        except (TypeError, ValueError):
            continue
        if call_s <= 0 or batch <= 0:
            continue
        out.append({"label": str(row.get("label") or ""), "batch": batch,
                    "call_s": call_s, "per_decision_s": round(call_s / batch, 4)})
    findings = []
    for prev, cur in zip(out, out[1:]):
        if cur["call_s"] > prev["call_s"] and cur["per_decision_s"] < prev["per_decision_s"]:
            findings.append({"kind": "slower-call-faster-decision",
                             "from": prev["label"], "to": cur["label"],
                             "call": [prev["call_s"], cur["call_s"]],
                             "per_decision": [prev["per_decision_s"], cur["per_decision_s"]]})
    return {"format": FORMAT, "rows": out, "findings": findings,
            "why": "a call that got slower per request can still be faster per decision"}


def amortize(acquisition_s, gain_per_task_s, tasks=None):
    """A gain that never pays back the cost of finding it is not an improvement."""
    try:
        acquisition_s, gain = float(acquisition_s), float(gain_per_task_s)
    except (TypeError, ValueError):
        return {"format": FORMAT, "break_even": None,
                "findings": [{"kind": "bad-input"}], "why": "not a cost"}
    findings = []
    if gain <= 0:
        return {"format": FORMAT, "break_even": None,
                "findings": [{"kind": "no-gain", "gain": gain}],
                "why": "without a per-task gain the acquisition never pays back"}
    break_even = int(math.ceil(acquisition_s / gain))
    net = None
    if tasks is not None:
        net = round(float(tasks) * gain - acquisition_s, 4)
        if float(tasks) < break_even:
            findings.append({"kind": "unamortized",
                             "tasks": tasks, "break_even": break_even})
    return {"format": FORMAT, "break_even": break_even, "net_s": net,
            "findings": findings,
            "why": "the policy must survive its own acquisition cost at the deployment horizon"}
