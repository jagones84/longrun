#!/usr/bin/env python3
"""Memory authority — bind the right to act to the origin, at write time.

Source: arXiv:2606.24322, "Securing LLM-Agent Long-Term Memory Against
Poisoning: Non-Malleable, Origin-Bound Authority with Machine-Checked
Guarantees" (round 158). The paper's claim is a separation: a memory item's
authority to act is derived from a signal the adversary can transform — its
content, or a derivation edge — so content and lineage defenses are unsound under
laundering, write-time origin binding is necessary, and non-malleable origin-bound
authority with Sybil-resistant corroboration-gated elevation is sufficient
(`mem_origin_authority_2606.24322.txt:31`, `:97`). The three laundering channels
are the agent's own summarization (L-a), a trusted-tool echo (L-b) and
manufactured corroboration (L-c) (`:52`, `:56`). The measured consequence: on the
unified benchmark, content and capability-IFC defenses are laundered at 68% and
lineage at 47%, while the origin-bound gate is 0% at 100% legitimate utility
(`:302`, `:335`).

This module makes the four mechanisms executable: write-time binding, non-
malleable propagation, corroboration-gated elevation with domain-aware
independence, and single-use action-bound user authorization.

Formats: `longrun-memory-authority/1`.
"""

FORMAT = "longrun-memory-authority/1"

# Integrity order: untrusted ⊏ agent ⊏ trusted (paper §IV, `:196`).
_ORDER = {"untrusted": 0, "agent": 1, "trusted": 2}
# The app's own provenance vocabulary (`memory.store` origin) maps onto the
# paper's three classes. Harness-authored knowledge is agent-derived, never
# trusted by its label alone; only the operator path is `user`/trusted.
_ORIGINS = {"untrusted": "untrusted", "external": "untrusted",
            "agent": "agent", "self": "agent",
            "reflect": "agent", "mining": "agent", "harness": "agent",
            "anchor": "agent", "meta": "agent", "auto": "agent",
            "trusted": "trusted", "tool": "trusted", "user": "trusted"}
_ACT = {"untrusted": "none", "agent": "inform", "trusted": "act"}
_ACT_RANK = {"none": 0, "inform": 1, "act": 2}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _origin(value):
    return _ORIGINS.get(str(value or "").strip().lower())


def item(record):
    """Bind an item's act class from its origin, never from its content.

    `record` = {"origin": untrusted|agent|trusted, "content": str,
                "scope": str, "claims_trust": bool (optional)}
    A payload that asserts its own trustworthiness (`claims_trust`) is recorded
    and ignored: that assertion is exactly the whitebox attack the origin label
    defeats (`:716`).
    """
    origin = _origin(record.get("origin"))
    if origin is None:
        return {"format": FORMAT, "verdict": "unknown-origin",
                "origin": record.get("origin"),
                "known": ["untrusted", "agent", "trusted"]}
    act = _ACT[origin]
    out = {"format": FORMAT, "origin": origin, "act": act,
           "scope": record.get("scope") or "session",
           "claims_trust_ignored": bool(record.get("claims_trust"))}
    out["verdict"] = ("non-actionable" if act == "none"
                      else "inform-only" if act == "inform" else "actionable")
    return out


def from_memory(record):
    """An authority item from a stored memory record's own provenance.

    The store now carries `origin`, `trigger` and (when a caller forged an
    elevated label) `origin_claim`. This is the adapter that makes a real
    recalled record consumable by `derive()` and `gate()`; the claim is passed
    as evidence and ignored by `item()`, exactly as the paper requires.
    """
    r = record if isinstance(record, dict) else {}
    return item({"origin": r.get("origin"), "content": r.get("content"),
                 "scope": r.get("scope") or "session",
                 "claims_trust": bool(r.get("origin_claim"))})


def derive(record):
    """Non-malleable propagation: a derived item inherits its worst parent.

    `record` = {"parents": [{"origin": ..., "act": ...}, ...], "channel":
                "summarize"|"tool-echo"|"merge"}
    L-a and L-b both fail here for the same structural reason: the derived act
    class is the minimum over parents, so paraphrasing or echoing untrusted
    content cannot raise it (`:164`, `:172`).
    """
    parents = [p for p in (record.get("parents") or []) if isinstance(p, dict)]
    if not parents:
        return {"format": FORMAT, "verdict": "no-parents"}
    origins = [_origin(p.get("origin")) for p in parents]
    if any(o is None for o in origins):
        return {"format": FORMAT, "verdict": "unknown-origin"}
    acts = [_ACT[o] for o in origins]
    worst = min(origins, key=lambda o: _ORDER[o])
    act = min(acts, key=lambda a: _ACT_RANK[a])
    out = {"format": FORMAT, "origin": worst, "act": act,
           "parents": len(parents), "channel": record.get("channel") or "merge"}
    out["verdict"] = ("tainted-inherited" if _ORDER[worst] < 2
                      else "trusted-inherited")
    return out


