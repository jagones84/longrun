#!/usr/bin/env python3
"""Evidence review — mentioning a figure is not checking it against the text.

Source: arXiv:2611.24353, "When Figures Disagree with Text" (round 147).
Benchmarks usually hand a model the figure, the claim, or the knowledge that a
conflict exists; the harder autonomous task supplies only the paper
(`visual_evidence_verification_2611.24353.txt:24`, `:107`, `:109`). Three steps
separate them: candidate discovery, element–claim alignment and contradiction
verification (`:101`, `:103`, `:105`).

  * **four nested outcomes** — omit, mention, concern, diagnose; the accepted
    rate is `S3 = P`, with `S1 = mention ∪ P` and `S2 = concern ∪ P`
    (`:212`, `:214`, `:216`).
  * **measured**: 60.6% of 1,445 open-ended reviews mention the flawed figure,
    while 3.3% diagnose it (`:30`, `:128`).
  * **naming the figure is the one aid that helps**: 4.3% → 20.4%, while a
    consistency instruction (+2.69 pp) and a model-chosen shortlist (+0.54 pp)
    do not (`:33`, `:132`, `:356`, `:474`).
  * **the rendered figure matters**: on the 20 image-only contradictions,
    text-only review diagnoses none and naming the figure reaches 15.8%
    (`:35`, `:414`).
  * **asserting a conflict is not diagnosing the documented one**: a
    reference-free panel rises 22.6% → 44.1% with the figure named while the
    rubric rises 4.3% → 20.4% (`:405`, `:1236`).
  * **the rubric is lenient**: a blind audit confirms 52.6% of its acceptances,
    so every rate is an upper bound (`:247`, `:246`).
  * **honest negatives**: one model supplies 37 of 47 diagnoses; the controlled
    arms have no human audit; the shortlist result bounds one rule (`:315`,
    `:532`).

  * `outcomes()` — the four outcomes and the three steps.
  * `rates(rows)` — S1, S2 and S3 from per-review flags.
  * `aided(rows)` — which single input change moves diagnosis.
  * `shortlist(row)` — recall, end-to-end gain and the share of the oracle gain.
  * `evidence_type(rows)` — figure-only against text-supported contradictions.
  * `assertion(rows)` — asserted conflict against accepted diagnosis.
  * `instrument(rows)` — primary rubric, replay and the human audit.
  * `near_miss(rows)` — wrong target, wrong relation, quote threshold.
  * `noise(row)` — an intervention against the byte-identical repeat band.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: review flags and arm rates in; nested rates and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-evidence-review/1"

OUTCOMES = ("omit", "mention", "concern", "diagnose")
STEPS = ("discover", "align", "verify")
DEFAULTS = {"aid_gain": 0.05, "selection_share": 0.25,
            "assertion_gap": 0.15, "precision_floor": 0.80}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def outcomes():
    """The four nested outcomes and the three steps they fail to separate."""
    return {"format": FORMAT, "outcomes": list(OUTCOMES),
            "steps": list(STEPS),
            "nested": {"S1": "mention or diagnose", "S2": "concern or diagnose",
                       "S3": "diagnose"},
            "verdict": "outcomes-defined"}


def rates(rows):
    """Counts and the three nested rates from per-review flags."""
    counts = {name: 0 for name in OUTCOMES}
    for row in rows or []:
        r = row or {}
        mention = r.get("mention") is True
        concern = r.get("concern") is True
        diagnose = r.get("diagnose") is True
        if diagnose:
            counts["diagnose"] += 1
        elif concern:
            counts["concern"] += 1
        elif mention:
            counts["mention"] += 1
        else:
            counts["omit"] += 1
    n = sum(counts.values())
    if not n:
        return {"format": FORMAT, "verdict": "no-reviews"}
    s3 = counts["diagnose"] / n
    s2 = (counts["concern"] + counts["diagnose"]) / n
    s1 = ((counts["mention"] + counts["concern"] + counts["diagnose"]) / n)
    return {"format": FORMAT, "reviews": n, "counts": counts,
            "S1": s1, "S2": s2, "S3": s3,
            "nested_ok": s3 <= s2 <= s1,
            "verdict": "nested-rates-measured"}


def aided(rows):
    """One input change at a time against an unprompted baseline."""
    arms = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("arm") or "")
        value = _num(r.get("rate"))
        if name and value is not None:
            arms[name] = value
    if "unprompted" not in arms:
        return {"format": FORMAT, "verdict": "no-baseline"}
    base = arms["unprompted"]
    deltas = {name: value - base for name, value in arms.items()
              if name != "unprompted"}
    if not deltas:
        return {"format": FORMAT, "verdict": "no-arms"}
    decisive = max(deltas, key=lambda k: (deltas[k], k))
    return {"format": FORMAT, "arms": arms, "deltas": deltas,
            "decisive": decisive, "decisive_delta": deltas[decisive],
            "verdict": "aid-helps" if deltas[decisive] >= DEFAULTS["aid_gain"]
            else "aid-inert"}


def shortlist(row):
    """Does the model's own shortlist recover the naming gain?"""
    r = row or {}
    end = _num(r.get("end_to_end"))
    unprompted = _num(r.get("unprompted"))
    named = _num(r.get("named"))
    recall3 = _num(r.get("recall_at_3"))
    recall5 = _num(r.get("recall_at_5"))
    if None in (end, unprompted, named):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    gain = end - unprompted
    oracle = named - unprompted
    share = (gain / oracle) if oracle else None
    verdict = ("selection-limit" if (share is None or share < DEFAULTS["selection_share"])
               else "selection-workable")
    return {"format": FORMAT, "gain": gain, "oracle_gain": oracle,
            "share_recovered": share, "recall_at_3": recall3,
            "recall_at_5": recall5, "verdict": verdict}


