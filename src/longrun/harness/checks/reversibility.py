#!/usr/bin/env python3
"""Reversibility classes — "there is an undo command" is not a recovery claim.

Source: arXiv:2611.22075, "Can You Undo It? Reversibility Classes for AI Agent
Actions" (round 129). Tool-using agents change files, databases, access rights
and public information, but permission to call a tool says nothing about whether
a mistake can be undone. The paper declares a five-level vocabulary with
argument-sensitive rules, conservative defaults and an explicit prior-state
capture contract, and pins an evidence-linked registry over 536 tools.

What the paper establishes, and what this module encodes:

  * EXACT RESTORATION has three requirements, not one (§3): the prior state must
    be recorded in full, the principal must already be able to write it back
    without another person's intervention, and no outside party may have seen,
    received or acted upon the changed state. An audit log satisfies the first
    and neither of the others.
  * The highest applicable effect decides the class; ordered argument rules
    select among the explicitly declared cases; unmatched inputs keep the base
    class; an UNRECOGNIZED call is R4 (§3, §4.1).
  * DISCLOSURE is R4 even when a stored message can be deleted, and a disclosure
    cannot be lowered while it remains a disclosure (§3).
  * A CAPTURE-BASED R1 override must have a confirmed capture before the call;
    a failure reverts to the underlying class, and a capture of one private file
    cannot justify an override covering payments, other files, access changes,
    triggered automation or disclosure (§4.3).
  * A RESTORATION check must measure two things: removal of the mistaken effect
    AND preservation of subsequent legitimate changes (§7). Equality with the
    starting state can coexist with data loss (the SQLite later-insert case);
    a documented soft reset does not restore a pending merge (§6.6).
  * The measured replay is a TRADE-OFF, not a win: coverage 29/29 versus 18/29
    for a read/write proxy, but nine MORE benign approval points, and the whole
    coverage difference depends on modelling web reads as exposure (§6.3).

What this module does NOT do: it does not create backups, discover effects,
perform merges, or prove that no outsider observed an action. Those belong to
the deployment, and the paper is explicit that the classifier cannot.

Pure: records and observations in, classes and findings out.
"""
from __future__ import annotations

FORMAT = "longrun-reversibility/1"

CLASSES = ("R0", "R1", "R2", "R3", "R4")

CLASS_NAMES = {
    "R0": "no-effect",
    "R1": "restorable",
    "R2": "compensable",
    "R3": "hard-to-recover",
    "R4": "irreversible",
}

RECOVERY_CRITERIA = {
    "R0": "no external state change within the declared effect boundary",
    "R1": "prior state recorded in full, writable by the principal, unobserved "
          "outside its control",
    "R2": "a known further action reaches an accepted equivalent state at a "
          "bounded, knowable cost",
    "R3": "recovery requires a human, an outside process or unbounded effort; "
          "access, credentials, availability or physical-state changes live here",
    "R4": "disclosure, unrecoverable destruction, or another consequence that "
          "cannot be recalled or compensated",
}

AUTONOMY = {
    "R0": "act-autonomously",
    "R1": "act-then-notify",
    "R2": "ask-or-preapproved-budget",
    "R3": "ask-each-action",
    "R4": "never-autonomous",
}

# The evaluated hook returns "ask" for R2-R4 and no decision at all for R0-R1,
# leaving the client's own permissions in force (§4.2). "no decision" is NOT
# "the call was allowed".
HOOK = {"R0": "no-decision", "R1": "no-decision", "R2": "ask",
        "R3": "ask", "R4": "ask"}

# Scope an override may never claim (§4.3).
FORBIDDEN_SCOPE = ("payments", "other-files", "access-changes",
                   "triggered-automation", "disclosure")


def _text(value):
    return str(value or "").strip().lower()


def _conditions(when, call):
    """Evaluate a rule's `when` block against a call.

    Supported conditions: {"argument": name, "equals"|"in"|"prefix"|"exists":
    value} (also spelled {"argument": name, "op": ..., "value": ...}) and lists
    under "all"/"any".
    """
    if not when:
        return True
    if isinstance(when, list):
        return all(_conditions(item, call) for item in when)
    if "all" in when:
        return all(_conditions(item, call) for item in (when.get("all") or []))
    if "any" in when:
        return any(_conditions(item, call) for item in (when.get("any") or []))
    arguments = call.get("arguments") or {}
    if "disclosure" in when:
        return bool(call.get("disclosure")) is bool(when.get("disclosure"))
    name = when.get("argument")
    if name is None:
        return False
    if name not in arguments:
        return False
    value = arguments.get(name)
    for op in ("equals", "in", "prefix", "exists"):
        if op in when:
            expected = when.get(op)
            if op == "equals":
                return _text(value) == _text(expected)
            if op == "in":
                return _text(value) in {_text(v) for v in (expected or [])}
            if op == "prefix":
                return _text(value).startswith(_text(expected))
            return value is not None
    op = when.get("op", "equals")
    expected = when.get("value")
    if op == "equals":
        return _text(value) == _text(expected)
    if op == "in":
        return _text(value) in {_text(v) for v in (expected or [])}
    if op == "prefix":
        return _text(value).startswith(_text(expected))
    if op == "exists":
        return value is not None
    return False


