#!/usr/bin/env python3
"""Admission is a decision, and it belongs outside the reasoner that answers.

Source: arXiv:2611.22169, "Not All Evidence Is Admissible: Evidence Governance
for Tool-Augmented Medical Agents" (round 131). A tool-augmented agent treats
whatever its tools return as evidence, and that default is costly: the tools
fail silently, and a frozen reasoner cannot look away from what enters its
context, so cases it would have answered correctly are FLIPPED to wrong once the
tool outputs are added. The paper calls this evidence hijacking and traces it to
a lost property: V-information is guaranteed non-negative only for a predictor
that may ignore any side input, and a frozen reasoner cannot.

Three harness-relevant results follow:

  * the decision of what counts as evidence must be taken OUTSIDE the reasoner
    (a Checker that reads only the input and the cards, never the solver's
    hypothesis, its tentative answer, or the label), while the answer is still
    given by the reasoner from the admitted cards alone;
  * a tool output is a CARD: it states a finding and shows the material the
    finding rests on, so the finding can be checked against the input;
  * the right reference for an evidence filter is a BUDGET-MATCHED RANDOM gate,
    not "admit everything": the gain splits into a budget term (from letting the
    reasoner see less) and a selection term (from letting it see better), and
    only a gate that reads content obtains the latter.

This module is the deterministic auditor over records a harness already
produces:

  * `admit(cards, context)` — rule on each card, from the input and the cards
    alone, and refuse to rule at all when the checker has seen the answer;
  * `gates(rows)` — the trivial gates, the budget term and the selection term,
    on per-case outcomes;
  * `first_order(rows)` — the covariance that predicts the selection term
    before the gate is run;
  * `advise(profile)` — the report a harness may publish about its own
    evidence handling.

Pure: cards and outcome rows in, findings out. No paper number is reproduced.
"""
from __future__ import annotations

FORMAT = "longrun-evidence-gate/1"

# What a card must carry for a ruling to be possible at all.
CARD_FIELDS = ("finding", "material")

# The gates every comparison must include.
TRIVIAL_GATES = ("none", "all")

# What a Checker is allowed to read.
CHECKER_INPUTS = ("input", "cards")


def _text(value):
    return str(value or "").strip()


def card(finding, material, source=None, case=None):
    """Write a tool output as a checkable card."""
    row = {"finding": _text(finding), "material": _text(material)}
    if source is not None:
        row["source"] = _text(source)
    if case is not None:
        row["case"] = case
    kinds = []
    if not row["finding"]:
        kinds.append("finding-missing")
    if not row["material"]:
        kinds.append("material-missing")
    row["complete"] = not kinds
    row["findings"] = [{"kind": k, "why": "a card states a finding and shows "
                                            "the material it rests on"} for k in kinds]
    return row


