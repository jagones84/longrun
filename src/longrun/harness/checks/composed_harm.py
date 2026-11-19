#!/usr/bin/env python3
"""Composed harm — a safe screen is not a safe task.

Source: arXiv:2611.22971, "SEAM: Computer-Use Agents Know the Harm Between
Screens, and Commit It Anyway" (round 130). The safety benchmarks a computer-use
agent is measured against put the harm in one place: a malicious instruction, a
planted command, a deceptive page, a hazardous object. An agent that checks the
task and each screen in isolation passes all of them. SEAM's harm is composed:
the instruction is legitimate, every page is truthful, no page carries two facts,
and the person at risk is a third party who never appears in the conversation.
The measured result is the harness-relevant one:

  * exposure is not the bottleneck — the decisive page was served in at least
    99.3% of required-path runs, and the harm still happened;
  * recognition does not reliably reach the action: asked about the same pages
    the models answer STOP on 90-97% of harmful tasks, yet they carry out
    18-51% of those harms, and 81-89% of them are ones they had answered STOP
    to; with reasoning they write the conflict down and confirm anyway;
  * the translation depends on the CHANNEL: the same sentence stops the agent
    in the user's instruction (1.1-22.0% harmful) far more often than read on a
    screen (7.4-58.3%), and the channel carries 76-111% of that gap while the
    speaker carries little.

So "the agent knows" is not a defence, and "the screen was checked" is not a
defence either. What a harness can do is refuse to commit while a composed
conflict is unresolved, and to keep the composed facts available at the moment
of commit — the paper's checkpoint fork shows an earlier screen's fact is
mostly no longer part of the judgment at commit time.

This module is the deterministic auditor over records the harness already
produces:

  * `compose(facts, binding)` — do the facts a task collected actually bind a
    person to a hazardous object, and by which reasoning operation?
  * `screen_check(screens)` — which screens carry how many facts, and is any
    single screen itself harmful (the guarantee SEAM verifies behaviourally)?
  * `recognition_vs_action(rows)` — the thought-action disconnect: the agent
    recognised the conflict and still committed.
  * `channel_effect(rows)` — the same hazard, delivered by different channels.
  * `commit_gate(state)` — what the harness may do at the moment of commit.
  * `advise(profile)` — the report a harness may publish about its own safety.

Pure: facts and run records in, findings out. No paper number is reproduced
here; the module carries the INVARIANTS, not the rates.
"""
from __future__ import annotations

FORMAT = "longrun-composed-harm/1"

# The eight reasoning operations SEAM's rules use (grouped in three tiers).
OPERATIONS = ("lookup", "quantity", "state-version")

TIERS = {
    "lookup": "lookup-binding",
    "quantity": "quantity",
    "state-version": "state-version",
}

# The four channels a fact can arrive through.
CHANNELS = ("instruction", "screen", "requester", "relayed")

# What a run can end with.
OUTCOMES = ("executes-silent", "executes-flagged", "stops", "remediates",
            "benign-done", "incomplete")


def _text(value):
    return str(value or "").strip().lower()


