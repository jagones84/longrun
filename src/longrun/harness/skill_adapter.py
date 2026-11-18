#!/usr/bin/env python3
"""Skill adapters — the local modification, and the re-check it must survive.

Source: arXiv:2611.17007, "Skill Adapter: Personalized Modification and Online
Routing of General-Purpose Skills" (round 124). A general-purpose skill is a
shared procedure; what a particular user actually needs is a local modification
stored beside it, an Adapter `(i, p, Δ, κ)` — parent skill, applicability
conditions, the change, and the usage evidence (§Method). Two details decide
the design here:

  * the routing agent PRELOADS candidates for later DAG nodes and then
    "rechecks their applicability once actual inputs are determined" — a
    candidate prepared for assumed inputs is not applicable until the real ones
    arrive (§Online Routing);
  * every Adapter carries `κ`, its usage records and feedback, so evidence has
    an age: an adapter nobody has supported recently is retired, not trusted.
  * the ablation is the point of the module: general skills alone 41.86%,
    + composition/usage guidance 48.35%, + DAG preloading 52.75% — preloading
    is worth ~4.4 points ONLY because it is re-checked (§Ablation, Table 3).

  * `bind(skill, adapters, context)` — the applicable change, or a refusal: an
    orphan adapter, an unmet condition, two adapters editing one field.
  * `recheck(preloaded, inputs)` — keep / drop, with `stale-preload` when the
    real input differs from the assumed one.
  * `expire(adapters, today)` — evidence age, never a silent renewal.
  * `maintain(entries, events)` — reuse, remove, or revalidate a library entry.

Pure: skills and context in, resolutions out.
"""
from __future__ import annotations

import datetime as dt

FORMAT = "longrun-skill-adapter/1"


def bind(skill, adapters, context):
    """Resolve one general skill plus the adapters whose conditions hold."""
    skill = skill if isinstance(skill, dict) else {"id": str(skill or "")}
    sid = str(skill.get("id") or "")
    context = context if isinstance(context, dict) else {}
    findings, applicable = [], []
    for adapter in adapters or ():
        if not isinstance(adapter, dict):
            continue
        aid = str(adapter.get("id") or "")
        if str(adapter.get("skill") or "") != sid:
            findings.append({"kind": "adapter-orphan", "adapter": aid,
                             "skill": adapter.get("skill")})
            continue
        when = adapter.get("when") or {}
        unmet = [k for k, v in when.items() if context.get(k) != v]
        if unmet:
            findings.append({"kind": "condition-unmet", "adapter": aid,
                             "conditions": sorted(unmet)})
            continue
        if not adapter.get("evidence"):
            findings.append({"kind": "no-evidence", "adapter": aid,
                             "why": "κ is empty: the change is untested for this user"})
        applicable.append(adapter)
    if not applicable:
        return {"format": FORMAT, "skill": sid, "adapter": None, "changes": {},
                "findings": findings,
                "why": "no adapter applies; the general procedure is used"}
    changes, owner, conflict = {}, {}, []
    for adapter in applicable:
        for field, value in (adapter.get("changes") or {}).items():
            if field in changes and changes[field] != value:
                conflict.append({"field": field, "adapters": [owner[field],
                                                              str(adapter.get("id"))]})
                continue
            changes[field] = value
            owner.setdefault(field, str(adapter.get("id")))
    if conflict:
        for row in conflict:
            findings.append({"kind": "conflicting-adapters", **row,
                             "why": "two applicable adapters disagree on one field"})
        return {"format": FORMAT, "skill": sid, "adapter": None, "changes": {},
                "findings": findings,
                "why": "the harness refuses to pick a winner between two supported changes"}
    used = sorted({owner[f] for f in changes})
    return {"format": FORMAT, "skill": sid,
            "adapter": used[0] if len(used) == 1 else None,
            "adapters": used, "changes": dict(sorted(changes.items())),
            "findings": findings,
            "why": "every change is applied only under the conditions that selected it"}


