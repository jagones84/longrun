#!/usr/bin/env python3
"""Model budget — delegation and budgeted routing economics for a two-model harness.

Sources (read 2026-11-26, round 173), one subject: *cost-efficient model choice
inside an agent harness*.

  * **Delegent** — arXiv:2611.33098. The frontier model stays in charge and hands
    focused legwork (investigating code, running tests, searching a corpus) to a
    small model; no router is trained (`delegent_slm_delegation_2611.33098.txt:22`,
    `:36`). Frontier cost falls 67% on coding and 59% on search with a 27B SLM, 66%
    with a 2B, with no loss in task performance (`:41`, `:45`); a short instruction
    that keeps the main coding task on the frontier accounts for most of the saving
    and keeps a 2B from losing tasks (`:445`); on tasks needing under ~25 calls
    delegation brings little (`:266`).
  * **ARoute** — arXiv:2611.13209. A *task-aligned* router chooses the model before
    generation under a user cost budget (`:34`, `:45`); the useful signal is the
    only-strong-correct outcome, `a_w = +1` when only the strong model is right and
    `-1` when it replaces a correct weak answer (`:228`); the budget buys upgrades,
    so the batch routes the greatest expected benefit first (`:383`); the streaming
    variant calibrates a threshold on a small validation set and carries a
    finite-sample guarantee on expected **normalized spending** (`:48`, `:485`).
  * **Route Anything** — arXiv:2611.05275. Per-input oracle routing beats the best
    fixed candidate by 5.4 points, and a learned router captures only a small share
    of that gap (`:39`, `:440`); routing raises efficiency 8.82x on average at a
    quality loss below 0.5 points (`:74`, `:169`) — a routing claim is bounded by the
    oracle gap it captures (`:193`).

  * `classify(task)` — which model runs one task class (Delegent's instruction).
  * `delegation_gain(legwork_share, slm_ratio)` — the cost fraction removed.
  * `worthwhile(calls, legwork_share, slm_ratio)` — Delegent's short-task caveat.
  * `osc(pairs)` — the only-strong-correct rate over paired outcomes (ARoute).
  * `plan(records, budget)` — route the greatest expected benefit first (ARoute-Batch).
  * `certified(spend, quota, margin)` — a spend that a point estimate cannot certify.
  * `oracle_gap(fixed, oracle)` / `capture(router, fixed, oracle)` — the ceiling and
    the share of it a router took (Route Anything).
  * `efficiency(saving, quality_delta)` — the cost multiple at a quality floor.
  * `audit(record)` — every claim the three papers would refuse.
  * `advise(profile)` — map a harness profile onto the papers' failure modes.

Pure: numbers and recorded claims in; verdicts out. It never calls a model and it
never reads a price list. Related but DIFFERENT: `model_handoff` routes each STEP
(local/verify/cloud escalation, arXiv:2610.07816); this module prices the WORK
(which class goes to which model, and what a routing claim is worth).
"""
from __future__ import annotations

FORMAT = "longrun-model-budget/1"

LEGWORK = ("code_investigate", "run_tests", "corpus_search")
LEAD_WORK = ("main_code", "plan", "answer")
TASK_CLASSES = LEGWORK + LEAD_WORK
SHORT_TASK_CALLS = 25          # Delegent: below ~25 calls delegation brings little
GAIN_FLOOR = 0.02              # a saving under 2% does not pay for the harness edit
QUALITY_FLOOR = 0.5            # Route Anything: admissible at a loss below 0.5 points
UNITS = ("fraction", "dollars")


def _stamp(rec):
    rec.setdefault("format", FORMAT)
    return rec


def classify(task, lead_owns_main=True):
    """Which model runs one task class, and why (Delegent's short instruction)."""
    task = str(task)
    if task not in TASK_CLASSES:
        return _stamp({"task": task, "model": "lead", "reason": "unknown-task-class"})
    if not lead_owns_main:
        return _stamp({"task": task, "model": "lead", "reason": "instruction-disabled"})
    if task in LEGWORK:
        return _stamp({"task": task, "model": "slm", "reason": "legwork-delegated"})
    return _stamp({"task": task, "model": "lead", "reason": "lead-keeps-main"})


