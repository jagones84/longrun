#!/usr/bin/env python3
"""History truth — a clean record over a dirty world is worse than no edit.

Source: arXiv:2611.14654, "Cleaning an Agent's History Hurts When the World
Still Holds the Error" (round 129). A system that compacts, repairs or hands
off an agent's history decides what the record SAYS about the agent's mistakes
while their effects stay in the world. The paper separates the two halves and
finds the sign of the effect flips with the world:

  * At a FIXED WORLD, the same correct value raises recovery as a truthful note
    beside the preserved error (+15.20 pp over a matched neutral note) and
    LOWERS it as the agent's own completed action (-6.43 pp against the
    unedited record). The gap D = (T - N) - (F - O) is +21.63 pp (§5.1).
  * The presence of the answer does not predict the sign: a copying account
    predicts the falsified record would come out AHEAD, and it comes out
    6.43 pp BEHIND (§5.2). Disclosure and assertion come apart.
  * At a FIXED RECORD, a success receipt lowers whole-task success by 16.92 pp
    while the step's effect is ABSENT and raises it by 10.38 pp once the effect
    is PRESENT; the interaction is +27.31 pp, positive in six of eight receivers
    at 97.5% and seven of eight at 95% (§5.4, §5.5).
  * The matched neutral append is not automatically inert: unresolved on
    AgentCE-Bench, but +6.67 pp for one AppWorld receiver (§5.1, §5.6).
  * The consequence for a harness: a compaction, repair or handoff policy has
    to be judged AGAINST THE WORLD. A record made to look clean while the world
    still holds the error left agents worse off than no edit at all.

What this module does NOT claim: the paper chooses the state, the error and the
edit, so it does NOT estimate how often records and worlds disagree in use, and
it does not bound an adversary. Nothing here reproduces a paper number.

Pure: arm means, cell means and policy facts in, findings out.
"""
from __future__ import annotations

FORMAT = "longrun-history-truth/1"

# The four arms of the fixed-world design (§3, §4.2).
ARMS = ("original", "falsified", "truthful", "neutral")

# The two factors of the crossed design (§3, §4.3).
RECORDS = ("success", "failure")
WORLDS = ("absent", "present")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def agreement(record, world):
    """Does the record agree with the world it describes?

    `record` — {"receipt": "success"|"failure"}
    `world`  — {"effect": "present"|"absent"}
    """
    rec = record if isinstance(record, dict) else {}
    wld = world if isinstance(world, dict) else {}
    receipt = str(rec.get("receipt") or "").lower()
    effect = str(wld.get("effect") or "").lower()
    findings = []
    if receipt not in RECORDS:
        findings.append({"kind": "receipt-unknown",
                         "why": "the record states no success or failure"})
        return {"format": FORMAT, "agreement": "unknown", "findings": findings,
                "why": "without a stated receipt the record cannot be compared "
                       "with the world"}
    if effect not in WORLDS:
        findings.append({"kind": "effect-unknown",
                         "why": "the world state of the step is unknown"})
        return {"format": FORMAT, "agreement": "unknown", "findings": findings,
                "why": "without a known world state the comparison cannot be made"}
    truth = (receipt == "success") == (effect == "present")
    if truth:
        return {"format": FORMAT, "agreement": "consistent", "findings": [],
                "receipt": receipt, "effect": effect,
                "why": "exactly one receipt can be true in each world; here it is"}
    findings.append({"kind": "record-world-disagreement",
                     "receipt": receipt, "effect": effect,
                     "why": "the record asserts something the world does not hold"})
    return {"format": FORMAT, "agreement": "disagreeing", "findings": findings,
            "receipt": receipt, "effect": effect,
            "why": "the record and the world tell different stories about the "
                   "same step"}