def admit(cards, context=None):
    """Rule on which cards may enter as evidence.

    `cards` — [{"finding": ..., "material": ..., "source": ...}]
    `context` — {"input": the case input, "checker_reads": [what the checker
                 saw], "quoted": bool (the material is a verbatim quote)}
    """
    ctx = context if isinstance(context, dict) else {}
    reads = [str(x).lower() for x in (ctx.get("checker_reads")
                                      or CHECKER_INPUTS)]
    findings = []
    if any(r not in CHECKER_INPUTS for r in reads):
        # Independence is the whole design: a checker conditioned on the
        # solver's hypothesis, its tentative answer or the label can only
        # confirm what the reasoner already leans towards.
        findings.append({"kind": "checker-not-independent", "reads": reads,
                         "why": "the ruling must not see the solver's context, "
                                "its hypothesis, its answer or the label; "
                                "conditioned on them it cannot correct them"})
        return {"format": FORMAT, "admitted": None, "rejected": [],
                "findings": findings,
                "why": "no ruling: the checker is inside the context it was "
                       "meant to govern"}
    rows = [c for c in (cards or []) if isinstance(c, dict)]
    if not rows:
        findings.append({"kind": "no-cards", "why": "an empty pool admits "
                                                    "nothing; that is the g0 gate, not a filter"})
        return {"format": FORMAT, "admitted": [], "rejected": [], "findings": findings,
                "why": "nothing to rule on"}
    input_text = _text(ctx.get("input"))
    quoted = bool(ctx.get("quoted", True))
    admitted, rejected = [], []
    for row in rows:
        item = card(row.get("finding"), row.get("material"), row.get("source"))
        reasons = []
        if not item["finding"]:
            reasons.append({"kind": "finding-missing",
                            "why": "a card with no finding cannot be checked"})
        if not item["material"]:
            reasons.append({"kind": "finding-without-material",
                            "why": "the finding shows nothing to check it "
                                   "against, so it is taken on trust"})
        elif quoted and input_text and item["material"] not in input_text:
            reasons.append({"kind": "material-not-in-input",
                            "why": "the quoted material does not appear in the "
                                   "input: the card is not verifiable against it"})
        if reasons:
            rejected.append({"card": item, "reasons": reasons})
        else:
            admitted.append(item)
    # Consistency: contradictions mark where to look, but the ruling rests on
    # fidelity to the input, because tools can also agree in error.
    by_key = {}
    for item in rows:
        key = _text(item.get("key") or item.get("finding")).lower()
        value = _text(item.get("value")).lower()
        if key and value:
            by_key.setdefault(key, set()).add(value)
    contested = sorted(k for k, vs in by_key.items() if len(vs) > 1)
    if contested:
        findings.append({"kind": "cards-contradict", "on": contested,
                         "why": "contradictions point at cases to inspect; they "
                                "are not proof that the agreeing cards are right"})
    if admitted and len(admitted) == len(rows):
        findings.append({"kind": "admitted-everything",
                         "why": "the checker admitted the whole pool; a filter "
                                "that never rejects is the g1 gate"})
    if not admitted:
        findings.append({"kind": "admitted-nothing",
                         "why": "the checker admitted no card; that is the g0 "
                                "gate, and it must beat admitting everything to "
                                "count as a filter"})
    return {"format": FORMAT, "admitted": admitted, "rejected": rejected,
            "contested": contested, "findings": findings,
            "why": "admission is decided from the input and the cards alone, "
                   "before the reasoner reads any of them"}