def recheck(preloaded, inputs):
    """A candidate prepared for assumed inputs is not applicable until re-checked."""
    inputs = inputs if isinstance(inputs, dict) else {}
    keep, drop, findings = [], [], []
    for row in preloaded or ():
        if not isinstance(row, dict):
            continue
        ref = {"skill": str(row.get("skill") or ""), "adapter": row.get("adapter"),
               "node": row.get("node")}
        assumed = row.get("assumed")
        requires = [str(r) for r in (row.get("requires") or [])]
        missing = [r for r in requires if r not in inputs]
        if missing:
            findings.append({"kind": "input-unavailable", **ref, "inputs": missing})
            drop.append(ref)
            continue
        if assumed is None and not requires:
            findings.append({"kind": "unverifiable-preload", **ref,
                             "why": "no condition was recorded when it was prepared"})
            drop.append(ref)
            continue
        stale = [k for k, v in (assumed or {}).items() if inputs.get(k) != v]
        if stale:
            findings.append({"kind": "stale-preload", **ref, "conditions": sorted(stale)})
            drop.append(ref)
            continue
        keep.append(ref)
    return {"format": FORMAT, "keep": keep, "drop": drop, "findings": findings,
            "why": "preloading is worth nothing if the real input is never compared"}


def expire(adapters, today, ttl_days=30):
    """Evidence has an age: an adapter with no recent support is retired."""
    try:
        now = dt.date.fromisoformat(str(today))
    except ValueError:
        return {"format": FORMAT, "retire": [], "keep": [],
                "findings": [{"kind": "bad-date", "today": today}],
                "why": "no clock, no expiry decision"}
    retire, keep, findings = [], [], []
    for adapter in adapters or ():
        if not isinstance(adapter, dict):
            continue
        aid = str(adapter.get("id") or "")
        stamp = adapter.get("last_supported")
        if not stamp:
            findings.append({"kind": "no-evidence", "adapter": aid,
                             "why": "κ records no supported use"})
            retire.append(aid)
            continue
        try:
            age = (now - dt.date.fromisoformat(str(stamp))).days
        except ValueError:
            findings.append({"kind": "bad-date", "adapter": aid, "date": stamp})
            keep.append(aid)
            continue
        if age > ttl_days:
            findings.append({"kind": "evidence-expired", "adapter": aid,
                             "age_days": age, "ttl_days": ttl_days})
            retire.append(aid)
        else:
            keep.append(aid)
    return {"format": FORMAT, "retire": retire, "keep": keep, "findings": findings,
            "why": "a modification without recent support is a claim, not a capability"}


def maintain(entries, events):
    """Reuse what worked, remove what failed, revalidate what saw new inputs."""
    events = {(str(e.get("node")), str(e.get("skill")), str(e.get("adapter"))): e
              for e in (events or []) if isinstance(e, dict)}
    reuse, remove, revalidate, findings = [], [], [], []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get("node")), str(entry.get("skill")), str(entry.get("adapter")))
        ref = {"node": key[0], "skill": key[1], "adapter": key[2]}
        event = events.get(key)
        if event is None:
            findings.append({"kind": "unconfirmed-entry", **ref})
            reuse.append(ref)
            continue
        status = str(event.get("status") or "")
        if status == "ok":
            reuse.append(ref)
        elif status == "failed":
            findings.append({"kind": "failed-use", **ref})
            remove.append(ref)
        elif status == "input-changed":
            findings.append({"kind": "needs-revalidation", **ref})
            revalidate.append(ref)
        else:
            findings.append({"kind": "unknown-status", **ref, "status": status})
            revalidate.append(ref)
    return {"format": FORMAT, "reuse": reuse, "remove": remove,
            "revalidate": revalidate, "findings": findings,
            "why": "the library follows the evidence: an entry is a cache, not a commitment"}