def delegation_gain(legwork_share, slm_ratio):
    """Fraction of cost removed by sending `legwork_share` of the work to the SLM.

    `slm_ratio` is the SLM's price per token divided by the lead's (0 < r <= 1).
    """
    try:
        share = float(legwork_share)
        ratio = float(slm_ratio)
    except (TypeError, ValueError):
        return _stamp({"gain": 0.0, "reason": "not-a-number"})
    if not 0.0 <= share <= 1.0 or not 0.0 < ratio <= 1.0:
        return _stamp({"share": share, "ratio": ratio, "gain": 0.0,
                       "reason": "invalid-input"})
    return _stamp({"share": share, "ratio": ratio,
                   "gain": round(share * (1.0 - ratio), 6),
                   "reason": "ok"})


def worthwhile(calls, legwork_share, slm_ratio, floor=GAIN_FLOOR):
    """Whether delegating this task class pays, on Delegent's own terms."""
    gain = delegation_gain(legwork_share, slm_ratio)
    if gain.get("reason") != "ok":
        return _stamp({"worthwhile": False, "gain": 0.0, "reason": gain["reason"]})
    if int(calls) < SHORT_TASK_CALLS:
        return _stamp({"worthwhile": False, "gain": gain["gain"], "reason": "short-task"})
    if gain["gain"] < floor:
        return _stamp({"worthwhile": False, "gain": gain["gain"],
                       "reason": "gain-below-floor"})
    return _stamp({"worthwhile": True, "gain": gain["gain"], "reason": "worthwhile"})


def osc(pairs):
    """Only-strong-correct rate over paired outcomes `[(weak_ok, strong_ok), ...]`.

    ARoute's `a_w` is +1 for only-strong-correct and -1 when the strong model
    replaces a correct weak answer; both extremes are counted so a router that
    upgrades too much is visible, not only one that upgrades too little.
    """
    rows = [(bool(w), bool(s)) for w, s in pairs]
    n = len(rows)
    if n == 0:
        return _stamp({"n": 0, "osc": 0.0, "replace": 0.0, "reason": "no-records"})
    only_strong = sum(1 for w, s in rows if s and not w)
    replace = sum(1 for w, s in rows if w and not s)
    return _stamp({"n": n, "osc": round(only_strong / n, 6),
                   "replace": round(replace / n, 6), "reason": "ok"})


def plan(records, budget):
    """ARoute-Batch: route the greatest expected benefit first, within `budget`.

    Each record is `{id, benefit, cost}` in ONE unit; `benefit` is `a_w` in
    {-1, 0, 1} and `cost` is the cost of the upgrade. Returns the chosen ids, the
    net benefit and the spend — a negative-benefit upgrade is never taken.
    """
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        return _stamp({"chosen": [], "net": 0.0, "spend": 0.0, "reason": "not-a-number"})
    rows = []
    for r in records or []:
        try:
            b, c = float(r["benefit"]), float(r["cost"])
        except (KeyError, TypeError, ValueError):
            return _stamp({"chosen": [], "net": 0.0, "spend": 0.0,
                           "reason": "malformed-record"})
        rows.append((str(r.get("id", "?")), b, c))
    rows.sort(key=lambda t: (-(t[1] / t[2] if t[2] > 0 else 0.0), t[0]))
    chosen, spend, net = [], 0.0, 0.0
    for rid, b, c in rows:
        if b <= 0 or spend + c > budget:
            continue
        chosen.append(rid)
        spend += c
        net += b
    return _stamp({"chosen": chosen, "net": round(net, 6), "spend": round(spend, 6),
                   "adheres": spend <= budget + 1e-9, "reason": "ok"})


