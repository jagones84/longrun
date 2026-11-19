#!/usr/bin/env python3
"""Write integrity — the policy comes from schemas, the values from the request.

Source: arXiv:2611.17115, "CapLite: Prompt-Injection Defense for Small Language
Model Agents without Model-Written Security Artifacts" (round 155). When the
agent's own model writes the security artifact (a program, a policy, a graph),
its mistakes become admitted attacks: the policies of 15 open-weight models
admitted 676 attacks, IPIGuard 435 and DRIFT 214
(`caplite_write_integrity_2611.17115.txt:18`, `:80`).

  * **the policy is derived from tool schemas**: read verbs, effect verbs,
    unclassified tools denied, and every write argument is an authority field
    unless the schema marks it payload, temporal or control (`:514`, `:521`).
  * **writes are committed before any tool result is read**, and no later
    component may add, remove or reorder them (`:540`, `:544`).
  * **grounding is exact**: every authority argument must equal a value the
    request states; a substring does not count, and 1 is not grounded by 100
    (`:505`, `:1154`).
  * **two guarantees hold by construction**: executed writes are a prefix of the
    committed writes, and every authority argument is grounded (`:530`).
  * **the Mediator is load-bearing**: removing it admits 106 attacks in 7,432
    episodes while benign utility rises 5.6 points (`:772`, `:793`).

  * `policy(record)` — schema-derived tool class and argument roles.
  * `grounding(request)` — the grounding set G(q), canonicalised.
  * `commit(plan)` — the committed write prefix.
  * `mediate(call, ...)` — execute / deny / ask, in the paper's check order.
  * `integrity(trace)` — re-derive the two guarantees over a logged episode.
  * `ablate(record)` — which component carries security, and at what utility.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: schemas, requests, plans and traces in; decisions and verdicts out.
"""
from __future__ import annotations

import re

from longrun.harness import tool_policy

FORMAT = "longrun-write-integrity/1"

# ONE classifier: the shared module owns the verb lists and the argument roles.
# Kept as module aliases so existing callers keep resolving the names.
READ_VERBS = tool_policy.READ_VERBS
EFFECT_VERBS = tool_policy.EFFECT_VERBS
PAYLOAD_NAMES = tool_policy.PAYLOAD_NAMES
DESTINATION_HINTS = tool_policy.DESTINATION_HINTS
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{8,30}\b")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s\"<>]+")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
QUOTED_RE = re.compile(r"[\"'`]([^\"'`]{1,80})[\"'`]")


def _canon(value):
    text = str(value).strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def policy(record):
    """A tool's class and its argument roles, from the schema alone."""
    p = tool_policy.classify(record or {})
    kind = "read" if p["kind"] in ("local-read", "external-read") else p["kind"]
    return {"format": FORMAT, "kind": kind, "roles": p["roles"], "enum": p["enum"],
            "denied": kind == "unclassified", "verdict": "classified"}


def grounding(request):
    """G(q): the values and n-grams the request itself states."""
    text = str(request or "")
    if not text.strip():
        return {"format": FORMAT, "verdict": "empty-request"}
    values = set()
    for rx in (EMAIL_RE, IBAN_RE, URL_RE, DATE_RE, NUMBER_RE):
        for match in rx.findall(text):
            values.add(_canon(match))
    for quoted in QUOTED_RE.findall(text):
        values.add(_canon(quoted))
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9@._%+-]*", text)
    tokens = [_canon(t) for t in tokens]
    for n in range(1, 9):
        for i in range(len(tokens) - n + 1):
            values.add(" ".join(tokens[i:i + n]))
    return {"format": FORMAT, "values": sorted(values), "count": len(values),
            "verdict": "grounded"}


def grounded(value, ground):
    """Exact membership after canonicalisation; a substring never counts."""
    g = ground or {}
    values = {_canon(v) for v in (g.get("values") or [])}
    return _canon(value) in values


def commit(plan):
    """The Planner's writes, fixed before any read; at most ten calls."""
    p = plan or {}
    calls = list(p.get("calls") or [])
    if len(calls) > 10:
        return {"format": FORMAT, "verdict": "too-many-calls"}
    writes = [c for c in calls
              if policy(c.get("tool") or c).get("kind") == "write"]
    return {"format": FORMAT, "calls": len(calls), "writes": writes,
            "count": len(writes), "fixed": True, "verdict": "committed"}


def append(plan, call):
    """A committed plan never grows."""
    return {"format": FORMAT, "appended": False,
            "verdict": "replanning-refused"}


def _placeholder(value):
    text = str(value)
    return text.startswith("$") or (text.startswith("{{") and text.endswith("}}"))


