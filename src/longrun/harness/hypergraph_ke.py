#!/usr/bin/env python3
"""Hypergraph KE — one typed store, kept sound under edits, read by the right tier.

Source: arXiv:2611.24294, "KnowledgeClaw: Towards Agentic Knowledge Engineering
via Omnimodal Hypergraphs" (round 153). A live personal knowledge base needs
omnimodality, a closed-loop lifecycle and multi-granular application at once,
and prior systems meet at most two
(`knowledge_engineering_2611.24294.txt:60`, `:63`).

  * **the artefact is typed and carries provenance**:
    `K = (D, V, E, pi)` with `kappa(e) in {record, event, cross-modal}` and
    `pi: V union E -> 2^D` (`:266`).
  * **files meet on shared entities**: two files whose records name one entity
    are joined within two hyperedges, across modalities (`:302`, `:1685`).
  * **an edit prunes provenance and drops what it alone supported**, so no node
    rests on an absent file; an append-only store accumulated 10,148 such nodes
    over 2,000 edits (`:322`, `:554`).
  * **a named file always enters the evidence**, which top-k cannot guarantee:
    with `l` exchangeable look-alikes, `Pr[a in top-k] = min(k, l+1)/(l+1)`
    (`:397`, `:1770`).
  * **routing beats any fixed tier**: forced file-only fails the joins (1.5 and
    3.6) and walking fails extraction (36.1), while the router matches the best
    fixed tier on every task (`:571`, `:580`).
  * **measured**: OKE 55.9 against 41.3 for the strongest baseline, and the
    ablations lose T1 by 20.0, T5 by 46.0 or OKE by 29.2 (`:428`, `:475`).

  * `ingest(rows)` — what each file contributes, and what may not be gold.
  * `join(rows)` — identity, alias classes and the two-hop join rate.
  * `edit(record)` — ADD / DEL / REFRESH with the soundness invariant.
  * `route(record)` — the three cues and the tier they select.
  * `evidence(record)` — the named-file guarantee against top-k.
  * `oke(rows)` — persona means, task means and the equal-persona overall.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: file records, hashes and provenance maps in; invariants and verdicts out.
"""
from __future__ import annotations

import unicodedata

FORMAT = "longrun-hypergraph-ke/1"

MODALITIES = ("text", "pdf", "image", "audio", "video")
TIERS = ("file", "subgraph", "community", "fallback")
KINDS = ("record", "event", "cross-modal")


def _norm(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return text.strip(".,;:()[]{}")


def _alias(name):
    parts = _norm(name).replace(".", " ").split()
    if len(parts) < 2:
        return _norm(name)
    return parts[0][0] + " " + parts[-1]


def ingest(rows):
    """A file's surface, modality and record fields; model output is never gold."""
    files = 0
    media = 0
    violations = []
    fields = set()
    for row in rows or []:
        r = row or {}
        name = str(r.get("file") or "")
        modality = str(r.get("modality") or "")
        if not name or modality not in MODALITIES:
            continue
        files += 1
        if modality not in ("text", "pdf"):
            media += 1
        if r.get("gold_from_model") is True:
            violations.append({"file": name, "reason": "model-made-gold"})
        if r.get("surface") is None and modality in ("text", "pdf"):
            violations.append({"file": name, "reason": "no-surface"})
        for field in r.get("fields") or []:
            fields.add(str(field))
    return {"format": FORMAT, "files": files, "media": media,
            "fields": sorted(fields), "violations": violations,
            "verdict": "ingested" if files and not violations
            else "ingest-rejected"}


def join(rows, window=2):
    """Shared entities and alias classes; the share of files within the window."""
    nodes = {}
    edges = 0
    files = set()
    modality = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("file") or "")
        if not name:
            continue
        files.add(name)
        modality[name] = str(r.get("modality") or "text")
        values = list(r.get("values") or [])
        if r.get("person"):
            values.append("P:" + _alias(r["person"]))
        for value in values:
            key = _norm(value)
            if not key:
                continue
            nodes.setdefault(key, set()).add(name)
            edges += 1
    if not files:
        return {"format": FORMAT, "verdict": "no-files"}
    joined = set()
    for holders in nodes.values():
        if len(holders) > 1:
            joined |= holders
    cross = [key for key, holders in nodes.items()
             if len({modality.get(name, "text") for name in holders}) > 1]
    return {"format": FORMAT, "files": len(files), "entities": len(nodes),
            "edges": edges, "joined": len(joined),
            "join_share": len(joined) / len(files),
            "cross_modal_entities": len(cross),
            "verdict": "joined" if len(joined) >= len(files) * 0.9
            else "join-gap"}