def _rule_matches(rule, call):
    """A rule is an ORDERED lowering rule; it must name a positive form."""
    when = rule.get("when")
    if when is None:
        return False
    keys = set()
    if isinstance(when, dict):
        keys = {str(k).lower() for k in when}
    elif isinstance(when, list):
        keys = set()
        for item in when:
            if isinstance(item, dict):
                keys |= {str(k).lower() for k in item}
    # A lowering rule has to identify a positive, narrowly defined form; the
    # absence of a dangerous keyword is not a rule (§4.1).
    if any(k.startswith("not_") or k in ("missing", "absence") for k in keys):
        return False
    return _conditions(when, call)


def classify(call, record=None):
    """Classify one proposed call against a declared registry record.

    `call`   — {"tool", "arguments", "disclosure"}
    `record` — {"class": base class for the tool's broadest effect,
                "rules": [{"id", "when", "class"}], "rationale"}
    """
    call = call if isinstance(call, dict) else {}
    findings = []
    if not isinstance(record, dict) or not record.get("class"):
        findings.append({"kind": "unclassified-call-defaults-r4",
                         "why": "an unrecognized call is R4; the conservative "
                                "default is not a safe one"})
        return {"format": FORMAT, "class": "R4", "base": "R4", "rule": None,
                "disclosure": bool(call.get("disclosure")), "findings": findings,
                "why": "no registry record; treated as irreversible"}
    base = str(record.get("class")).upper()
    if base not in CLASSES:
        base = "R4"
    disclosure = bool(call.get("disclosure") or record.get("disclosure"))
    rules = [r for r in (record.get("rules") or []) if isinstance(r, dict)]
    # The highest applicable effect decides the class. Every matching rule is a
    # candidate: stopping at the first made the class depend on rule order, so a
    # broad early rule silently lowered an irreversible action.
    chosen = None
    cls = base
    for rule in rules:
        if not _rule_matches(rule, call):
            continue
        cand = str(rule.get("class") or base).upper()
        if cand not in CLASSES:
            cand = base
        if chosen is None or CLASSES.index(cand) > CLASSES.index(cls):
            chosen, cls = rule, cand
    if chosen is None and rules:
        findings.append({"kind": "unmatched-arguments-keep-base",
                         "base": base,
                         "why": "no declared rule covers these arguments"})
    if disclosure:
        if cls != "R4":
            findings.append({"kind": "disclosure-not-lowerable",
                             "attempted": cls,
                             "why": "intended delivery to outsiders is R4 even "
                                    "when a stored copy can be deleted"})
        cls = "R4"
    return {"format": FORMAT, "class": cls, "base": base,
            "rule": (chosen or {}).get("id"), "disclosure": disclosure,
            "findings": findings,
            "why": "the highest applicable effect decides the class; ordered "
                   "rules only select among the declared cases"}


def hint_class(annotations, trusted=False):
    """The trusted-annotation mapping (§4.2) — it cannot express R2.

    read-only hint -> R0; otherwise open-world -> R4, closed-world and
    destructive -> R3, closed-world and non-destructive -> R1. Missing hint
    fields use the protocol defaults, so an absent openWorldHint means an open
    world. NO branch yields R2, and every comparable R2 entry differed for
    exactly that reason (§6.2).
    """
    hints = annotations if isinstance(annotations, dict) else {}
    findings = [{"kind": "hint-mapping-cannot-express-r2",
                 "why": "no branch of the annotation mapping yields R2, so a "
                        "compensable action is invisible to it"}]
    if not trusted:
        findings.append({"kind": "annotations-untrusted",
                         "why": "MCP annotations are untrusted unless their "
                                "source is trusted"})
    read_only = bool(hints.get("read_only", hints.get("readOnlyHint", False)))
    open_world = bool(hints.get("open_world", hints.get("openWorldHint", True)))
    destructive = bool(hints.get("destructive", hints.get("destructiveHint", True)))
    if read_only:
        cls = "R0"
    elif open_world:
        cls = "R4"
    elif destructive:
        cls = "R3"
    else:
        cls = "R1"
    return {"format": FORMAT, "class": cls, "findings": findings,
            "why": "hint mapping is a representational loss, not an accuracy "
                   "estimate against the registry"}


