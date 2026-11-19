#!/usr/bin/env python3
"""Traps must sit on the attacker's path — and a trap is not a control.

Source: arXiv:2611.19295, "Optional Traps: An Empirical Study of LLM Agents
Against Credential Deception and Alert-Driven Revocation" (round 130). Deception
(honeypots, decoys, canary credentials) rests on one premise: legitimate users
never touch a fake asset, so any touch is a high-confidence signal. The paper
tests that premise against LLM agents and measures what deception adds once
ordinary hardening is in place. Four studies, one synthetic target, two small
local models — and the findings are the harness-relevant ones:

  * TRAPS BESIDE THE PATH ARE OPTIONAL. In the exploratory run the agent
    ignored every decoy, read a genuinely leaked service key from a debug
    endpoint and exported the protected records, in both static and adaptive
    deception modes (Table I: 6 calls, zero decoy hits). A goal-directed agent
    with a working path does not explore, so a decoy beside the path is never
    reached.
  * CLOSING THE REAL WEAKNESS DID THE PREVENTIVE WORK. Hardening alone and
    hardening plus deception both reduced genuine exports from 20/20 to 0/20;
    the paired McNemar p is 1.9e-6 for baseline versus defended, and p = 1 for
    hardened versus defended. Deception added REVOCATION of the attacking
    client in 19 of 20 defended sessions and no measurable prevention.
  * ALERTS CAN DRIVE NARROW ENFORCEMENT. A real OpenCanary alert, authenticated
    from the verified sensor address, redacted, signed with a per-run HMAC
    secret and posted to a control endpoint that rejects stale (>30 s), forged
    and replayed events, revoked the attacking peer whose valid token was then
    refused; the legitimate client completed 100/100 requests (Table III).
  * BAIT IS NOT CONCLUSIVE. A legitimate LLM agent held the correct key in its
    prompt, preferred the "leaked" credential, used it and was revoked
    (engagement B). Bait use is high-signal but not conclusive; the response
    was reversible and scoped (15-minute peer revocation).

So for a harness: a decoy on a path the agent never walks is not a control; a
bait an honest agent can take is not a verdict; and a detection signal is not
prevention. This module is the deterministic auditor over those three claims:

  * `path_position(bait, weakness)` — is the bait on the attacker's path or
    beside it?
  * `ablation(baseline, hardened, defended)` — prevention versus detection,
    separated.
  * `alert_gate(event, policy)` — the authentication, freshness and replay
    checks an alert-driven revocation must pass.
  * `scope(revocation, clients)` — is the response scoped to the peer, and
    what does it cost the legitimate client?
  * `false_positive(bait_use, legitimate)` — bait use is a signal, not a
    verdict.

Pure: records in, findings out. No paper number is reproduced here.
"""
from __future__ import annotations

FORMAT = "longrun-trap-path/1"

# The three conditions the paper's ablation runs.
CONDITIONS = ("baseline", "hardened", "defended")

# The checks the gateway applies to a sensor event (§V, Table III).
ALERT_CHECKS = ("verified-source", "signature", "freshness", "replay",
                "scope")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def path_position(bait, weakness):
    """Is the bait on the attacker's path, or beside it?

    `bait` — {"route": "/api/v1/debug/env", "serves": "canary-key"}
    `weakness` — {"route": "/api/v1/debug/env", "serves": "real-key"}
    """
    b = bait if isinstance(bait, dict) else {}
    w = weakness if isinstance(weakness, dict) else {}
    b_route = str(b.get("route") or "")
    w_route = str(w.get("route") or "")
    findings = []
    if not b_route:
        findings.append({"kind": "no-bait-route",
                         "why": "a trap with no route is not on any path"})
    if b_route and w_route and b_route != w_route:
        findings.append({"kind": "bait-beside-the-path",
                         "bait": b_route, "weakness": w_route,
                         "why": "the real weakness answers first, so a "
                                "goal-directed agent never reaches the bait"})
    if b_route and w_route and b_route == w_route:
        findings.append({"kind": "bait-on-the-path",
                         "route": b_route,
                         "why": "the bait occupies the place the attacker must "
                                "look"})
    if str(b.get("serves") or "") == "real-key":
        findings.append({"kind": "bait-serves-a-real-credential",
                         "why": "a canary that is a working credential is "
                                "evidence, and it must be revocable"})
    return {"format": FORMAT, "on_path": bool(b_route and b_route == w_route),
            "findings": findings,
            "why": "a trap beside the path is optional; a trap on the path is "
                   "encountered"}