def edit(record):
    """ADD, DEL or REFRESH; the soundness invariant is checked, not assumed."""
    r = record or {}
    operation = str(r.get("op") or "").upper()
    provenance = {str(k): set(v or []) for k, v in (r.get("provenance") or {}).items()}
    present = set(r.get("present") or [])
    handle = str(r.get("handle") or "")
    new_files = list(r.get("files") or [])
    stale_before = 0
    if operation not in ("ADD", "DEL", "REFRESH"):
        return {"format": FORMAT, "verdict": "unknown-op"}
    append_only = r.get("append_only") is True
    if operation in ("DEL", "REFRESH"):
        old = set(r.get("handle_files") or [])
        present -= old
        if not append_only:
            for key in list(provenance):
                provenance[key] -= old
    if operation in ("ADD", "REFRESH"):
        present |= set(new_files)
        for value in r.get("new_entities") or []:
            provenance.setdefault(_norm(value), set()).update(new_files)
    if not append_only:
        for key in [k for k, v in provenance.items() if not v]:
            del provenance[key]
    unsound = [k for k, v in provenance.items() if not v <= present]
    gone = set(r.get("gone") or [])
    stale_after = sum(1 for v in provenance.values() if v & gone)
    return {"format": FORMAT, "op": operation, "nodes": len(provenance),
            "present": len(present), "unsound": unsound,
            "stale_before": stale_before, "stale_after": stale_after,
            "verdict": "sound" if not unsound and not stale_after
            else "stale-or-unsound"}


def route(record):
    """Handles and quoted spans anchor; relational, lookup and synthesis cue."""
    r = record or {}
    handles = list(r.get("handles") or [])
    spans = list(r.get("spans") or [])
    relational = r.get("relational") is True
    lookup = r.get("lookup") is True
    synthesis = r.get("synthesis") is True
    if handles and not spans and not relational:
        tier = "file"
    elif handles or spans or (lookup and not synthesis):
        tier = "subgraph"
    elif not handles and not spans and synthesis:
        tier = "community"
    else:
        tier = "fallback"
    return {"format": FORMAT, "tier": tier,
            "anchors": len(handles) + len(spans),
            "verdict": "routed"}


def evidence(record):
    """Named cards always enter; top-k may miss with l exchangeable look-alikes."""
    r = record or {}
    named = list(r.get("named_files") or [])
    k = int(r.get("k") or 0)
    lookalikes = int(r.get("lookalikes") or 0)
    if not named:
        return {"format": FORMAT, "verdict": "no-named-files"}
    if lookalikes <= 0:
        miss = 0.0
    elif k <= 0:
        miss = 1.0
    else:
        miss = 1 - min(k, lookalikes + 1) / (lookalikes + 1)
    return {"format": FORMAT, "named": len(named),
            "cards_always_included": True, "topk_miss": miss,
            "verdict": "named-file-guaranteed"}


def oke(rows):
    """Persona scores, task means and the equal-persona overall."""
    personas = {}
    for row in rows or []:
        r = row or {}
        persona = str(r.get("persona") or "")
        task = str(r.get("task") or "")
        score = r.get("score")
        if not persona or not task:
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        personas.setdefault(persona, []).append(value)
    if not personas:
        return {"format": FORMAT, "verdict": "no-scores"}
    means = {name: sum(v) / len(v) for name, v in personas.items()}
    return {"format": FORMAT, "personas": len(means), "persona_scores": means,
            "oke": sum(means.values()) / len(means),
            "verdict": "oke-computed"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("stores_segments_only") is True:
        findings.append({"kind": "segments-only",
                         "why": "a segment store has no node to join two files on"})
    if r.get("appends_new_versions") is True:
        findings.append({"kind": "appends-new-versions",
                         "why": "an append-only store leaves 10,148 stale nodes"})
    if r.get("flat_topk_is_enough") is True:
        findings.append({"kind": "flat-topk-is-enough",
                         "why": "top-k misses a named file on 33.5% of T2 items"})
    if r.get("one_tier_for_every_query") is True:
        findings.append({"kind": "one-tier-for-every-query",
                         "why": "no fixed tier wins on all six tasks"})
    if r.get("model_made_gold") is True:
        findings.append({"kind": "model-made-gold",
                         "why": "gold must trace to human metadata or parsing"})
    if r.get("rebuild_per_edit") is True:
        findings.append({"kind": "rebuild-per-edit",
                         "why": "a refresh costs 2.6 s against 118 s for a full add"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("reads_every_modality_natively", "bridges_media_to_text",
         "the bridge loses what the record needs"),
        ("keys_entities_deterministically", "matches_entities_by_similarity",
         "a join needs an identity, not a nearest neighbour"),
        ("commits_edits_along_provenance", "rebuilds_or_appends",
         "an edit must reach what its file supports"),
        ("anchors_named_files_before_ranking", "trusts_top_k",
         "top-k cannot guarantee a named file"),
        ("routes_the_query_to_a_tier", "uses_one_retrieval_shape",
         "each fixed tier fails a different task"),
        ("keeps_gold_out_of_model_output", "generates_answers_with_a_model",
         "model-made gold measures the model"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