def certified(spend, quota, margin):
    """Whether a spend claim is certified, not merely estimated (ARoute).

    A point estimate cannot certify: the guarantee is on the EXPECTED normalized
    spending, so certification needs a positive margin that still fits the quota.
    """
    try:
        spend, quota, margin = float(spend), float(quota), float(margin)
    except (TypeError, ValueError):
        return _stamp({"certified": False, "reason": "not-a-number"})
    if margin <= 0.0:
        return _stamp({"spend": spend, "quota": quota, "margin": margin,
                       "adheres": spend <= quota + 1e-9, "certified": False,
                       "reason": "no-margin"})
    return _stamp({"spend": spend, "quota": quota, "margin": margin,
                   "adheres": spend <= quota + 1e-9,
                   "certified": round(spend + margin, 9) <= quota + 1e-9,
                   "headroom": round(quota - spend, 9), "reason": "ok"})


def oracle_gap(fixed_scores, oracle_scores):
    """Mean(per-input oracle − best fixed candidate) over benchmarks."""
    fs, os_ = list(fixed_scores or []), list(oracle_scores or [])
    if not fs or len(fs) != len(os_):
        return _stamp({"gap": 0.0, "reason": "mismatched-scores"})
    diffs = [float(o) - float(f) for f, o in zip(fs, os_)]
    return _stamp({"gap": round(sum(diffs) / len(diffs), 6), "n": len(diffs),
                   "reason": "ok"})


def capture(router_scores, fixed_scores, oracle_scores):
    """Share of the oracle gap a router actually took (Route Anything)."""
    rs, fs, os_ = list(router_scores or []), list(fixed_scores or []), list(oracle_scores or [])
    if not rs or not (len(rs) == len(fs) == len(os_)):
        return _stamp({"capture": None, "reason": "mismatched-scores"})
    gained = sum(float(r) - float(f) for r, f in zip(rs, fs))
    room = sum(float(o) - float(f) for o, f in zip(os_, fs))
    if room <= 1e-9:
        return _stamp({"capture": None, "gained": round(gained, 6),
                       "reason": "no-headroom"})
    return _stamp({"capture": round(gained / room, 6),
                   "gained": round(gained, 6), "headroom": round(room, 6),
                   "reason": "ok"})


def efficiency(saving, quality_delta, floor=QUALITY_FLOOR):
    """The cost multiple a saving buys, admissible only at the quality floor."""
    try:
        saving, quality_delta = float(saving), float(quality_delta)
    except (TypeError, ValueError):
        return _stamp({"efficiency": None, "reason": "not-a-number"})
    if not 0.0 <= saving < 1.0:
        return _stamp({"efficiency": None, "reason": "invalid-saving"})
    return _stamp({"efficiency": round(1.0 / (1.0 - saving), 4),
                   "quality_delta": quality_delta,
                   "admissible": quality_delta >= -floor, "reason": "ok"})


def record_from_arms(arms, costs=None, seeds=None, units="fraction"):
    """Turn a benchmark run's arms into the claim record `audit()` prices.

    `arms` is plain data: `{"weak": [bool,...], "strong": [bool,...], "router":
    [bool,...]}` — one element per task, the same tasks in the same order. `weak`
    is the baseline arm, `strong` is the all-strong arm (the oracle's per-task
    input), `router` is the arm whose claim is being priced (optional).
    `costs` mirrors those keys with per-task costs, in one unit; `seeds` is the
    number of independent seeds behind the vectors.

    The output feeds `audit()` directly, so a real run is priced instead of a
    hand-written record. Pure: booleans and numbers in, a record out.
    """
    a = arms or {}
    seeds = seeds if seeds is not None else a.get("seeds")
    costs = costs or a.get("costs")
    weak = [bool(x) for x in (a.get("weak") or [])]
    strong = [bool(x) for x in (a.get("strong") or [])]
    router = [bool(x) for x in a["router"]] if a.get("router") else None
    if not weak or len(weak) != len(strong):
        return _stamp({"reason": "mismatched-arms"})
    n = len(weak)
    fixed = [1.0 if x else 0.0 for x in weak]
    oracle = [1.0 if (w or s) else 0.0 for w, s in zip(weak, strong)]
    rec = {"units": units, "seeds": seeds,
           "delegation_calls": a.get("delegation_calls"),
           "delegated_tasks": a.get("delegated_tasks"),
           "osc": osc(list(zip(weak, strong)))["osc"],
           "oracle_gap": round(oracle_gap(fixed, oracle).get("gap", 0.0) * 100.0, 4)}
    if router is not None and len(router) == n:
        rs = [1.0 if x else 0.0 for x in router]
        rec["claimed_gain"] = round((sum(rs) - sum(fixed)) / n * 100.0, 4)
        rec["capture"] = capture(rs, fixed, oracle).get("capture")
        c = costs or {}
        strong_cost, router_cost = c.get("strong"), c.get("router")
        if strong_cost and router_cost and sum(strong_cost) > 0:
            rec["spend"] = round(sum(router_cost) / sum(strong_cost), 6)
    rec["quota"] = a.get("quota")
    rec["margin"] = a.get("margin")
    return _stamp(rec)