def disclosure_vs_assertion(record):
    """Separate what a record DISCLOSES from what it ASSERTS (§3).

    `record` — {"discloses": <value or None>, "asserts": "done"|"pending"|None,
                 "author": "agent"|"user"|"third-party"}
    """
    rec = record if isinstance(record, dict) else {}
    discloses = rec.get("discloses")
    asserts = rec.get("asserts")
    author = rec.get("author")
    findings = []
    if discloses is not None and asserts is not None:
        findings.append({"kind": "disclosure-and-assertion-coupled",
                         "why": "this record both shows a value and claims an "
                                "outcome; the two are read apart only when the "
                                "arm keeps them separate"})
    if author == "agent" and asserts == "done":
        findings.append({"kind": "agent-asserts-completion",
                         "why": "the agent's own completed action is the form "
                                "that measured worse than the unedited record"})
    return {"format": FORMAT, "discloses": discloses, "asserts": asserts,
            "author": author, "findings": findings,
            "why": "revealing and asserting come apart; only the assertion "
                   "carries the record's account of the world"}


def effect(arms):
    """The fixed-world contrast: D = (T - N) - (F - O) (§5.1).

    `arms` — {"original": m, "falsified": m, "truthful": m, "neutral": m}
    where each m is a mean endpoint (a rate on the same scale for all arms).
    """
    values = arms if isinstance(arms, dict) else {}
    means = {}
    for name in ARMS:
        means[name] = _num(values.get(name))
    missing = [name for name in ARMS if means[name] is None]
    if missing:
        return {"format": FORMAT, "d": None, "findings": [],
                "why": "the four arms must all be present; missing: "
                       + ", ".join(missing)}
    t_minus_n = round(means["truthful"] - means["neutral"], 6)
    f_minus_o = round(means["falsified"] - means["original"], 6)
    d = round(t_minus_n - f_minus_o, 6)
    findings = []
    if t_minus_n > 0:
        findings.append({"kind": "truthful-note-helps",
                         "delta": t_minus_n,
                         "why": "the truthful note beside the preserved error "
                                "raises the endpoint over a matched neutral note"})
    if f_minus_o < 0:
        findings.append({"kind": "falsified-record-hurts",
                         "delta": f_minus_o,
                         "why": "the same value recorded as the agent's own "
                                "completed action lowers the endpoint against "
                                "the unedited record"})
    if t_minus_n > 0 and f_minus_o < 0:
        findings.append({"kind": "sign-reversal",
                         "why": "the same correct value helps in one form and "
                                "hurts in the other; the presence of the answer "
                                "does not predict the sign"})
    neutral = round(means["neutral"] - means["original"], 6)
    findings.append({"kind": "append-effect-is-separate",
                     "delta": neutral,
                     "why": "the matched neutral append has its own effect and "
                            "is not automatically inert"})
    return {"format": FORMAT, "d": d, "t_minus_n": t_minus_n,
            "f_minus_o": f_minus_o, "neutral_minus_original": neutral,
            "means": means, "findings": findings,
            "why": "a difference of contrasts: each edit is compared against "
                   "its own control, not against the other edit"}


def interaction(cells):
    """The crossed design: I = (succ_post - fail_post) - (succ_pre - fail_pre) (§5.4).

    `cells` — {"success_present": m, "success_absent": m,
                "failure_present": m, "failure_absent": m}
    """
    values = cells if isinstance(cells, dict) else {}
    sp = _num(values.get("success_present"))
    sa = _num(values.get("success_absent"))
    fp = _num(values.get("failure_present"))
    fa = _num(values.get("failure_absent"))
    if None in (sp, sa, fp, fa):
        return {"format": FORMAT, "interaction": None, "findings": [],
                "why": "all four cells are needed for the interaction"}
    effect_present = round(sp - fp, 6)
    effect_absent = round(sa - fa, 6)
    inter = round(effect_present - effect_absent, 6)
    agree = round(abs(sp - fa), 6)
    findings = []
    if effect_present > 0 > effect_absent or effect_absent > 0 > effect_present:
        findings.append({"kind": "sign-reversal-with-the-world",
                         "why": "the record's effect changes sign with the "
                                "world it describes"})
    findings.append({"kind": "agreeing-cells-are-close",
                     "delta": agree,
                     "why": "where the record and the world agree the two "
                            "receipts differ little; the interaction lives in "
                            "the disagreement"})
    return {"format": FORMAT, "interaction": inter,
            "effect_when_present": effect_present,
            "effect_when_absent": effect_absent,
            "agreeing_cell_gap": agree, "findings": findings,
            "why": "how far a success receipt's advantage depends on the world"}


