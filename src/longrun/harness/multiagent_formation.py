#!/usr/bin/env python3
"""Multi-agent formation — separate agents for separate users can beat nobody.

Source: arXiv:2610.00583, "Worse Together: How Performance Breaks Down in
Multi-User Multi-Agent Teams" (round 159). It compares four formations over
77 scenarios in four shared-resource environments: a solo agent, one coordinator
serving every user, a silent team (one agent per user, no channel) and a
peer-to-peer team (`mamubench_teams_2610.00583.txt:126`). Teams lose to the
coordinator in every environment, and they collapse hardest with no channel
(`:31`, `:185`). The mechanism is not one bug: participation falls as teams grow
(66% → 10% for one model, `:190`), agents override peers, requests reach the
committer without being read, and claims about other people are fabricated
(`:371`, `:376`, `:415`). Mitigations are environment-specific and only a lead
told to rank by value beats the coordinator (`:217`).

Formats: `longrun-multiagent-formation/1`.
"""

FORMAT = "longrun-multiagent-formation/1"

_FORMATIONS = {
    "solo": {"agents": 1, "channel": False, "users": 1},
    "coordinator": {"agents": 1, "channel": False, "users": "many"},
    "silent-team": {"agents": "one-per-user", "channel": False, "users": "many"},
    "peer-team": {"agents": "one-per-user", "channel": True, "users": "many"},
}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def formations():
    """The four formations the paper compares."""
    return {"format": FORMAT, "formations": [
        {"formation": k, **v} for k, v in _FORMATIONS.items()]}


def outcome(record):
    """Per-formation group outcome, and the gap to the coordinator.

    `record` = {"shares": {"coordinator": 0..1, "peer-team": 0..1,
                           "silent-team": 0..1}} — share of the achievable optimum.
    The paper's decision rule is a comparison, not a threshold: a team that is
    lower than its coordinator is `worse-together`, whatever its absolute score
    (`:29`).
    """
    shares = {k: _num(v) for k, v in (record.get("shares") or {}).items()
              if k in _FORMATIONS}
    if "coordinator" not in shares or len(shares) < 2:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    coord = shares["coordinator"]
    out = {"format": FORMAT, "shares": shares, "coordinator": coord}
    teams = {k: v - coord for k, v in shares.items() if k != "coordinator"}
    out["gaps"] = teams
    worst = min(teams, key=lambda k: teams[k])
    out["worst"] = worst
    out["verdict"] = ("worse-together" if teams[worst] < 0
                      else "team-not-worse")
    return out


def participation(record):
    """Share of team members that ever act, by team size.

    `record` = {"points": [{"size": 4, "share": 0..1}, ...]}
    A team whose participation halves as it grows has lost the work before any
    coordination question is asked; the paper's largest teams act at 10–25%
    (`:190`).
    """
    points = [p for p in (record.get("points") or []) if isinstance(p, dict)]
    if len(points) < 2:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    points = sorted(points, key=lambda p: _num(p.get("size")))
    first = _num(points[0].get("share"))
    last = _num(points[-1].get("share"))
    out = {"format": FORMAT, "first": first, "last": last,
           "drop": first - last,
           "sizes": [_num(p.get("size")) for p in points]}
    out["verdict"] = ("participation-collapse" if last <= first / 2
                      else "participation-holds")
    return out


def fairness(record):
    """Jain index over users' outcome attainment.

    `record` = {"attainment": [x1, .., xn]} (0..1 each, n >= 2)
    J = (Σx)² / (n·Σx²); 1 is perfectly even and 1/n means one user gets
    everything (`:244`). The paper reports it beside the score because a team can
    score by concentrating on one user.
    """
    xs = [_num(x) for x in (record.get("attainment") or [])]
    if len(xs) < 2:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    total = sum(xs)
    squares = sum(x * x for x in xs)
    if squares == 0:
        return {"format": FORMAT, "verdict": "no-attainment"}
    j = (total * total) / (len(xs) * squares)
    return {"format": FORMAT, "jain": j, "n": len(xs),
            "even": abs(j - 1.0) < 1e-9,
            "verdict": "fair" if j >= 0.75 else "concentrated"}