def audit(record):
    """The misreadings the three papers name, as findings over one claim record.

    `record` keys (all optional): `claimed_gain`, `oracle_gap`, `capture`,
    `seeds`, `units`, `delegation_calls`, `delegated_tasks`, `spend`, `quota`,
    `margin`, `certified`.
    """
    rec = record or {}
    findings = []

    def add(kind, detail):
        findings.append({"kind": kind, "detail": detail})

    units = rec.get("units")
    if units is not None and units not in UNITS:
        add("unit-mismatch", "units %r is neither of %s" % (units, list(UNITS)))

    gap = rec.get("oracle_gap")
    claimed = rec.get("claimed_gain")
    if claimed is not None and gap is None:
        add("capture-not-reported", "a routing gain is claimed with no oracle gap")
    if claimed is not None and gap is not None and float(claimed) > float(gap) + 1e-9:
        add("routing-beyond-oracle",
            "claimed %.4f exceeds the oracle gap %.4f" % (float(claimed), float(gap)))
    if claimed is not None and rec.get("capture") is None and gap is not None:
        add("capture-not-reported", "the share of the oracle gap captured is missing")
    if (claimed is not None or rec.get("capture") is not None) and int(rec.get("seeds") or 0) < 2:
        add("single-seed", "a gap/capture claim rests on fewer than two seeds")

    calls = rec.get("delegation_calls")
    if calls is not None and int(calls) < SHORT_TASK_CALLS:
        add("delegation-on-short-task",
            "%d calls is below Delegent's ~%d" % (int(calls), SHORT_TASK_CALLS))
    for task in rec.get("delegated_tasks") or []:
        if task not in LEGWORK:
            add("main-delegated", "%r is not legwork and must stay on the lead" % (task,))

    spend, quota = rec.get("spend"), rec.get("quota")
    if spend is not None and quota is not None and float(spend) > float(quota) + 1e-9:
        add("budget-overspend", "spend %.4f exceeds quota %.4f" % (float(spend), float(quota)))
    if rec.get("certified") and (rec.get("margin") is None or float(rec.get("margin")) <= 0.0):
        add("uncertified-spend", "a spend cannot be certified without a positive margin")

    return _stamp({"verdict": "findings" if findings else "clean",
                   "findings": findings, "n": len(findings)})


def advise(profile):
    """Map a harness profile onto the papers' failure modes (strings, ordered)."""
    p = profile or {}
    out = []
    if p.get("routing_claim") and p.get("oracle_gap") is None:
        out.append("measure the per-input oracle gap before claiming a routing win")
    if p.get("routing_claim") and p.get("capture") is None:
        out.append("report the share of the oracle gap the router captured")
    if p.get("delegation") and "main_code" in (p.get("delegated_tasks") or []):
        out.append("keep main_code on the lead; delegate only legwork")
    if p.get("delegation") and int(p.get("delegation_calls") or 0) < SHORT_TASK_CALLS:
        out.append("do not delegate on tasks under ~%d calls" % SHORT_TASK_CALLS)
    if p.get("budget") is not None and not p.get("margin"):
        out.append("a point estimate does not certify spend; carry a margin")
    if not out:
        out.append("no misreading found in this profile")
    return _stamp({"advice": out, "n": len(out)})
