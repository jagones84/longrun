#!/usr/bin/env python3
"""Attestation and accountability — trust in the BUILD and the RECORD.

Source: arXiv:2611.23202, "Agent Trust Infrastructure (ATI): A Federated
Identity, Trust, Attestation, and Accountability Architecture for
Cross-Organization Autonomous AI Agents" (round 132). `harness/checks/trust_boundary.py`
already judges identity, authorization and trust propagation of a CALL; this
module audits the two planes it does not: what the caller is RUNNING, and what
the allowed actions leave BEHIND.

  * **identity**: an Agent ID is the hash of the agent's public key, and a
    request with no key is refused before any agent runs
    (`agent_trust_infrastructure_2611.23202.md:95`).
  * **federation**: a certificate passes only if a federated CA signed it, the
    ID matches the signing key, the issuing CA names its own organization, the
    certificate is unexpired and the peer is not revoked (`:113`–`:123`).
  * **attestation of the build**: the running model, the pinned tool and the
    system-prompt hash must match the approved configuration (`:129`–`:133`);
    this stops model substitution (0% → 100%) and prompt tampering (27% → 100%).
  * **policy at every tool call**: cross-organization writes, replayed
    transactions and bulk exports are refused (`:149`–`:155`).
  * **accountability**: a signed hash-chained log records identity, model,
    timestamp, tool and argument hash, flags a request that reads private data
    from two offices, and cannot detect deletion from the end (`:163`–`:179`,
    `:310`).
  * **measured**: containment 43% → 84%, benign 91% → 92%, ~174 µs per request,
    and the same attack is stopped 0% on one model and 93% on another
    (`:231`, `:284`, `:302`, `:255`).

  * `identity(request)` — keyed, signed, ID derived from the key.
  * `certificate(cert, federation)` — the six trust checks.
  * `attestation(build, approved)` — the approved build is running.
  * `policy(call)` — every tool call against the three rules.
  * `accountability(entries)` — chain integrity, length anchor, signed entries.
  * `measure(rows)` — cumulative ablation, benign retention, overhead, model
    variance and the noise band.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: request, build and log records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-attestation-trust/1"

PLANES = ("identity", "trust", "attestation", "policy", "accountability")
APPROVED_FIELDS = ("model", "tools", "prompt_hash")


def _text(value):
    return str(value).strip() if value is not None else ""


def identity(request):
    """A request must carry a key, a signature and an ID derived from that key."""
    r = request or {}
    aid = _text(r.get("aid"))
    key_hash = _text(r.get("key_hash"))
    findings = []
    if not aid or not key_hash:
        findings.append({"kind": "anonymous-request",
                         "why": "a request with no key is refused before any agent runs"})
    elif aid != key_hash:
        findings.append({"kind": "aid-not-key-hash", "aid": aid, "key_hash": key_hash,
                         "why": "the identifier is the hash of the public key, not a free name"})
    if r.get("signature_ok") is False:
        findings.append({"kind": "signature-invalid",
                         "why": "the request must be signed with the private key of the claimed ID"})
    return {"format": FORMAT, "findings": findings}


def certificate(cert, federation):
    """The six checks a certificate passes before a request is trusted."""
    c = cert or {}
    fed = {str(x) for x in (federation or ())}
    findings = []
    issuer = _text(c.get("issuer"))
    org = _text(c.get("org"))
    ca_org = _text(c.get("ca_org")) or org
    if issuer and issuer not in fed:
        findings.append({"kind": "ca-not-federated", "issuer": issuer,
                         "why": "a certificate signed outside the federation is not trusted"})
    if org and ca_org and ca_org != org:
        findings.append({"kind": "issuer-vouches-other-org", "issuer": issuer, "org": org,
                         "why": "a name constraint keeps each CA inside its own namespace"})
    if _text(c.get("aid")) and _text(c.get("key_hash")) and c.get("aid") != c.get("key_hash"):
        findings.append({"kind": "aid-mismatch",
                         "why": "the certificate's ID must match the key that signed the request"})
    now = c.get("now")
    if now is not None and c.get("not_after") is not None and now > c.get("not_after"):
        findings.append({"kind": "cert-expired", "not_after": c.get("not_after")})
    if now is not None and c.get("not_before") is not None and now < c.get("not_before"):
        findings.append({"kind": "cert-not-yet-valid", "not_before": c.get("not_before")})
    if c.get("revoked"):
        findings.append({"kind": "peer-revoked",
                         "why": "a revoked partner is refused even with a valid certificate"})
    if c.get("validity_signed") is False:
        findings.append({"kind": "validity-outside-signed-payload",
                         "why": "an expiry date next to the signed data can be edited"})
    return {"format": FORMAT, "findings": findings}


def attestation(build, approved):
    """Is the approved build actually running?"""
    b = build or {}
    a = approved or {}
    findings = []
    if _text(b.get("model")) != _text(a.get("model")):
        findings.append({"kind": "model-substituted", "running": b.get("model"),
                         "approved": a.get("model"),
                         "why": "a swapped model keeps a valid certificate"})
    running_tools = {str(x) for x in (b.get("tools") or ())}
    approved_tools = {str(x) for x in (a.get("tools") or ())}
    if running_tools != approved_tools:
        findings.append({"kind": "tool-tampered",
                         "extra": sorted(running_tools - approved_tools),
                         "missing": sorted(approved_tools - running_tools),
                         "why": "a poisoned tool is not in the approved inventory"})
    if _text(b.get("prompt_hash")) != _text(a.get("prompt_hash")):
        findings.append({"kind": "prompt-tampered",
                         "why": "the system prompt is part of the approved build"})
    if b.get("host_trusted") is False:
        findings.append({"kind": "attestation-host-reported",
                         "why": "a compromised host can falsify its own measurements"})
    return {"format": FORMAT, "findings": findings}


def policy(call):
    """Every tool call is checked, not only the entry request."""
    c = call or {}
    kind = _text(c.get("kind")).lower()
    findings = []
    if kind == "write" and _text(c.get("origin_org")) and _text(c.get("target_org")) \
            and c.get("origin_org") != c.get("target_org"):
        findings.append({"kind": "cross-org-write",
                         "why": "an organization may read a partner's data but not write it"})
    if kind == "write" and c.get("processed"):
        findings.append({"kind": "replay",
                         "why": "an already-processed transaction is not processed again"})
    if kind == "read" and c.get("sensitive") and int(c.get("records") or 0) > int(c.get("cap") or 1):
        findings.append({"kind": "bulk-export", "records": c.get("records"), "cap": c.get("cap"),
                         "why": "a sensitive office caps a read at one record"})
    offices = {str(x) for x in (c.get("offices_read") or ())}
    if kind == "read" and len(offices) >= 2:
        findings.append({"kind": "separation-of-duties", "offices": sorted(offices),
                         "why": "a single request reading two offices is flagged, not refused"})
    if c.get("legitimate") is None and c.get("observable") == "identical":
        findings.append({"kind": "policy-cannot-distinguish",
                         "why": "a rule cannot separate collusion from a legitimate multi-office task"})
    return {"format": FORMAT, "findings": findings}


def accountability(entries):
    """A signed hash chain, its silent end, and the key it assumes."""
    rows = list(entries or ())
    findings = []
    prev = None
    for idx, e in enumerate(rows):
        if prev is not None and _text(e.get("prev_hash")) != _text(prev):
            findings.append({"kind": "chain-broken", "index": idx,
                             "why": "each entry carries the hash of the entry before it"})
            break
        if e.get("signature_ok") is False:
            findings.append({"kind": "unsigned-entry", "index": idx,
                             "why": "an entry is signed by the organization where the action happened"})
        prev = e.get("hash")
    if not rows:
        findings.append({"kind": "no-record",
                         "why": "an allowed action with no log entry cannot be attributed"})
    if not any(e.get("length_anchor") for e in rows):
        findings.append({"kind": "chain-end-unpinned",
                         "why": "an append-only chain cannot detect deletion from the end"})
    if any(e.get("log_key_shared") for e in rows):
        findings.append({"kind": "log-key-assumed",
                         "why": "a stolen signing key can construct an alternative valid log"})
    return {"format": FORMAT, "entries": len(rows), "findings": findings}


def measure(rows):
    """Cumulative ablation: containment, benign retention, overhead, model variance."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurement"}]}
    planes = [p for p in PLANES if any(str(r.get("plane")) == p for r in data)]
    gains = {}
    for r in data:
        plane = str(r.get("plane"))
        if r.get("containment") is None:
            continue
        gains.setdefault(plane, []).append(r.get("containment"))
    for plane, values in gains.items():
        if len(values) >= 2 and values[-1] <= values[0]:
            findings.append({"kind": "no-containment-gain", "plane": plane,
                             "why": "a plane that stops nothing it targets is not a control"})
        elif len(values) >= 2:
            findings.append({"kind": "plane-adds-containment", "plane": plane,
                             "gain": round(values[-1] - values[0], 4)})
    benign = [r for r in data if r.get("benign") is not None]
    if len(benign) >= 2:
        before, after = benign[0]["benign"], benign[-1]["benign"]
        if after < before - 0.05:
            findings.append({"kind": "benign-lost", "before": before, "after": after,
                             "why": "a control that breaks normal work is a cost, not a gain"})
        else:
            findings.append({"kind": "benign-retained", "before": before, "after": after})
    overhead = [r.get("overhead_us") for r in data if r.get("overhead_us") is not None]
    if overhead:
        findings.append({"kind": "overhead-measured", "us": max(overhead)})
    models = [r for r in data if r.get("model")]
    if len({str(r["model"]) for r in models}) <= 1 and models:
        findings.append({"kind": "single-model-evaluation",
                         "why": "the same attack is stopped by one model and executed by another"})
    elif models:
        stop = {}
        for r in models:
            stop.setdefault(str(r["model"]), []).append(r.get("stopped"))
        spread = []
        for values in stop.values():
            values = [v for v in values if v is not None]
            if values:
                spread.append(sum(values) / len(values))
        if spread and max(spread) - min(spread) >= 0.4:
            findings.append({"kind": "model-variance-misjudges",
                             "spread": round(max(spread) - min(spread), 4),
                             "why": "a single-model evaluation would misjudge the system"})
    untargeted = [r for r in data if r.get("targeted") is False and r.get("containment") is not None]
    if len(untargeted) >= 2:
        lo = min(r["containment"] for r in untargeted)
        hi = max(r["containment"] for r in untargeted)
        if hi - lo >= 0.10:
            findings.append({"kind": "noise-band", "low": lo, "high": hi,
                             "why": "swings with no mechanism behind them set the table's noise level"})
    return {"format": FORMAT, "planes": planes, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("verifies_build", "build-unverified", "a valid identity says nothing about the running model or prompt"),
        ("checks_every_call", "entry-only-policy", "permissions checked once at the door miss the tool call"),
        ("signed_hash_chain", "no-tamper-evident-log", "an unsigned record cannot attribute an action"),
        ("pins_chain_length", "chain-end-unpinned", "deletion from the end leaves no trace"),
        ("federated_certificates", "no-federation", "a peer cannot verify the caller without a shared CA"),
        ("multi_model_evaluation", "single-model-evaluation", "model safety varies enough to misjudge the system"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