def interference(record):
    """Peer takeovers per episode, and whether they had consent.

    `record` = {"takeovers": n, "episodes": n, "consented": n}
    The paper separates an effective action from an acceptable one: a takeover
    can raise the score and still be a takeover (`:202`).
    """
    episodes = int(_num(record.get("episodes")))
    takeovers = _num(record.get("takeovers"))
    consented = _num(record.get("consented"))
    if episodes <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    per = takeovers / episodes
    share = (consented / takeovers) if takeovers else 1.0
    return {"format": FORMAT, "per_episode": per, "consent_share": share,
            "verdict": ("consented" if share >= 0.9
                        else "self-serving" if share < 0.5 else "mixed")}


def mitigation(record):
    """Compare mitigation arms against the control and the coordinator.

    `record` = {"control": 0..1, "coordinator": 0..1,
                "arms": {"name": 0..1, ...}}
    The decision is not "did it improve" but "did it reach the coordinator"; the
    paper's only arm that does so at small team sizes is a lead told to rank by
    value (`:217`).
    """
    control = _num(record.get("control"))
    coord = _num(record.get("coordinator"))
    arms = {k: _num(v) for k, v in (record.get("arms") or {}).items()}
    if not arms:
        return {"format": FORMAT, "verdict": "no-arms"}
    rows = [{"arm": k, "score": v, "delta": v - control,
             "reaches": v >= coord} for k, v in arms.items()]
    best = max(rows, key=lambda r: r["score"])
    return {"format": FORMAT, "control": control, "coordinator": coord,
            "arms": rows, "best": best["arm"],
            "reaches_coordinator": best["reaches"],
            "verdict": "mitigation-works" if best["delta"] > 0 else "no-effect"}


def failure(record):
    """The dominant behavioural failure among the ones the paper names.

    `record` = {"episodes": n, "stalled": n, "overrides": n, "fabrications": n,
                "unread_commit": n}
    Rates are per episode; the module names the largest and refuses to call it a
    cause, because the paper says its analyses do not establish causation
    (`:418`).
    """
    episodes = _num(record.get("episodes"))
    if episodes <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    counts = {k: _num(record.get(k)) for k in
              ("stalled", "overrides", "fabrications", "unread_commit")}
    rates = {k: v / episodes for k, v in counts.items()}
    dominant = max(rates, key=lambda k: rates[k])
    return {"format": FORMAT, "rates": rates, "dominant": dominant,
            "verdict": "measured-not-causal"}


def audit_record(record):
    """Check a formation comparison's arithmetic before trusting it."""
    findings = []
    shares = record.get("shares") or {}
    if not shares:
        findings.append("no shares supplied")
    for name, value in shares.items():
        if _num(value) > 1.0:
            findings.append("%s share above 1.0: not a share of the optimum" % name)
    if "coordinator" not in shares and shares:
        findings.append("no coordinator baseline: the comparison has no control")
    if record.get("episodes") is not None and _num(record.get("episodes")) <= 0:
        findings.append("episode count is zero")
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Recommendations from a measured formation profile."""
    findings = []
    p = profile or {}
    if p.get("gaps"):
        worst = min(p["gaps"], key=lambda k: _num(p["gaps"][k]))
        if _num(p["gaps"][worst]) < 0:
            findings.append("%s trails the coordinator by %.2f; a separate agent "
                            "per user is not a free parallelism win"
                            % (worst, -_num(p["gaps"][worst])))
    if p.get("participation_drop") is not None and _num(p.get("participation_drop")) > 0.4:
        findings.append("participation falls %.2f as the team grows; give one "
                        "agent responsibility for prioritisation" % _num(p.get("participation_drop")))
    if p.get("consent_share") is not None and _num(p.get("consent_share")) < 0.5:
        findings.append("most peer takeovers are unconsented")
    if p.get("best") and not p.get("reaches_coordinator"):
        findings.append("no mitigation reaches the coordinator; measure before "
                        "shipping a team")
    if not findings:
        findings.append("no formation, participation or mitigation measurement supplied")
    return {"format": FORMAT, "findings": findings}