def evidence_type(rows):
    """Where the contradiction lives decides whether pixels are required."""
    groups = {}
    for row in rows or []:
        r = row or {}
        group = str(r.get("evidence") or "")
        arm = str(r.get("arm") or "")
        value = _num(r.get("rate"))
        if group and arm and value is not None:
            groups.setdefault(group, {})[arm] = value
    figure = groups.get("figure_only") or {}
    text = groups.get("also_text") or {}
    pixels_required = (figure.get("text_only") == 0.0
                       and (figure.get("named") or 0.0) > 0.0)
    return {"format": FORMAT, "groups": groups,
            "verdict": "pixels-required" if pixels_required
            else "text-can-carry" if groups else "no-measurements"}


def assertion(rows):
    """An asserted conflict against a rubric-accepted diagnosis."""
    arms = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("arm") or "")
        rubric = _num(r.get("rubric"))
        panel = _num(r.get("panel"))
        if name and rubric is not None and panel is not None:
            arms[name] = {"rubric": rubric, "panel": panel}
    base = arms.get("unprompted")
    if not base:
        return {"format": FORMAT, "verdict": "no-baseline"}
    out, gap = {}, 0.0
    for name, values in arms.items():
        if name == "unprompted":
            continue
        rubric_delta = values["rubric"] - base["rubric"]
        panel_delta = values["panel"] - base["panel"]
        out[name] = {"rubric_delta": rubric_delta, "panel_delta": panel_delta}
        gap = max(gap, panel_delta - rubric_delta)
    return {"format": FORMAT, "arms": out, "max_gap": gap,
            "verdict": "assertion-not-diagnosis" if gap >= DEFAULTS["assertion_gap"]
            else "assertion-tracks-diagnosis"}


def instrument(row):
    """Primary rubric, independent replay and the blind human audit."""
    r = row or {}
    primary = _num(r.get("primary"))
    replay = _num(r.get("replay"))
    precision = _num(r.get("human_precision"))
    recall = _num(r.get("human_recall"))
    if primary is None:
        return {"format": FORMAT, "verdict": "no-primary-rate"}
    lenient = precision is not None and precision < DEFAULTS["precision_floor"]
    upper = (primary * precision) if (precision is not None) else None
    return {"format": FORMAT, "primary": primary, "replay": replay,
            "precision": precision, "recall": recall,
            "human_confirmed_upper_bound": upper,
            "verdict": "rubric-lenient" if lenient else "rubric-supported"}


def near_miss(rows):
    """Why a near-miss fails: the wrong target, the wrong relation, the quote."""
    counts = {"wrong_target": 0, "wrong_relation": 0, "quote": 0}
    for row in rows or []:
        r = row or {}
        label = str(r.get("label") or "")
        if label in counts:
            counts[label] += int(r.get("count") or 0)
    total = sum(counts.values())
    if not total:
        return {"format": FORMAT, "verdict": "no-near-misses"}
    shares = {name: value / total for name, value in counts.items()}
    dominant = max(shares, key=lambda k: (shares[k], k))
    return {"format": FORMAT, "counts": counts, "shares": shares,
            "verdict": ("wrong-target-dominates" if dominant == "wrong_target"
                        else "wrong-relation-dominates" if dominant == "wrong_relation"
                        else "quote-threshold-dominates")}


def noise(row):
    """An intervention shift judged against the byte-identical repeat band."""
    r = row or {}
    repeat = _num(r.get("repeat_band_s3"))
    delta = _num(r.get("delta_s3"))
    if repeat is None or delta is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "repeat_band": abs(repeat), "delta": delta,
            "verdict": "within-noise" if abs(delta) <= abs(repeat) else "beyond-noise"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("mentions_as_verification") is True:
        findings.append({"kind": "mentions-as-verification",
                         "why": "a review can discuss a figure without checking it"})
    if r.get("guided_as_autonomous") is True:
        findings.append({"kind": "guided-as-autonomous",
                         "why": "a named figure is the one input a deployed reviewer lacks"})
    if r.get("single_judge") is True:
        findings.append({"kind": "single-judge",
                         "why": "a lenient rubric needs a replay and a human check"})
    if r.get("no_repeat_band") is True:
        findings.append({"kind": "no-repeat-band",
                         "why": "an intervention smaller than run-to-run noise is not a gain"})
    if r.get("text_only_extrapolation") is True:
        findings.append({"kind": "text-only-extrapolation",
                         "why": "figure-only contradictions need the rendered pixels"})
    if r.get("aggregate_only") is True:
        findings.append({"kind": "aggregate-only",
                         "why": "one model can supply most of the acceptances"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("reveals_the_target", "names_the_figure",
         "naming the target turns search into verification"),
        ("scores_the_specific_claim", "scores_review_quality",
         "a fluent review is not evidence that a source was checked"),
        ("keeps_the_rendered_source", "reads_text_only",
         "some contradictions exist only in the pixels"),
        ("reports_by_evidence_type", "one_aggregate_rate",
         "figure-only and text-supported cases differ"),
        ("separates_assertion_from_diagnosis", "counts_any_concern",
         "asserting a conflict is not diagnosing the documented one"),
        ("validates_the_rubric", "trusts_the_judge",
         "a lenient judge overstates the detection rate"),
        ("measures_the_repeat_band", "compares_raw_deltas",
         "an intervention inside the noise is not a result"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