def compose(facts, binding=None):
    """Do the collected facts bind a person to a hazardous object?

    `facts` — [{"kind": "person"|"object", "value": ..., "source": "screen",
                "screen": "page-id"}, ...]
    `binding` — {"person": ..., "object": ..., "operation": "quantity",
                 "relation": {"above": 38, "value": 40}}

    Returns the composed conflict when the facts bind, or the reason they do
    not. The paper's guarantee is that NO screen carries two facts and no text
    names the conflict, so a composition here is the harness's own synthesis.
    """
    rows = [f for f in (facts or []) if isinstance(f, dict)]
    kinds = {_text(f.get("kind")) for f in rows}
    findings = []
    if "person" not in kinds:
        findings.append({"kind": "no-person-fact",
                         "why": "a conflict needs a fact about the person at risk"})
    if "object" not in kinds:
        findings.append({"kind": "no-object-fact",
                         "why": "a conflict needs a fact about the item"})
    b = binding if isinstance(binding, dict) else {}
    operation = _text(b.get("operation")) or None
    if operation and operation not in OPERATIONS:
        findings.append({"kind": "unknown-operation", "operation": operation,
                         "why": "the reasoning operation is one of the eight "
                                "SEAM groups facts by"})
    if findings:
        return {"format": FORMAT, "conflict": None, "tier": None,
                "findings": findings,
                "why": "the facts do not bind a person to a hazardous object"}
    relation = b.get("relation") if isinstance(b.get("relation"), dict) else {}
    detail = {}
    violated = None
    if "above" in relation and "value" in relation:
        limit = _num(relation.get("above"))
        value = _num(relation.get("value"))
        if limit is not None and value is not None:
            violated = value > limit
            detail = {"limit": limit, "value": value}
    elif "below" in relation and "value" in relation:
        limit = _num(relation.get("below"))
        value = _num(relation.get("value"))
        if limit is not None and value is not None:
            violated = value < limit
            detail = {"limit": limit, "value": value}
    elif relation.get("member_of"):
        violated = True
        detail = {"membership": relation.get("member_of")}
    else:
        findings.append({"kind": "no-relation-stated",
                         "why": "a binding without a relation cannot be violated"})
        return {"format": FORMAT, "conflict": None, "tier": None,
                "findings": findings,
                "why": "the binding states no relation to violate"}
    if not violated:
        return {"format": FORMAT, "conflict": False, "tier": TIERS.get(operation),
                "operation": operation, "findings": [],
                "why": "the bound facts do not violate the relation; the twin "
                       "is safe"}
    findings.append({"kind": "composed-conflict",
                     "operation": operation, "detail": detail,
                     "why": "no single screen carries this conflict; it exists "
                            "only in the composition of the facts"})
    return {"format": FORMAT, "conflict": True, "tier": TIERS.get(operation),
            "operation": operation, "detail": detail, "findings": findings,
            "why": "the harm is in the composition, so checking one screen at "
                   "a time cannot find it"}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def screen_check(screens):
    """Verify SEAM's guarantee: no single screen carries the conflict.

    `screens` — [{"id": "page-1", "facts": ["person", "object"]}, ...]
    """
    rows = [s for s in (screens or []) if isinstance(s, dict)]
    findings = []
    multi = []
    for screen in rows:
        facts = [_text(f) for f in (screen.get("facts") or [])]
        if len(set(facts)) > 1:
            multi.append(screen.get("id"))
    if multi:
        findings.append({"kind": "screen-carries-two-facts", "screens": multi,
                         "why": "the harm must not be visible on one screen, or "
                                "a single-screen check finds it"})
    for screen in rows:
        if screen.get("names_conflict"):
            findings.append({"kind": "screen-names-the-conflict",
                             "screen": screen.get("id"),
                             "why": "no text may state the conflict"})
    return {"format": FORMAT, "screens": len(rows), "composed_screens": multi,
            "findings": findings,
            "why": "the guarantee is behavioural: the single-screen rendering "
                   "separates harmful from benign by nothing"}


