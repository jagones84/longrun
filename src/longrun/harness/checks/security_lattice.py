#!/usr/bin/env python3
"""Compositional security — a two-axis label, not a boolean taint flag.

Source: arXiv:2611.13960, "From Attack Surface to Defense Architecture:
Compositional Security for Agentic Coding Harnesses" (round 125). Two measurements
shape this module. First, a coarse boolean taint lock closes every kill chain and
blocks **83.3% of benign issue-driven workflows**, while the product lattice keeps
both at ABR 1.000 / FPR 0.000 (§5.4, Table 5). Second, a live 4B LLM judge
reaches ABR 1.000 only by refusing **98.3% of benign work at 142.3 ms**, whereas
the deterministic ring decides in 12.7 µs (Table 4). Security at the execution
boundary is therefore a structural, two-axis property, not a judgement call.

The lattice is `L = Ltrust × Lsens` with componentwise join:
`trusted ⊑ sanitized ⊑ derived ⊑ untrusted` and `public ⊑ sensitive` (§3.2).
Reading external content raises trust; reading secrets raises sensitivity; the
two axes never collapse into one flag — which is exactly what lets an agent read
an untrusted issue, then edit the workspace and run ISOLATED tests, while
arbitrary shells and egress stay closed.

  * `join(a, b)` / `sanitize(label)` / `declassify(label, authorized)` —
    sanitization lowers trust only; **redaction with authority is the only path
    that clears sensitivity** (§3.2).
  * `admit(label, action)` — the action-class gate.
  * `attenuate(parent, child)` — delegation may add caveats, never widen them
    (§3.1, Definition 3.2).
  * `ledger_read` / `ledger_write` / `admit_effect` — workspace provenance:
    a writer's label joins into the file, a reader's label joins from it, and
    the Lethal Trifecta becomes a check over composed state (§3.2, Def. 3.4).

Pure: labels in, decisions out. The paper's HMAC tokens and OS guards are not
implemented here; only the algebra they enforce.
"""
from __future__ import annotations

FORMAT = "longrun-security-lattice/1"
TRUST = ("trusted", "sanitized", "derived", "untrusted")
SENS = ("public", "sensitive")
PUBLIC_SAFE = ("read_workspace", "write_workspace", "extract", "test_isolated")
TRIFECTA = ("read_sensitive", "shell_arbitrary", "net_egress", "exec_process")


def _rank(order, value):
    try:
        return order.index(str(value))
    except ValueError:
        return len(order) - 1          # an unknown level is the worst case, never a pass


def label(trust="trusted", sens="public"):
    return {"trust": str(trust), "sens": str(sens)}


def join(a, b):
    """Componentwise join: trust takes the higher rank, sensitivity the higher one."""
    a = a if isinstance(a, dict) else {}
    b = b if isinstance(b, dict) else {}
    return label(TRUST[max(_rank(TRUST, a.get("trust")), _rank(TRUST, b.get("trust")))],
                 SENS[max(_rank(SENS, a.get("sens")), _rank(SENS, b.get("sens")))])


def sanitize(value):
    """Structural cleaning lowers trust; it NEVER clears sensitivity."""
    value = value if isinstance(value, dict) else {}
    trust = str(value.get("trust") or "untrusted")
    if trust in ("derived", "untrusted"):
        trust = "sanitized"
    return {"format": FORMAT, "label": label(trust, value.get("sens") or "public"),
            "why": "sanitization is representational, not a declassification"}


def declassify(value, authorized=False):
    """Only an authorized redaction may clear sensitivity."""
    value = value if isinstance(value, dict) else {}
    if not authorized:
        return {"format": FORMAT, "allowed": False,
                "label": label(value.get("trust"), value.get("sens")),
                "findings": [{"kind": "no-authority",
                              "why": "clearing sensitivity needs an authorizing principal"}],
                "why": "an agent cannot declassify its own input"}
    return {"format": FORMAT, "allowed": True,
            "label": label(value.get("trust"), "public"),
            "findings": [], "why": "redaction with authority is the only declassification"}