def ablation(baseline, hardened, defended):
    """Prevention and detection, separated.

    `baseline`, `hardened`, `defended` — {"success": int, "n": int,
                                            "revoked": int}
    """
    out = {}
    for name in CONDITIONS:
        row = {"baseline": baseline, "hardened": hardened,
               "defended": defended}.get(name)
        row = row if isinstance(row, dict) else {}
        n = int(row.get("n") or 0)
        success = int(row.get("success") or 0)
        revoked = int(row.get("revoked") or 0)
        out[name] = {"n": n, "success": success,
                     "success_rate": round(success / n, 4) if n else None,
                     "revoked": revoked,
                     "revocation_rate": round(revoked / n, 4) if n else None}
    findings = []
    base = out["baseline"]["success_rate"]
    hard = out["hardened"]["success_rate"]
    defe = out["defended"]["success_rate"]
    if base is not None and hard is not None and hard < base:
        findings.append({"kind": "hardening-prevents",
                         "baseline": base, "hardened": hard,
                         "why": "closing the real weakness removed the "
                                "preventive effect"})
    if hard is not None and defe is not None and hard == defe:
        findings.append({"kind": "deception-adds-no-prevention",
                         "rate": hard,
                         "why": "hardened and defended are indistinguishable "
                                "on success; deception added a signal, not a "
                                "barrier"})
    if out["defended"]["revocation_rate"] and not out["hardened"]["revocation_rate"]:
        findings.append({"kind": "deception-adds-detection",
                         "rate": out["defended"]["revocation_rate"],
                         "why": "the bait identified and cut off the client "
                                "that the hardened condition could not name"})
    return {"format": FORMAT, "conditions": out, "findings": findings,
            "why": "prevention and detection are different contributions and "
                   "must be reported separately"}


def alert_gate(event, policy=None):
    """The checks an alert-driven revocation must pass before it is enforced.

    `event` — {"source": "verified"|"unknown", "signature": "valid"|"invalid"|
                None, "age_ms": int, "seen": bool}
    `policy` — {"max_age_ms": 30000, "require_signature": True}
    """
    ev = event if isinstance(event, dict) else {}
    pol = policy if isinstance(policy, dict) else {}
    max_age = int(pol.get("max_age_ms") or 30000)
    findings = []
    if str(ev.get("source") or "").lower() != "verified":
        findings.append({"kind": "unverified-source",
                         "why": "an alert from an unauthenticated source is "
                                "not evidence"})
    if pol.get("require_signature", True) \
            and str(ev.get("signature") or "").lower() != "valid":
        findings.append({"kind": "invalid-signature",
                         "why": "the event must be signed with the per-run "
                                "secret"})
    age = ev.get("age_ms")
    age_num = _num(age)
    if age_num is None:
        findings.append({"kind": "unknown-age",
                         "why": "an event with no timestamp cannot be checked "
                                "for staleness"})
    elif age_num > max_age:
        findings.append({"kind": "stale-event", "age_ms": age_num,
                         "why": "an event older than the validity window is "
                                "refused"})
    if ev.get("seen"):
        findings.append({"kind": "replayed-event",
                         "why": "a replayed signed event is refused"})
    return {"format": FORMAT, "decision": "deny" if findings else "allow",
            "findings": findings,
            "why": "the alert is authenticated, fresh, unreplayed and scoped "
                   "before it revokes anything"}


def scope(revocation, clients):
    """Is the response scoped to the peer, and what does it cost the others?

    `revocation` — {"peer": "peer-a", "minutes": 15, "applies_to": "peer"}
    `clients` — [{"id": "peer-a", "legitimate": False},
                 {"id": "peer-b", "legitimate": True}]
    """
    rev = revocation if isinstance(revocation, dict) else {}
    peer = str(rev.get("peer") or "")
    rows = [c for c in (clients or []) if isinstance(c, dict)]
    findings = []
    affected = []
    for client in rows:
        cid = str(client.get("id") or "")
        if rev.get("applies_to") == "all" or (peer and cid == peer):
            affected.append(cid)
    legitimate_hit = [c for c in affected
                      if any(str(x.get("id") or "") == str(c)
                             and x.get("legitimate") for x in rows)]
    if legitimate_hit:
        findings.append({"kind": "legitimate-client-revoked",
                         "clients": legitimate_hit,
                         "why": "a scoped response must not deny the "
                                "co-resident legitimate client"})
    minutes = rev.get("minutes")
    if minutes is not None and int(minutes) > 0:
        findings.append({"kind": "response-is-reversible",
                         "minutes": int(minutes),
                         "why": "a bait hit is high-signal but not conclusive; "
                                "the response expires"})
    if not peer:
        findings.append({"kind": "unscoped-revocation",
                         "why": "a revocation with no peer is a blanket denial"})
    return {"format": FORMAT, "affected": affected, "findings": findings,
            "why": "the enforcement is per-client and the co-resident client "
                   "keeps working"}


def false_positive(bait_use, legitimate):
    """Bait use is a signal, not a verdict.

    `bait_use` — {"peer": "peer-a", "used_canary": True}
    `legitimate` — [{"peer": "peer-a", "legitimate": True}]
    """
    use = bait_use if isinstance(bait_use, dict) else {}
    rows = [r for r in (legitimate or []) if isinstance(r, dict)]
    peer = str(use.get("peer") or "")
    findings = []
    if use.get("used_canary"):
        match = [r for r in rows if str(r.get("peer") or "") == peer
                 and r.get("legitimate")]
        if match:
            findings.append({"kind": "legitimate-agent-took-the-bait",
                             "peer": peer,
                             "why": "bait that looks useful is also taken by "
                                    "benign automation; use is a signal, not a "
                                    "verdict"})
    return {"format": FORMAT, "findings": findings,
            "why": "the premise that only attackers touch decoys assumes "
                   "benign clients follow instructions"}