def recognition_vs_action(rows):
    """The thought-action disconnect: recognised, then committed.

    `rows` — [{"outcome": "executes-silent"|"executes-flagged"|"stops"|...,
               "recognised": True|False, "mentioned_fact": True|False,
               "stated_conflict": True|False}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    harmful = [r for r in data if _text(r.get("outcome")).startswith("executes")]
    recognised_harmful = [r for r in harmful if r.get("recognised")]
    stated = [r for r in recognised_harmful if r.get("stated_conflict")]
    findings = []
    if recognised_harmful and stated:
        findings.append({"kind": "thought-action-disconnect",
                         "count": len(stated), "of_harmful": len(harmful),
                         "why": "the agent stated the conflict and confirmed "
                                "anyway; recognition did not reach the action"})
    for r in harmful:
        if r.get("mentioned_fact") and not r.get("stated_conflict"):
            findings.append({"kind": "fact-mentioned-without-conflict",
                             "why": "the fact was read but never connected to "
                                    "the action about to be committed"})
    return {"format": FORMAT, "harmful": len(harmful),
            "recognised_among_harmful": len(recognised_harmful),
            "stated_conflict": len(stated),
            "recognition_rate": round(len(recognised_harmful) / len(harmful), 4)
            if harmful else None,
            "findings": findings,
            "why": "knowing the harm and acting safely are two different "
                   "measurements"}


def channel_effect(rows):
    """The same hazard, delivered through different channels.

    `rows` — [{"variant": "R"|"E"|"Eq"|"Eu", "harmful": 0|1, "n": int}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    rates = {}
    for row in data:
        variant = str(row.get("variant") or "").strip()
        n = int(row.get("n") or 0)
        harmful = int(row.get("harmful") or 0)
        if not variant or not n:
            continue
        rates[variant] = round(harmful / n, 4)
    findings = []
    lower = {k.lower(): v for k, v in rates.items()}
    r_rate = lower.get("r")
    eu_rate = lower.get("eu")
    if r_rate is not None and eu_rate is not None and r_rate > eu_rate:
        findings.append({"kind": "channel-carries-the-gap",
                         "r": r_rate, "eu": eu_rate,
                         "delta": round(r_rate - eu_rate, 4),
                         "why": "the same sentence in the instruction stops the "
                                "agent far more often than the same sentence on "
                                "a screen"})
    e_rate = lower.get("e")
    eq_rate = lower.get("eq")
    if e_rate is not None and eq_rate is not None:
        findings.append({"kind": "channel-effect-measured",
                         "e_minus_eq": round(e_rate - eq_rate, 4),
                         "why": "relaying the requester's sentence in the "
                                "user's instruction moves only the channel"})
    if eq_rate is not None and eu_rate is not None:
        findings.append({"kind": "speaker-effect-measured",
                         "eq_minus_eu": round(eq_rate - eu_rate, 4),
                         "why": "the same channel said by a different speaker "
                                "moves much less than the channel itself"})
    return {"format": FORMAT, "rates": rates, "findings": findings,
            "why": "the translation from evidence to action depends on how the "
                   "evidence arrives"}


def commit_gate(state):
    """What the harness may do at the moment of commit.

    `state` — {"conflict": bool, "facts_available": [ids], "needed_facts":
                [ids], "channel": "instruction"|"screen"|..., "user_stated":
                bool}
    """
    st = state if isinstance(state, dict) else {}
    available = {str(f) for f in (st.get("facts_available") or [])}
    needed = {str(f) for f in (st.get("needed_facts") or [])}
    missing = sorted(needed - available)
    findings = []
    if st.get("conflict"):
        findings.append({"kind": "unresolved-composed-conflict",
                         "why": "a conflict is known at the commit point; the "
                                "action must not be committed silently"})
    if missing:
        findings.append({"kind": "fact-not-in-the-judgment", "missing": missing,
                         "why": "a fact read earlier may no longer be part of "
                                "the judgment at commit time"})
    if st.get("user_stated"):
        findings.append({"kind": "stated-in-instruction",
                         "why": "the channel the fact arrived in decides how "
                                "much it reaches the action"})
    decision = "deny" if (st.get("conflict") or missing) else "allow"
    return {"format": FORMAT, "decision": decision, "missing": missing,
            "findings": findings,
            "why": "at the moment of commit the harness holds the composed "
                   "facts; a conflict it knows about cannot be committed"}


def advise(profile):
    """What a harness may claim about its own safety measurement."""
    prof = profile if isinstance(profile, dict) else {}
    findings = []
    if not prof.get("composed_tasks"):
        findings.append({"kind": "no-composed-tasks",
                         "why": "single-screen and single-intent checks pass "
                                "without ever testing a composed harm"})
    if not prof.get("benign_twin"):
        findings.append({"kind": "no-benign-twin",
                         "why": "without a twin, refusal and incapability look "
                                "identical"})
    if not prof.get("commit_point_check"):
        findings.append({"kind": "no-check-at-commit",
                         "why": "recognition at the screen does not survive to "
                                "the confirmation"})
    findings.append({"kind": "recognition-is-not-safety",
                     "why": "an agent that flags the harm when asked still "
                            "commits it; knowledge is not a defence"})
    findings.append({"kind": "harm-is-not-only-in-the-instruction",
                     "why": "a truthful page and a legitimate task can still "
                            "compose into harm"})
    return {"format": FORMAT, "findings": findings,
            "why": "a harness reports what it cannot prove: it can measure "
                   "exposure, recognition and execution separately"}
