#!/usr/bin/env python3
"""Intake gate — who may start work, under what mandate, and in which mode.

Source: Sam Witteveen, "NEW DeepSeek Harness - Super Agent!" (2026-11-03,
`youtube.com/watch?v=OrcsMi2-IcM`, transcript S-2026-11-19-052). A four-part
description of the DeepSeek super-agent design, each part a rule this module
makes deterministic:

  * every outside trigger passes a GATE that is code, not a model: is this
    author allowed, is the message actually addressed to the agent, was it
    already answered (t. 148-151);
  * a ticket carries a MANDATE — who asked, under which rules, how far the
    worker may go (t. 152-154);
  * once a worker owns a ticket it subscribes to that conversation directly;
    routing comments back through the orchestrator raised router decisions by
    30% when disabled (t. 154-158);
  * work nobody asked for starts in RECORD mode: it writes what it would have
    done, confirms it, and speaks only when there is a result or a decision
    (t. 181-184).

The speaker marks the benchmark numbers (30 tasks, 17.5x cost spread, a 63.3%
tie at $3.28 vs $18.34 per solved task) as a rough guide on synthetic workloads
(t. 64-77, 198-203) — they are context for the rules, not measured here.

  * `admit(trigger, policy)` — route / shadow / ignore, before any model call.
  * `mandate(ticket, today)` — a bounded, attributable, unexpired authority.
  * `subscribe(events, owned)` — which events skip the orchestrator.
  * `preset(base, strip)` — the worker preset, and capability leaks.

Pure: records in, decisions out.
"""
from __future__ import annotations

import datetime as dt

FORMAT = "longrun-intake-gate/1"


def admit(trigger, policy):
    """A deterministic gate decides before the model ever sees the trigger."""
    trigger = trigger if isinstance(trigger, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    source = str(trigger.get("source") or "")
    author = str(trigger.get("author") or "")
    allowed = policy.get("allowed") or {}
    findings = []
    if author not in (allowed.get(source) or []):
        findings.append({"kind": "not-allowed", "source": source, "author": author,
                         "why": "the author is not on this source's allow-list"})
        return {"format": FORMAT, "decision": "ignore", "findings": findings,
                "why": "the gate is code: it answers before a token is spent"}
    if trigger.get("already_answered"):
        findings.append({"kind": "duplicate", "why": "this trigger was answered already"})
        return {"format": FORMAT, "decision": "ignore", "findings": findings,
                "why": "answering twice spends attention nobody asked for"}
    addressed = str(trigger.get("addresses") or "") == "agent"
    if not addressed and policy.get("require_address", True):
        findings.append({"kind": "not-addressed",
                         "why": "the message does not address the agent"})
        if not policy.get("shadow_unrequested", True):
            return {"format": FORMAT, "decision": "ignore", "findings": findings,
                    "why": "unaddressed work is not started when shadowing is off"}
        findings.append({"kind": "unrequested-work",
                         "why": "allowed but unaddressed: record first, speak later"})
        return {"format": FORMAT, "decision": "shadow", "findings": findings,
                "why": "take as little human attention as possible"}
    return {"format": FORMAT, "decision": "route", "findings": findings,
            "why": "allowed, addressed, not a duplicate"}


def mandate(ticket, today=None):
    """A ticket must state who asked, under which rules, and how far it may go."""
    ticket = ticket if isinstance(ticket, dict) else {}
    findings = []
    if not ticket.get("requester"):
        findings.append({"kind": "missing-requester"})
    if not (ticket.get("rules") or []):
        findings.append({"kind": "no-rules",
                         "why": "no rule was cited for the work"})
    scope = ticket.get("scope") or {}
    if not (scope.get("tools") or scope.get("paths")):
        findings.append({"kind": "unbounded-scope",
                         "why": "nothing bounds what the worker may touch"})
    if today is not None and ticket.get("expires"):
        try:
            if dt.date.fromisoformat(str(ticket["expires"])) < dt.date.fromisoformat(str(today)):
                findings.append({"kind": "expired", "expires": ticket["expires"]})
        except ValueError:
            findings.append({"kind": "bad-date", "expires": ticket["expires"]})
    return {"format": FORMAT, "valid": not findings,
            "ticket": str(ticket.get("id") or ""), "findings": findings,
            "why": ("bounded, attributable and current"
                    if not findings else "a worker without a bounded mandate is an unbounded agent")}


def subscribe(events, owned):
    """An owned ticket bypasses the orchestrator; the router keeps only the rest."""
    owned = {str(k): str(v) for k, v in (owned or {}).items()}
    direct, routed, findings = [], [], []
    for event in events or ():
        if not isinstance(event, dict):
            continue
        ticket = str(event.get("ticket") or "")
        row = {"ticket": ticket, "kind": str(event.get("kind") or ""),
               "worker": owned.get(ticket)}
        if ticket and ticket in owned:
            direct.append(row)
        else:
            routed.append(row)
            findings.append({"kind": "router-hop", "ticket": ticket,
                             "why": "no worker owns this ticket, so the router must decide"})
    total = len(direct) + len(routed)
    share = round(len(routed) / total, 4) if total else 0.0
    return {"format": FORMAT, "direct": direct, "via_router": routed,
            "router_share": share, "findings": findings,
            "why": "a subscribed worker skips the orchestration layer and its tokens"}


def preset(base, strip, background_shell_s=5):
    """The worker preset is the standard one MINUS capabilities it must not need."""
    base = base if isinstance(base, dict) else {}
    strip = [str(s) for s in (strip or [])]
    capabilities = sorted(set(str(c) for c in (base.get("capabilities") or [])) - set(strip))
    reachable = {str(t.get("name")): set(str(c) for c in (t.get("capabilities") or []))
                 for t in (base.get("tools") or []) if isinstance(t, dict)}
    findings = []
    for name in strip:
        for tool, caps in reachable.items():
            if name in caps:
                findings.append({"kind": "capability-leak", "capability": name, "tool": tool,
                                 "why": "stripped from the preset but still reachable"})
    return {"format": FORMAT, "capabilities": capabilities,
            "tools": sorted(reachable), "background_shell_s": int(background_shell_s),
            "findings": findings,
            "why": "a worker that cannot ask, plan or fetch is a worker that finishes the ticket"}


def shadow(actions, confirmed=False):
    """Unrequested work records what it would have done and waits to speak."""
    recorded, findings = [], []
    for action in actions or ():
        if not isinstance(action, dict):
            continue
        row = {"id": str(action.get("id") or ""), "kind": str(action.get("kind") or ""),
               "would": str(action.get("would") or "")}
        if not action.get("recorded", True):
            findings.append({"kind": "unrecorded-action", "id": row["id"]})
        recorded.append(row)
    if not confirmed:
        findings.append({"kind": "no-confirmation",
                         "why": "nothing has confirmed that the recorded plan works"})
    return {"format": FORMAT, "mode": "speak" if confirmed else "record",
            "actions": recorded, "findings": findings,
            "why": ("a result or a decision exists, so it is worth the attention"
                    if confirmed else "no result yet: recording costs no attention")}