def restoration_requirements(state):
    """The three requirements of exact restoration (§3).

    `state` — {"prior_state_recorded", "principal_can_write", "outside_observed"}
    """
    state = state if isinstance(state, dict) else {}
    recorded = bool(state.get("prior_state_recorded"))
    can_write = bool(state.get("principal_can_write"))
    observed = bool(state.get("outside_observed"))
    findings = []
    if not recorded:
        findings.append({"kind": "prior-state-not-recorded",
                         "why": "nothing was captured before execution"})
    if not can_write:
        findings.append({"kind": "no-authority-to-restore",
                         "why": "restoring the state needs another person's "
                                "intervention"})
    if observed:
        findings.append({"kind": "outside-observation",
                         "why": "an outside party saw, received or acted upon "
                                "the changed state"})
    if recorded and not (can_write and not observed):
        findings.append({"kind": "audit-log-is-not-restoration",
                         "why": "an audit log records the prior state but does "
                                "not restore it, and does not un-observe it"})
    exact = recorded and can_write and not observed
    return {"format": FORMAT, "exact_restoration": exact,
            "criteria": {"prior_state_recorded": recorded,
                         "principal_can_write": can_write,
                         "outside_observed": observed},
            "findings": findings,
            "why": "exact restoration needs recorded state, authority to write "
                   "it back, and no outside observation"}


def capture_override(base_class, override):
    """A capture-based override: confirmed capture, bounded scope, a reference."""
    base = str(base_class or "R4").upper()
    if base not in CLASSES:
        base = "R4"
    over = override if isinstance(override, dict) else {}
    findings = []
    capture = over.get("capture") or {}
    if not isinstance(capture, dict) or not capture:
        findings.append({"kind": "capture-missing",
                         "why": "no capture declared for an R1 override"})
        return {"format": FORMAT, "class": base, "capture_confirmed": False,
                "findings": findings,
                "why": "an override without a capture declaration is refused"}
    confirmed = bool(capture.get("confirmed"))
    if not confirmed:
        findings.append({"kind": "capture-unconfirmed-falls-back",
                         "why": "capture must be confirmed BEFORE the call; the "
                                "decision reverts to the underlying class"})
        return {"format": FORMAT, "class": base, "capture_confirmed": False,
                "findings": findings,
                "why": "unconfirmed capture; the underlying class applies"}
    scope = {_text(s) for s in (over.get("scope") or [])}
    forbidden = sorted(scope & set(FORBIDDEN_SCOPE))
    if forbidden:
        findings.append({"kind": "capture-scope-too-broad", "scope": forbidden,
                         "why": "a private-file capture cannot justify an "
                                "override covering these categories"})
        return {"format": FORMAT, "class": base, "capture_confirmed": True,
                "findings": findings,
                "why": "the override scope is refused; the underlying class applies"}
    missing = [k for k in ("state", "restore", "retention")
               if not capture.get(k)]
    if missing:
        findings.append({"kind": "capture-contract-incomplete", "missing": missing,
                         "why": "a capture declares what to save, how to restore "
                                "it and how long it is kept"})
        # A half-specified capture cannot justify autonomy: revert like the
        # unconfirmed and over-broad paths, instead of lowering the class anyway.
        return {"format": FORMAT, "class": base, "capture_confirmed": True,
                "findings": findings,
                "why": "an incomplete capture contract reverts to the underlying "
                       "class"}
    if not over.get("capture_ref"):
        findings.append({"kind": "capture-reference-missing",
                         "why": "each captured decision must carry its capture "
                                "reference in the audit record"})
    cls = str(over.get("class") or "R1").upper()
    # The contract is a capture-based R1 override. Any other requested class is
    # refused, so a caller cannot declare a mutating call as R0 (no effect).
    if cls != "R1":
        findings.append({"kind": "capture-override-not-r1", "attempted": cls,
                         "why": "a capture may only lower an action to R1"})
        cls = base
    return {"format": FORMAT, "class": cls, "capture_confirmed": True,
            "findings": findings,
            "why": "a confirmed, bounded capture supports the declared class; "
                   "the deployment still owns the backup"}


def policy_for(cls):
    """The suggested autonomy policy for a class (Table A1) and the hook's part."""
    key = str(cls or "R4").upper()
    if key not in CLASSES:
        key = "R4"
    return {"format": FORMAT, "class": key, "name": CLASS_NAMES[key],
            "autonomy": AUTONOMY[key], "hook": HOOK[key],
            "criterion": RECOVERY_CRITERIA[key],
            "why": "reversibility complements severity and authorization; it "
                   "does not replace them"}