def corroborate(record):
    """Elevation needs k INDEPENDENT trusted principals, not k items.

    `record` = {"vouchers": [{"principal": id, "domain": id}, ...], "k": 2}
    Independence is a distinct domain, so two endpoints of one vendor count once
    (paper §VIII, `:700`; Table X `:690`). Repeated untrusted items never count.
    """
    vouchers = [v for v in (record.get("vouchers") or []) if isinstance(v, dict)]
    k = int(_num(record.get("k"), 2))
    if k < 1:
        return {"format": FORMAT, "verdict": "invalid-threshold"}
    trusted = [v for v in vouchers
               if _origin(v.get("origin") or "trusted") == "trusted"]
    # R160 bug hunt: an unattributed voucher has no identity, so it cannot
    # establish INDEPENDENCE. The old code fell back to the list index, which
    # fabricated one distinct "domain" per anonymous voucher.
    domains = set()
    for v in trusted:
        ident = v.get("domain") or v.get("principal")
        if ident is not None and str(ident).strip():
            domains.add(str(ident))
    out = {"format": FORMAT, "vouchers": len(vouchers), "k": k,
           "independent": len(domains), "domains": sorted(domains)}
    if len(domains) >= k:
        out["verdict"] = "elevated"
    elif len(trusted) >= k:
        out["verdict"] = "correlated-not-independent"
    else:
        out["verdict"] = "insufficient-corroboration"
    return out


def authorize(record):
    """A single-use token bound to the concrete action, not the session.

    `record` = {"token": {"tool", "value", "amount", "nonce", "ts"},
                "action": {"tool", "value", "amount"}, "used": [nonce, ...]}
    Any field mismatch or a spent nonce voids the approval — this is what rules
    out replay and payee substitution (`:199`).
    """
    token = record.get("token") or {}
    action = record.get("action") or {}
    used = [str(u) for u in (record.get("used") or [])]
    if not token or not action:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    # A single-use token needs an identity to spend; without a nonce the replay
    # check cannot run at all, so an anonymous token is refused. Every field the
    # token names must be PRESENT and equal in the action: the old code compared
    # only fields present on both sides, so `{amount: 100}` authorized a call that
    # omitted the amount, and `{}` authorized `{amount: 999}`.
    missing = [f for f in ("tool", "value", "nonce")
               if not str(token.get(f) or "").strip()]
    if missing:
        return {"format": FORMAT, "verdict": "incomplete-token",
                "missing": missing}
    mismatched = [f for f in ("tool", "value", "amount")
                  if f in token and (f not in action
                                     or str(token.get(f)) != str(action.get(f)))]
    nonce = str(token.get("nonce") or "")
    if mismatched:
        return {"format": FORMAT, "verdict": "action-mismatch",
                "fields": mismatched}
    if nonce and nonce in used:
        return {"format": FORMAT, "verdict": "replayed", "nonce": nonce}
    return {"format": FORMAT, "verdict": "authorized", "nonce": nonce}


def gate(record):
    """The act-time decision: allow iff the value is not untrusted-derived, or
    elevated by k independent principals, or covered by a fresh authorization.

    `record` = {"parents": [items], "action": {"tool", "value"},
                "vouchers": [...], "k": 2, "token": {...}, "used": [...]}
    Ordering matters: an untrusted-free value never needs an approval, and an
    approval never launders a value it does not name.
    """
    parents = [p for p in (record.get("parents") or []) if isinstance(p, dict)]
    action = record.get("action") or {}
    if not action:
        return {"format": FORMAT, "verdict": "no-action"}
    untrusted = [p for p in parents
                 if _origin(p.get("origin")) == "untrusted"]
    if not untrusted:
        return {"format": FORMAT, "verdict": "allow",
                "reason": "value-not-untrusted-derived"}
    elevation = corroborate({"vouchers": record.get("vouchers") or [],
                             "k": record.get("k", 2)})
    if elevation.get("verdict") == "elevated":
        return {"format": FORMAT, "verdict": "allow",
                "reason": "corroborated", "independent": elevation["independent"]}
    auth = authorize({"token": record.get("token") or {}, "action": action,
                      "used": record.get("used") or []})
    if auth.get("verdict") == "authorized":
        return {"format": FORMAT, "verdict": "allow",
                "reason": "fresh-action-bound-authorization"}
    return {"format": FORMAT, "verdict": "deny",
            "reason": "untrusted-derived-uncorroborated",
            "elevation": elevation.get("verdict"), "authorization": auth.get("verdict")}


def weakening(record):
    """Is a transformation able to RAISE an item's authority?

    `record` = {"before": origin, "after": origin, "transformation": name}
    Non-malleability is defined exactly as `rank(after) <= rank(before)` for
    every transformation (`:202`). The module reports the violation, which is
    what a content or lineage defense allows.
    """
    before = _origin(record.get("before"))
    after = _origin(record.get("after"))
    if before is None or after is None:
        return {"format": FORMAT, "verdict": "unknown-origin"}
    delta = _ORDER[after] - _ORDER[before]
    return {"format": FORMAT, "before": before, "after": after,
            "delta": delta, "transformation": record.get("transformation"),
            "verdict": ("malleable" if delta > 0 else "non-malleable")}


