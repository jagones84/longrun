#!/usr/bin/env python3
"""Domain-scoped harness adapters — named-field deltas that compose (RSI, I-5).

Source: B. Chen et al., *Beyond Weight Updates: Evolving Agent Harnesses for
Domain Specialization*, arXiv:2611.25380 (2026), §3.4–§3.5 and Eq. 4. The paper
optimises the harness instead of the weights: a genotype is a STRUCTURED set of
named fields (system prompt, tool schemas, skill library, exemplars, planning),
a reflective evolutionary outer loop edits one field per mutation, and the
output is a portable, DOMAIN-SCOPED adapter. Adapters compose when their edited
fields are disjoint; an overlapping field is a right-biased override (the later
adapter wins) — never a silent collision. Eq. 4 adds the retention constraint:
specialising one domain may not destroy prior capability, which the paper
measures as the off-target columns staying near the base (its Table 4).

Longrun already has the pieces the adapter is made of (a rules proposal, a
mined skill, a Matrix bundle, a registry delta) but no name for the composed
object and no check that two specialisations do not collide or regress each
other. This module is that seam. It is read-only: `from_proposal()` maps an
existing improvement record onto the field it edits, `genotype()` composes the
adapters a round would apply, and `retention()` answers the constraints.

No model call, no network, stdlib only.
"""
import re

#: The genotype of arXiv:2611.25380 §3.4 — one field per kind of harness edit.
FIELDS = ("system_prompt", "tool_schema", "skill", "exemplar", "planning")

#: The paper's Eq. 4 tolerance: an off-target success rate may not drop by more
#: than this when a domain adapter is loaded (its Table 4 largest change: 1 pt).
RETENTION_TOLERANCE = 0.01

#: Proposal scope / candidate kind -> the harness field the edit lands in.
SCOPE_FIELDS = {"project": "system_prompt", "global": "system_prompt",
                "skill": "skill", "matrix": "tool_schema",
                "registry": "tool_schema"}
KIND_FIELDS = {"guardrail": "system_prompt", "skill": "skill",
               "matrix": "tool_schema"}

#: An edit is a body an agent will read, not a document store: refuse rather
#: than silently cut one.
MAX_EDIT = 20000


def _slug(text, fallback):
    raw = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").strip().lower()).strip("-")
    return (raw or fallback)[:64]


def field_for(name):
    """The harness field a scope/kind edits, or '' when it edits none."""
    key = str(name or "").strip().lower()
    if key in SCOPE_FIELDS:
        return SCOPE_FIELDS[key]
    if key in KIND_FIELDS:
        return KIND_FIELDS[key]
    if key.startswith("matrix_"):
        return "tool_schema"
    return ""


def adapter(name, domain, edits):
    """One domain-scoped adapter: {name, domain, edits:{field: body}}.

    `edits` must be non-empty and name only fields in `FIELDS`; an unknown field
    is refused because the genotype is a fixed vocabulary, not free text. The
    name and domain are slugs, so two spellings of one domain cannot become two
    adapters.
    """
    if not isinstance(edits, dict) or not edits:
        return {"ok": False, "error": "an adapter needs at least one field edit"}
    clean = {}
    for field, body in edits.items():
        key = str(field or "").strip().lower()
        if key not in FIELDS:
            return {"ok": False,
                    "error": "unknown harness field %r (expected one of %s)"
                             % (field, ", ".join(FIELDS))}
        text = str(body or "")
        if not text.strip():
            return {"ok": False, "error": "empty body for field %r" % key}
        if len(text) > MAX_EDIT:
            return {"ok": False, "error": "body for field %r is %d chars (max %d)"
                    % (key, len(text), MAX_EDIT)}
        clean[key] = text
    return {"ok": True,
            "adapter": {"name": _slug(name, "adapter"),
                        "domain": _slug(domain, "general"),
                        "edits": clean,
                        "fields": sorted(clean)}}


def conflicts(a, b):
    """The fields two adapters both edit ([] when they compose cleanly)."""
    fa = set((a or {}).get("edits") or {})
    fb = set((b or {}).get("edits") or {})
    return sorted(fa & fb)


