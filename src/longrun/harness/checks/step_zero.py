#!/usr/bin/env python3
"""Step Zero — the first processing of an opaque carrier can harm before the model sees it.

Source: arXiv:2611.01953, "Step-Zero Attack: Agent Safety Before Observability"
(round 121). An archive, a network body or an image is sealed until a tool opens
it, and the opening can write to the machine while it reads. Declared fields lie
(the decoy declares 64 bytes and carries an 8 MiB stream), so a header-reading
guard is defeated. The remedy lives at the primitive (§VII):

  * `peek(members, budget)` — a read-only opening that counts the bytes each
    member PRODUCES, stops past the budget and writes nothing;
  * `extract(members, budget, protect)` — stage, count produced bytes, refuse
    the chunk that would cross the budget, and commit by rename only when every
    member fits, so a refusal leaves the workspace untouched;
  * `bind_write(declared_name, body_sha, declared_sha, protect, allow_overwrite)`
    — the network/image side: write the body only when it matches the committed
    digest and no protected file is replaced.

Every declared field is untrusted; only produced bytes and a body digest the
sender cannot rewrite count. Pure: member records in, a decision out.
"""
from __future__ import annotations

FORMAT = "longrun-step-zero/1"
DEFAULT_BUDGET = 4 * 1024 * 1024          # 4 MiB, the paper's Bmax


def _members(members):
    return [m for m in (members or []) if isinstance(m, dict)]


def _unsafe_name(name):
    text = str(name or "")
    return (text.startswith("/") or ".." in text.split("/")
            or text in ("", ".") or str(name).endswith("/"))


def peek(members, budget=DEFAULT_BUDGET):
    """Read-only opening: count produced bytes, never write (paper Table IV, SZSP peek)."""
    budget = int(budget or DEFAULT_BUDGET)
    produced = 0
    findings = []
    rows = []
    for m in _members(members):
        name = str(m.get("name") or "")
        size = int(m.get("produced_bytes") or 0)
        if _unsafe_name(name):
            findings.append({"kind": "unsafe-member", "member": name,
                             "why": "the name escapes the destination"})
        if m.get("symlink"):
            findings.append({"kind": "symlink-member", "member": name,
                             "why": "a symlink entry can redirect a later write"})
        produced += size
        rows.append({"name": name, "produced_bytes": size,
                     "declared_size": m.get("declared_size")})
        if produced > budget:
            findings.append({"kind": "byte-budget", "produced_bytes": produced,
                             "budget": budget,
                             "why": "the stream exceeds the budget past this member"})
            break
    return {"format": FORMAT, "decision": "safe" if not findings else "refuse",
            "produced_bytes": produced, "budget": budget, "writes": 0,
            "members": rows, "findings": findings,
            "why": "a preview bounded by produced bytes, with no side effect"}


def extract(members, budget=DEFAULT_BUDGET, protect=None, allow_overwrite=False):
    """Staged extraction: commit by rename only when every produced byte fits (§VII)."""
    budget = int(budget or DEFAULT_BUDGET)
    protected = {str(p) for p in (protect or [])}
    rows = _members(members)
    findings = []
    produced = 0
    for m in rows:
        name = str(m.get("name") or "")
        if _unsafe_name(name):
            findings.append({"kind": "unsafe-member", "member": name,
                             "why": "the name escapes the destination"})
        if m.get("symlink"):
            findings.append({"kind": "symlink-member", "member": name,
                             "why": "a symlink entry can redirect a later write"})
        if name in protected and not allow_overwrite:
            findings.append({"kind": "protected-file", "member": name,
                             "why": "an existing file is replaced only on request"})
        produced += int(m.get("produced_bytes") or 0)
    if produced > budget:
        findings.append({"kind": "byte-budget", "produced_bytes": produced,
                         "budget": budget,
                         "why": "the produced stream crosses the budget before commit"})
    if findings:
        return {"format": FORMAT, "decision": "refuse", "writes": [],
                "produced_bytes": produced, "budget": budget, "findings": findings,
                "why": "a refusal leaves the workspace untouched"}
    return {"format": FORMAT, "decision": "commit",
            "writes": [str(m.get("name")) for m in rows],
            "produced_bytes": produced, "budget": budget, "findings": [],
            "why": "every member fits, so the staged tree is renamed into place"}


def bind_write(declared_name, body_sha, declared_sha, protect=None,
               allow_overwrite=False):
    """Write a fetched body only under its committed name and digest (§VII)."""
    name = str(declared_name or "")
    protected = {str(p) for p in (protect or [])}
    findings = []
    if not name:
        findings.append({"kind": "no-name", "why": "the input did not declare a name"})
    if _unsafe_name(name):
        findings.append({"kind": "unsafe-name", "member": name,
                         "why": "the declared name escapes the destination"})
    if not declared_sha:
        findings.append({"kind": "no-commitment", "why":
                         "a name without a committed digest lets the body decide what is written"})
    elif str(body_sha or "") != str(declared_sha):
        findings.append({"kind": "declaration-mismatch",
                         "body_sha": body_sha, "declared_sha": declared_sha,
                         "why": "the body is not the content the name claims"})
    if name in protected and not allow_overwrite:
        findings.append({"kind": "protected-file", "member": name,
                         "why": "an existing file is replaced only on request"})
    return {"format": FORMAT, "decision": "refuse" if findings else "write",
            "writes": [] if findings else [name], "findings": findings,
            "why": ("evidence, not the sender's field, decides the write"
                    if not findings else "the write is withheld")}