def separation(record):
    """Compare a defense class's measured failures with the theorem's prediction.

    `record` = {"defense": "content"|"lineage"|"capability"|"origin",
                "measured": {"direct": 0..1, "summarization": 0..1,
                             "echo": 0..1, "corroboration": 0..1}}
    Predicted (T1): content fails on all three laundering channels; lineage
    fails on summarization and echo; capability-IFC fails on everything
    including the direct attack; origin fails on nothing (`:500`, `:508`).
    """
    defense = str(record.get("defense") or "").strip().lower()
    predicted = {
        "content": {"direct": False, "summarization": True,
                    "echo": True, "corroboration": True},
        "lineage": {"direct": False, "summarization": True,
                    "echo": True, "corroboration": False},
        "capability": {"direct": True, "summarization": True,
                       "echo": True, "corroboration": True},
        "origin": {"direct": False, "summarization": False,
                   "echo": False, "corroboration": False},
    }
    if defense not in predicted:
        return {"format": FORMAT, "verdict": "unknown-defense",
                "known": sorted(predicted)}
    measured = record.get("measured") or {}
    mismatches = []
    table = {}
    for channel, fails in predicted[defense].items():
        if channel not in measured:
            continue
        observed = _num(measured.get(channel)) > 0.0
        table[channel] = {"predicted_fail": fails, "observed_fail": observed}
        if observed != fails:
            mismatches.append(channel)
    return {"format": FORMAT, "defense": defense, "channels": table,
            "mismatches": mismatches,
            "verdict": "theory-matches" if not mismatches else "theory-mismatch"}


def model_check(record):
    """A small exhaustive counterpart of the paper's TLA+ model.

    `record` = {"slots": 3, "k": 2, "assume": "origin"|"no-binding"|"lineage"}
    Enumerates every assignment of origins to slots and asks whether an
    untrusted-origin item can reach an act class above `none` for the new actor.
    With write-time binding the count is 0; without binding it is every state
    with an untrusted slot; a lineage-only defense lets an untrusted item pass
    when its derived edge looks trusted.
    """
    slots = max(1, min(5, int(_num(record.get("slots"), 3))))
    assume = str(record.get("assume") or "origin").strip().lower()
    origins = ["untrusted", "agent", "trusted"]
    states = 0
    violations = 0
    for a in range(3 ** slots):
        assign = []
        n = a
        for _ in range(slots):
            assign.append(origins[n % 3])
            n //= 3
        states += 1
        if assume == "no-binding":
            violations += 1 if "untrusted" in assign else 0
        elif assume == "lineage":
            violations += 1 if "untrusted" in assign and "trusted" in assign else 0
        else:
            violations += sum(1 for o in assign if o == "untrusted" and
                              _ACT[o] != "none")
    return {"format": FORMAT, "slots": slots, "assume": assume,
            "states": states, "violations": violations,
            "verdict": ("safe" if violations == 0 else "unsafe")}


def audit_record(record):
    """Check an authority record's internal consistency before trusting it."""
    findings = []
    acts = [v for v in (record.get("items") or []) if isinstance(v, dict)]
    if not acts:
        findings.append("no items supplied")
    for it in acts:
        origin = _origin(it.get("origin"))
        if origin is None:
            findings.append("item with unknown origin: %r" % (it.get("origin"),))
            continue
        if it.get("act") and it.get("act") != _ACT[origin]:
            findings.append("item %r claims act %r but its origin allows %r"
                            % (it.get("id"), it.get("act"), _ACT[origin]))
    if record.get("k") is not None and int(_num(record.get("k"))) < 2:
        findings.append("elevation threshold below 2: a single compromised "
                        "channel is enough")
    return {"format": FORMAT, "items": len(acts), "findings": findings,
            "verdict": "audit-complete"}


def advise(profile):
    """Recommendations from a measured authority profile."""
    findings = []
    if (profile or {}).get("laundering"):
        rate = _num(profile.get("laundering"))
        if rate > 0:
            findings.append("laundering succeeds at %.2f; the decision is a "
                            "function of content or a derivation edge" % rate)
    k = int(_num((profile or {}).get("k"), 2))
    if k < 2:
        findings.append("raise the elevation threshold to 2 independent domains")
    if (profile or {}).get("utility") is not None and _num(profile.get("utility")) < 0.8:
        findings.append("utility is %.2f; elevation is what lets legitimate "
                        "external information act" % _num(profile.get("utility")))
    if (profile or {}).get("correlated"):
        findings.append("vouchers share a domain; count independent domains, "
                        "not endpoints")
    if not findings:
        findings.append("no laundering, threshold or utility measurement supplied")
    return {"format": FORMAT, "findings": findings}