def recheck(runs):
    """The re-issue diagnostic: does the receiver track the world?

    `runs` — [{"receipt": "success"|"failure", "effect": "present"|"absent",
                "reissued": 0|1}]
    """
    rows = [r for r in (runs or []) if isinstance(r, dict)]
    buckets = {}
    for row in rows:
        receipt = str(row.get("receipt") or "?").lower()
        effect = str(row.get("effect") or "?").lower()
        key = (receipt, effect)
        bucket = buckets.setdefault(key, {"n": 0, "reissued": 0})
        bucket["n"] += 1
        if row.get("reissued"):
            bucket["reissued"] += 1
    table = {}
    for (receipt, effect), bucket in sorted(buckets.items()):
        table[f"{receipt}/{effect}"] = {
            "n": bucket["n"],
            "reissue_rate": round(bucket["reissued"] / bucket["n"], 4)
            if bucket["n"] else None,
        }
    findings = []
    succ_present = table.get("success/present")
    succ_absent = table.get("success/absent")
    if succ_present and succ_absent and succ_present["reissue_rate"] is not None \
            and succ_absent["reissue_rate"] is not None:
        findings.append({"kind": "reissue-tracks-the-world",
                         "delta": round(succ_absent["reissue_rate"]
                                        - succ_present["reissue_rate"], 4),
                         "why": "a success receipt stops the re-issue once the "
                                "effect is actually there; the re-issue rate is "
                                "a diagnostic, not a mediation estimate"})
    fail_present = table.get("failure/present")
    if fail_present and fail_present["reissue_rate"] is not None \
            and fail_present["reissue_rate"] > 0.5:
        findings.append({"kind": "false-failure-receipt-duplicates-work",
                         "rate": fail_present["reissue_rate"],
                         "why": "a receipt that denies an effect the world "
                                "holds drives the receiver to write the work "
                                "again"})
    return {"format": FORMAT, "cells": table, "n": len(rows),
            "findings": findings,
            "why": "whether the receiver re-checks the world is visible in "
                   "what it does next"}


def advise(policy):
    """What a compaction, repair or handoff policy may claim.

    `policy` — {"kind": "compaction"|"repair"|"handoff",
                "edits_history": bool, "asserts_completion": bool,
                "world_repaired": bool, "verified_value": bool}
    """
    pol = policy if isinstance(policy, dict) else {}
    kind = str(pol.get("kind") or "compaction").lower()
    findings = []
    if pol.get("asserts_completion") and not pol.get("world_repaired"):
        findings.append({"kind": "clean-record-over-dirty-world",
                         "why": "the record claims a step is done while the "
                                "world still holds the error; that form "
                                "measured WORSE than no edit at all"})
    if pol.get("edits_history") and not pol.get("verified_value") \
            and not pol.get("world_repaired"):
        findings.append({"kind": "unverified-value-in-record",
                         "why": "a deployed history manager may lack a verified "
                                "correct value; the matched neutral note is the "
                                "control that separates content from append"})
    if kind in ("compaction", "handoff") and not pol.get("world_repaired"):
        findings.append({"kind": "judge-the-policy-against-the-world",
                         "why": "a compaction or handoff policy has to be tested "
                                "at a restored state with the world intact, "
                                "not read from the record alone"})
    findings.append({"kind": "prevalence-unmeasured",
                     "why": "the study measures what an edit does once the "
                            "record and the world disagree; it does not "
                            "estimate how often they disagree in use"})
    findings.append({"kind": "adversary-not-bounded",
                     "why": "one flipped receipt and one appended note were "
                            "tested; nothing here bounds an adversary"})
    return {"format": FORMAT, "kind": kind,
            "recommendation": ("verify-the-world-before-cleaning"
                               if not pol.get("world_repaired")
                               else "clean-the-record-after-repair"),
            "findings": findings,
            "why": "the record is an account of the world, not the world; "
                   "the two must be compared before the account is edited"}