def gates(rows):
    """The budget term and the selection term, on per-case outcomes.

    `rows` — [{"case": id, "policy": "none"|"all"|"gate"|"random", "correct":
               bool, "admitted": int, "pool": int}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    per = {}
    for row in data:
        policy = _text(row.get("policy")).lower()
        if not policy:
            continue
        bucket = per.setdefault(policy, {"n": 0, "correct": 0, "admitted": 0})
        bucket["n"] += 1
        bucket["correct"] += 1 if row.get("correct") else 0
        bucket["admitted"] += int(row.get("admitted") or 0)
    rates = {p: round(v["correct"] / v["n"], 4) if v["n"] else None
             for p, v in per.items()}
    findings = []
    missing = [p for p in ("none", "all", "gate", "random") if p not in rates]
    for p in missing:
        findings.append({"kind": "gate-not-measured", "policy": p,
                         "why": "a filter is judged against admitting nothing, "
                                "admitting everything AND a budget-matched random "
                                "gate; a missing arm hides which gain it has"})
    all_r, gate_r, random_r = rates.get("all"), rates.get("gate"), rates.get("random")
    budget = selection = total = None
    if all_r is not None and random_r is not None:
        budget = round(random_r - all_r, 4)   # from seeing less
    if random_r is not None and gate_r is not None:
        selection = round(gate_r - random_r, 4)  # from seeing better
    if all_r is not None and gate_r is not None:
        total = round(gate_r - all_r, 4)
    if selection is not None:
        if selection > 0:
            findings.append({"kind": "selection-gain", "selection": selection,
                             "budget": budget,
                             "why": "at the same number of admitted cards the "
                                    "gate picks better evidence, not just less"})
        else:
            findings.append({"kind": "gain-is-only-budget", "selection": selection,
                             "budget": budget,
                             "why": "the gate does no better than admitting a "
                                    "random subset of the same size: whatever it "
                                    "gained came from seeing less"})
    admitted = per.get("gate", {}).get("admitted")
    n_gate = per.get("gate", {}).get("n")
    if admitted and n_gate and per.get("all", {}).get("admitted"):
        share = admitted / per["all"]["admitted"]
        if share > 0.9:
            findings.append({"kind": "admits-almost-everything",
                             "share": round(share, 4),
                             "why": "a gate that admits nearly the whole pool "
                                    "cannot be selecting; it is g1 with extra cost"})
    return {"format": FORMAT, "rates": rates, "budget_term": budget,
            "selection_term": selection, "total_gain": total,
            "findings": findings,
            "why": "report seeing-less and seeing-better separately, against a "
                   "budget-matched random gate"}


def first_order(rows):
    """Predict the selection term before running the gate.

    `rows` — [{"admitted": bool, "useful": +1|0|-1}] — one row per card, where
    `useful` is whether that card, presented alone, helps (+) or misleads (-) the
    reasoner. The selection term is positive exactly when admission decisions
    correlate positively with single-card usefulness.
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    if not data:
        return {"format": FORMAT, "covariance": None,
                "findings": [{"kind": "no-cards",
                              "why": "nothing to correlate"}],
                "why": "the first-order term needs the cards' own usefulness"}
    a = [1.0 if r.get("admitted") else 0.0 for r in data]
    v = [float(r.get("useful") or 0.0) for r in data]
    n = len(data)
    mean_a, mean_v = sum(a) / n, sum(v) / n
    cov = sum((x - mean_a) * (y - mean_v) for x, y in zip(a, v)) / n
    findings = []
    if cov > 0:
        findings.append({"kind": "selection-correlates-with-usefulness",
                         "covariance": round(cov, 6),
                         "why": "admitted cards are the ones that help; the "
                                "first-order prediction of a selection gain is "
                                "positive"})
    elif cov < 0:
        findings.append({"kind": "selection-anti-correlates",
                         "covariance": round(cov, 6),
                         "why": "the gate admits the cards that mislead; its "
                                "gain can only come from seeing less"})
    else:
        findings.append({"kind": "selection-independent-of-content",
                         "covariance": 0.0,
                         "why": "admission is uncorrelated with whether a card "
                                "helps: a content-agnostic gate"})
    return {"format": FORMAT, "n": n, "covariance": round(cov, 6),
            "findings": findings,
            "why": "a gate need not estimate each card's value; it needs to "
                   "rank the helpful ones above the misleading ones"}


def advise(profile):
    """What a harness may claim about its own evidence handling."""
    prof = profile if isinstance(profile, dict) else {}
    findings = []
    if not prof.get("checker_outside_context"):
        findings.append({"kind": "judgement-inside-the-context",
                         "why": "when the answering model judges its own tool "
                                "outputs, the wrong output has already entered "
                                "the context it is judging"})
    if not prof.get("cards_verifiable"):
        findings.append({"kind": "unverifiable-tool-output",
                         "why": "an output that does not show the material it "
                                "rests on cannot be checked against the input"})
    if not prof.get("budget_matched_control"):
        findings.append({"kind": "no-budget-matched-control",
                         "why": "without a random gate admitting the same number "
                                "of cards, a filtering gain cannot be told apart "
                                "from the gain of seeing less"})
    if prof.get("admit_all"):
        findings.append({"kind": "admits-every-tool-output",
                         "why": "admitting everything is a choice, and it is "
                                "the choice the paper measures as harmful"})
    findings.append({"kind": "tools-are-not-evidence-by-default",
                     "why": "a tool output is a claim, and a silent failure "
                            "looks exactly like a correct output"})
    return {"format": FORMAT, "findings": findings,
            "why": "a harness reports where the admission decision is taken, "
                   "because a decision takes inside the reasoner cannot undo itself"}