def mediate(call, ground, plan=None, schema=None):
    """The deterministic checks, in order; the first denial stops the writes."""
    c = call or {}
    tool = c.get("tool") or {}
    kind = str(c.get("kind") or policy(tool).get("kind"))
    if kind == "unclassified":
        return {"format": FORMAT, "decision": "deny", "reason": "unclassified-tool"}
    params = c.get("params") or {}
    if any(_placeholder(v) for v in params.values()):
        return {"format": FORMAT, "decision": "deny", "reason": "placeholder"}
    roles = policy(tool).get("roles") or {}
    required = set((schema or tool.get("required") or []))
    missing = [name for name in required if name not in params]
    if missing:
        return {"format": FORMAT, "decision": "deny", "reason": "schema",
                "missing": sorted(missing)}
    enum = policy(tool).get("enum") or {}
    if kind == "read":
        for name, value in params.items():
            if any(h in name.lower() for h in DESTINATION_HINTS) and \
                    not grounded(value, ground):
                return {"format": FORMAT, "decision": "deny",
                        "reason": "ungrounded-destination", "argument": name}
    for name, value in params.items():
        role = roles.get(name, "authority")
        if role == "authority":
            if kind == "read" and any(h in name.lower() for h in DESTINATION_HINTS):
                continue
            if not grounded(value, ground):
                return {"format": FORMAT, "decision": "ask",
                        "reason": "ungrounded-authority", "argument": name}
        elif role == "control" and name in enum and value not in enum[name]:
            return {"format": FORMAT, "decision": "deny",
                    "reason": "control-value", "argument": name}
    if plan is not None:
        writes = [w for w in plan.get("writes") or []
                  if str(w.get("tool", {}).get("name")) == str(tool.get("name"))]
        if writes and kind == "write":
            if not any(w.get("params") == params for w in writes):
                return {"format": FORMAT, "decision": "deny",
                        "reason": "not-committed"}
    return {"format": FORMAT, "decision": "execute", "verdict": "admitted"}


def integrity(trace):
    """Re-derive the two guarantees from a logged episode."""
    t = trace or {}
    committed = [c for c in t.get("committed") or []]
    executed = [c for c in t.get("executed") or []]
    writes = [c for c in executed
              if str(c.get("kind") or policy(c.get("tool") or {}).get("kind"))
              == "write"]
    violations = []
    for i, call in enumerate(writes):
        if i >= len(committed):
            violations.append({"kind": "uncommitted-write", "index": i})
            continue
        expected = committed[i]
        if str(expected.get("tool", {}).get("name")) != \
                str(call.get("tool", {}).get("name")):
            violations.append({"kind": "write-order", "index": i})
        ground = t.get("ground") or {}
        for name, value in (call.get("params") or {}).items():
            role = policy(call.get("tool") or {}).get("roles", {}).get(name,
                                                                       "authority")
            if role == "authority" and not grounded(value, ground):
                violations.append({"kind": "ungrounded-authority",
                                   "index": i, "argument": name})
    return {"format": FORMAT, "writes": len(writes),
            "violations": violations,
            "verdict": "trace-clean" if not violations else "violations"}


def ablate(record):
    """Which component carries the security, and what utility it costs."""
    r = record or {}
    base = r.get("base") or {}
    variants = r.get("variants") or {}
    if not base:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    rows = {}
    for name, value in variants.items():
        v = value or {}
        episodes = _num(v.get("episodes") or base.get("episodes"))
        attacks = _num(v.get("attacks"))
        if not episodes or attacks is None:
            continue
        rows[name] = {"asr": attacks / episodes,
                      "k": int(attacks), "episodes": int(episodes),
                      "bu": _num(v.get("bu")), "ua": _num(v.get("ua"))}
    if not rows:
        return {"format": FORMAT, "verdict": "no-variants"}
    worst = max(rows.items(), key=lambda kv: kv[1]["asr"])
    return {"format": FORMAT, "variants": rows,
            "load_bearing": worst[0] if worst[1]["asr"] > 0 else None,
            "verdict": "ablated"}


def audit_record(record):
    """The misreadings the paper's threat model and results exclude."""
    r = record or {}
    findings = []
    if r.get("model_written_policy") is True:
        findings.append({"kind": "model-written-policy",
                         "why": "its mistakes become admitted attacks"})
    if r.get("replanning_allowed") is True:
        findings.append({"kind": "replanning-allowed",
                         "why": "a write added after reading is exactly the channel"})
    if r.get("substring_grounding") is True:
        findings.append({"kind": "substring-grounding",
                         "why": "an attacker can place a phrase of the request"})
    if r.get("record_grounding") is True:
        findings.append({"kind": "record-grounding",
                         "why": "a planted record carrying the request phrase opens a channel"})
    if r.get("payload_checked_as_authority") is True:
        findings.append({"kind": "payload-checked-as-authority",
                         "why": "the payload is written by the composer, not by the user"})
    if r.get("attack_labels_used_for_tuning") is True:
        findings.append({"kind": "attack-labels-for-tuning",
                         "why": "the guarantee must not depend on the attacks seen"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the write-integrity gaps the paper names."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("derives_policy_from_schemas", "lets_the_model_write_the_policy",
         "a generated policy is wrong in both directions"),
        ("commits_writes_before_reading", "plans_after_observations",
         "an injected observation must not add a write"),
        ("checks_authority_values_for_exact_grounding", "checks_a_substring",
         "a substring is attacker-placeable"),
        ("asks_when_an_authority_value_is_unstated", "guesses_or_drops_the_task",
         "a confirmation costs less than a forged recipient"),
        ("halts_after_the_first_denial", "continues_after_a_denial",
         "later writes assume the denied step happened"),
        ("keeps_a_trace_audit", "trusts_the_runtime_alone",
         "the guarantee should be checkable outside the running agent"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