def recovery(observations):
    """A restoration check measures removal AND preservation of later work."""
    rows = [o for o in (observations or []) if isinstance(o, dict)]
    by_policy = {}
    for row in rows:
        policy = str(row.get("policy") or "?")
        bucket = by_policy.setdefault(policy, {
            "restores-and-preserves": 0, "erases-later-work": 0,
            "deferred": 0, "withheld": 0, "partial-state": 0, "n": 0})
        bucket["n"] += 1
        matched = bool(row.get("initial_state_matched"))
        preserved = bool(row.get("later_work_preserved"))
        deferred = bool(row.get("deferred"))
        state_complete = row.get("state_complete")
        if state_complete is False:
            bucket["partial-state"] += 1
        elif deferred:
            bucket["deferred"] += 1
        elif not matched:
            bucket["withheld"] += 1
        elif not preserved:
            bucket["erases-later-work"] += 1
        else:
            bucket["restores-and-preserves"] += 1
    findings = []
    for policy, bucket in sorted(by_policy.items()):
        if bucket["erases-later-work"]:
            findings.append({"kind": "erases-later-work", "policy": policy,
                             "count": bucket["erases-later-work"],
                             "why": "restoring the starting bytes can destroy a "
                                    "later writer's legitimate change"})
        if bucket["deferred"]:
            findings.append({"kind": "deferral-is-not-recovery", "policy": policy,
                             "count": bucket["deferred"],
                             "why": "deferring preserves the current state; it "
                                    "does not complete recovery"})
        if bucket["partial-state"]:
            findings.append({"kind": "recovery-route-partial", "policy": policy,
                             "count": bucket["partial-state"],
                             "why": "a documented undo can restore the tip and "
                                    "the files but not the pending merge state"})
    return {"format": FORMAT, "policies": by_policy, "n": len(rows),
            "findings": findings,
            "why": "a recovery claim needs removal of the effect AND "
                   "preservation of subsequent legitimate changes"}


def replay(rows, baseline_policy=None):
    """The measured replay is a coverage/burden trade-off, not a free win.

    `rows` — [{"policy", "attack_gated", "attack_denominator",
               "benign_approvals", "benign_runs", "depends_on_web_exposure"}]
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "policies": {}, "findings": [],
                "why": "no replay rows"}
    names = [str(r.get("policy") or "?") for r in rows]
    base_name = baseline_policy or names[0]
    table = {}
    for row in rows:
        name = str(row.get("policy") or "?")
        denominator = int(row.get("attack_denominator") or 0)
        gated = int(row.get("attack_gated") or 0)
        benign_runs = int(row.get("benign_runs") or 0)
        approvals = int(row.get("benign_approvals") or 0)
        table[name] = {
            "coverage": round(gated / denominator, 4) if denominator else None,
            "attack_gated": gated, "attack_denominator": denominator,
            "benign_approvals": approvals, "benign_runs": benign_runs,
            "approvals_per_benign_run": round(approvals / benign_runs, 4)
            if benign_runs else None,
            "depends_on_web_exposure": bool(row.get("depends_on_web_exposure")),
        }
    findings = [{"kind": "attack-coverage-denominator-is-selective",
                 "why": "the denominator is the attributable subset, not every "
                        "injected run; zero attributed cases is absence of "
                        "attributable evidence, not proof of prevention"}]
    base = table.get(base_name)
    if base:
        for name, entry in sorted(table.items()):
            if name == base_name:
                continue
            if entry["coverage"] is None or base["coverage"] is None:
                continue
            coverage_delta = round(entry["coverage"] - base["coverage"], 4)
            burden_delta = None
            if entry["approvals_per_benign_run"] is not None \
                    and base["approvals_per_benign_run"] is not None:
                burden_delta = round(entry["approvals_per_benign_run"]
                                     - base["approvals_per_benign_run"], 4)
            entry["coverage_delta_vs_baseline"] = coverage_delta
            entry["approval_delta_per_benign_run"] = burden_delta
            if coverage_delta > 0 and burden_delta is not None and burden_delta >= 0:
                findings.append({"kind": "coverage-gain-is-not-free", "policy": name,
                                 "coverage_delta": coverage_delta,
                                 "approval_delta": burden_delta,
                                 "why": "more coverage came with no fewer benign "
                                        "approval points; the hypothesis that the "
                                        "guard lowers burden is not supported"})
            if entry["depends_on_web_exposure"]:
                findings.append({"kind": "coverage-is-modelling-dependent",
                                 "policy": name,
                                 "why": "the whole coverage difference rests on "
                                        "treating a web read as an exposure channel"})
    return {"format": FORMAT, "policies": table, "baseline": base_name,
            "findings": findings,
            "why": "a replay projects approval points; it measures neither "
                   "prevented harm nor post-intervention task success"}