def admit(value, action):
    """The action-class gate over the product label."""
    value = value if isinstance(value, dict) else {}
    action = str(action or "")
    trust = str(value.get("trust") or "untrusted")
    sens = str(value.get("sens") or "public")
    allowed, findings = True, []
    if action in ("shell_arbitrary", "net_egress") and sens == "sensitive":
        allowed = False
        findings.append({"kind": "sensitive-flow", "action": action,
                         "why": "arbitrary execution and egress are closed while carrying secrets"})
    elif trust == "untrusted" and action not in ("read_workspace",):
        allowed = False
        findings.append({"kind": "untrusted-input", "action": action,
                         "why": "untrusted provenance permits local inspection only"})
    elif trust in ("sanitized", "derived") and action not in PUBLIC_SAFE + ("read_sensitive",):
        allowed = False
        findings.append({"kind": "needs-trusted-provenance", "action": action,
                         "trust": trust})
    return {"format": FORMAT, "allowed": allowed, "action": action,
            "label": label(trust, sens), "findings": findings,
            "why": ("permitted at this label" if allowed
                    else "the label, not the wording of the request, decides")}


def attenuate(parent, child):
    """A child capability must not widen any dimension of its parent."""
    parent = parent if isinstance(parent, dict) else {}
    child = child if isinstance(child, dict) else {}
    findings = []
    for key in ("tools", "paths", "cidrs"):
        p = {str(x) for x in (parent.get(key) or [])}
        c = {str(x) for x in (child.get(key) or [])}
        extra = sorted(c - p)
        if extra:
            findings.append({"kind": "widened-" + key, "extra": extra})
    if float(child.get("ttl_s") or 0) > float(parent.get("ttl_s") or 0):
        findings.append({"kind": "ttl-extended",
                         "parent": parent.get("ttl_s"), "child": child.get("ttl_s")})
    if float(child.get("quota") or 0) > float(parent.get("quota") or 0):
        findings.append({"kind": "quota-raised",
                         "parent": parent.get("quota"), "child": child.get("quota")})
    return {"format": FORMAT, "valid": not findings, "findings": findings,
            "why": ("delegation only adds caveats" if not findings
                    else "a child that widens its parent is a new principal")}


def _actor(actor):
    actor = dict(actor) if isinstance(actor, dict) else {}
    actor["label"] = label((actor.get("label") or {}).get("trust", "trusted"),
                           (actor.get("label") or {}).get("sens", "public"))
    actor["effects"] = sorted({str(e) for e in (actor.get("effects") or [])})
    return actor


def ledger_write(ledger, path, actor):
    """A write joins the writer's label into the file and absorbs its effects."""
    ledger = dict(ledger or {})
    actor = _actor(actor)
    path = str(path)
    row = ledger.get(path) or {"label": label(), "effects": []}
    ledger[path] = {"label": join(row.get("label"), actor["label"]),
                    "effects": sorted(set(row.get("effects") or []) | set(actor["effects"]))}
    return {"format": FORMAT, "ledger": ledger, "path": path,
            "label": ledger[path]["label"],
            "why": "shared workspace state is where two bounded agents compose"}


def ledger_read(ledger, path, actor):
    """A read joins the file's label into the reader and absorbs its effects."""
    actor = _actor(actor)
    path = str(path)
    row = (ledger or {}).get(path)
    if not row:
        return {"format": FORMAT, "actor": actor, "found": False,
                "findings": [{"kind": "unlabelled-path", "path": path,
                              "why": "an unlabelled file is treated as untrusted"}],
                "why": "no provenance, no trust"}
    actor["label"] = join(actor["label"], row.get("label"))
    actor["effects"] = sorted(set(actor["effects"]) | set(row.get("effects") or []))
    return {"format": FORMAT, "actor": actor, "found": True,
            "label": actor["label"], "findings": [],
            "why": "provenance travels with the data, across agents and files"}


def admit_effect(actor, effect):
    """The Lethal Trifecta as a deterministic check over composed state."""
    actor = _actor(actor)
    effect = str(effect or "")
    sensitive = actor["label"].get("sens") == "sensitive" or "read_sensitive" in actor["effects"]
    closing = sensitive and effect in ("shell_arbitrary", "net_egress", "exec_process")
    findings = [{"kind": "lethal-trifecta", "effect": effect,
                 "why": "sensitive material plus egress or execution is the trifecta"}] if closing else []
    if closing:
        return {"format": FORMAT, "allowed": False, "effect": effect,
                "findings": findings,
                "why": "Agent A can read a secret, write it, and Agent B cannot send it out"}
    return {"format": FORMAT, "allowed": True, "effect": effect, "findings": [],
            "effects": sorted(set(actor["effects"]) | {effect}),
            "why": "the resulting state does not close a toxic combination"}