def compose(adapters):
    """Merge adapters: disjoint fields add, an overlap is a RIGHT-BIASED override.

    The paper (§3.5) defines composition when the edited fields are disjoint and
    a right-biased override for overlaps. Every override is recorded with both
    adapter names, so two specialisations that collide are visible instead of
    one silently winning. An invalid adapter refuses the whole load.
    """
    genotype, applied, overrides = {}, [], []
    for ad in adapters or []:
        if not isinstance(ad, dict) or not isinstance(ad.get("edits"), dict):
            return {"ok": False, "error": "not an adapter: %r" % (ad,)}
        for field in ad["edits"]:
            if field not in FIELDS:
                return {"ok": False, "error": "unknown harness field %r" % field}
        name = str(ad.get("name") or "adapter")
        for field, body in ad["edits"].items():
            if field in genotype:
                overrides.append({"field": field, "from": genotype[field]["by"],
                                  "to": name})
            genotype[field] = {"body": body, "by": name}
        applied.append({"name": name, "domain": str(ad.get("domain") or "general"),
                        "fields": list(ad.get("fields") or sorted(ad["edits"]))})
    return {"ok": True, "genotype": genotype,
            "fields": sorted(genotype), "applied": applied,
            "overrides": overrides}


def retention(before, after, tolerance=None):
    """Eq. 4: did a specialisation destroy a capability it was not aimed at?

    `before` / `after` map a domain to its success evidence — `{"ok": n,
    "runs": m}` or a plain rate in [0, 1]. Only a domain present on BOTH sides
    with at least one run is compared; a drop larger than `tolerance` is a
    regression. `ok` is False when ANY compared domain regressed, so a helper
    that improves its target but costs another domain is refused, not averaged.
    """
    try:
        tol = float(RETENTION_TOLERANCE if tolerance is None else tolerance)
    except (TypeError, ValueError):
        tol = RETENTION_TOLERANCE
    tol = max(0.0, tol)

    def rate(rec):
        if isinstance(rec, dict):
            runs = int(rec.get("runs") or 0)
            if runs <= 0:
                return None
            return round(int(rec.get("ok") or 0) / float(runs), 4)
        if isinstance(rec, (int, float)):
            return round(max(0.0, min(1.0, float(rec))), 4)
        return None

    compared, regressions, skipped = [], [], []
    for domain in sorted(set(before or {}) | set(after or {})):
        old, new = rate((before or {}).get(domain)), rate((after or {}).get(domain))
        if old is None or new is None:
            skipped.append(domain)
            continue
        delta = round(new - old, 4)
        row = {"domain": domain, "before": old, "after": new, "delta": delta}
        compared.append(row)
        if delta < -tol:
            regressions.append(row)
    return {"ok": not regressions, "tolerance": tol,
            "compared": compared, "regressions": regressions, "skipped": skipped}


def from_proposal(rec):
    """The adapter an approved improvement record would be (None when it edits
    no harness field). The domain is the record's own `domain`, never its
    workspace path — a directory is not a vertical."""
    rec = rec or {}
    field = field_for(rec.get("scope"))
    if not field:
        return None
    body = str(rec.get("content") or "")
    if not body.strip():
        body = "\n\n".join(str((a or {}).get("content") or "")
                           for a in (rec.get("artifacts") or []))
    if not body.strip():
        return None
    made = adapter(rec.get("id") or "proposal", rec.get("domain") or "general",
                   {field: body})
    return made.get("adapter") if made.get("ok") else None


def from_candidate(cand, domain="general"):
    """The adapter a harness-cycle candidate would be, or None."""
    cand = cand or {}
    field = field_for(cand.get("kind"))
    if not field:
        return None
    made = adapter(cand.get("name") or "candidate", domain,
                   {field: str(cand.get("content") or "")})
    return made.get("adapter") if made.get("ok") else None


def genotype(rows, domain="general"):
    """The composed harness a round of proposals/candidates would produce.

    `rows` may be improvement proposals or cycle candidates; a row that edits
    no harness field is listed under `skipped`, never dropped silently. Returns
    `{ok, domain, fields, adapters, overrides, skipped}` — the cycle report's
    answer to "which parts of the harness does this round touch?".
    """
    adapters, skipped = [], []
    for row in rows or []:
        got = (from_proposal(row) if "scope" in (row or {})
               else from_candidate(row, domain))
        if got:
            adapters.append(got)
        else:
            skipped.append(str((row or {}).get("name")
                               or (row or {}).get("kind") or "?"))
    merged = compose(adapters)
    if not merged.get("ok"):
        return {"ok": False, "error": merged.get("error"), "domain": _slug(domain, "general")}
    return {"ok": True, "domain": _slug(domain, "general"),
            "fields": merged["fields"],
            "adapters": [a["name"] for a in merged["applied"]],
            "overrides": merged["overrides"], "skipped": skipped}
