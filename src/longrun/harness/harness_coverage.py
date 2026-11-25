#!/usr/bin/env python3
"""Harness coverage — Longrun's own ETCSLV self-rating, derived live.

Round 171. Source: the survey *Agent Harness for Large Language Model Agents*
(`Awesome-Agent-Harness`, v4, CC-BY-4.0): the framework **H = (E, T, C, S, L, V)**
and its evidence-coded 34-system matrix. The survey was used once, by hand, as a
reading grid (`.agent/docs/plans/reference/longrun-vs-harness-codebases.md` §3);
this module makes Longrun's own coverage a derivation instead of a document that
drifts.

It answers ONE question — *which of the six functions does this harness expose,
and where does each live?* — from the live tree: a declarative map from component
to owning modules, probed read-only. It is not a quality claim: a `Full` rating
says the owners exist, never that they are good. Bounded and fail-open (a module
that cannot be located contributes `Unverified`, never a crash).

Live seam (`core/forge.py`, `core/httpapi.py`) — it belongs at the `harness/` root,
never in `checks/` (ADR-0003). The *audit* of a survey matrix is the report-only
checker `harness/checks/harness_coverage.py`; the survey's data is the bundled
`harness/harness_matrix.json`.

  build(probe)          -> the self-rating payload (one policy, one place)
  census()              -> the same payload, from the live tree
  load_matrix()         -> the bundled 34-system matrix ({} when absent)
  compare(payload)      -> Longrun's rating joined to the matrix, per component
  card(payload)         -> a bounded, plain-text coverage card
"""
from __future__ import annotations

import json
import os

FORMAT = "longrun-harness-coverage/1"
MAX_TEXT = 900

COMPONENT_ORDER = ("E", "T", "C", "S", "L", "V")
COMPONENTS = {
    "E": {"name": "Execution loop", "what": "turn and step control, termination, retry, recovery, delegation"},
    "T": {"name": "Tool registry", "what": "typed tools, routing, validation, authorization, result handling"},
    "C": {"name": "Context manager", "what": "prompt assembly, retrieval, compaction, salience, provenance"},
    "S": {"name": "State store", "what": "cross-turn and cross-session persistence, checkpoints, recovery"},
    "L": {"name": "Lifecycle hooks", "what": "authentication, approval, policy, instrumentation, interception"},
    "V": {"name": "Evaluation iface", "what": "trajectories, intermediate state, outcomes, experiments, audit"},
}
# component -> the modules that own it (dotted path, one line of why).
_OWNERS = {
    "E": [("longrun.agent.agent", "the turn loop"),
          ("longrun.plan.keepgoing", "the completion loop"),
          ("longrun.core.inflight", "restart recovery")],
    "T": [("longrun.tools.registry", "typed registry + TOOL_EFFECTS"),
          ("longrun.tools.tools", "dispatch + validation")],
    "C": [("longrun.model.context_engine", "prompt assembly + retrieval"),
          ("longrun.model.prompt", "system sections"),
          ("longrun.memory.stores", "compaction + persistence")],
    "S": [("longrun.memory.stores", "session + task store"),
          ("longrun.plan.taskgraph", "the task graph"),
          ("longrun.util.tracing", "run manifests")],
    "L": [("longrun.tools.approvals", "the approval gate"),
          ("longrun.tools.sandbox", "execution confinement"),
          ("longrun.tools.hooks", "lifecycle hooks")],
    "V": [("longrun.util.runtree", "the trace tree"),
          ("longrun.util.evals", "the eval runner"),
          ("longrun.plan.verify", "closeout verification")],
}


def _default_probe(dotted):
    """True when a module is locatable, False when not, None when the probe failed."""
    import importlib.util
    try:
        return importlib.util.find_spec(dotted) is not None
    except Exception:  # noqa: BLE001 — a probe that cannot run is Unverified, not a crash
        return None


def _rating(evidence):
    """Full (all present) · Partial (some) · Unverified (a probe failed) · Absent."""
    present = [e["present"] for e in evidence]
    if present and all(p is True for p in present):
        return "Full"
    if any(p is True for p in present):
        return "Partial"
    if any(p is None for p in present):
        return "Unverified"
    return "Absent"


def build(probe=None):
    """The self-rating payload from the live tree (or a caller's `probe`)."""
    probe = probe or _default_probe
    components, summary = [], {r: 0 for r in ("Full", "Partial", "Absent", "Unverified")}
    for cid in COMPONENT_ORDER:
        evidence = [{"module": mod, "what": what, "present": probe(mod)}
                    for mod, what in _OWNERS[cid]]
        rating = _rating(evidence)
        summary[rating] += 1
        components.append({"id": cid, "name": COMPONENTS[cid]["name"],
                           "rating": rating, "evidence": evidence})
    full = summary["Full"]
    return {"format": FORMAT,
            "components": components,
            "summary": summary,
            "verdict": "full" if full == len(COMPONENT_ORDER) else
                       ("partial" if full else "none")}


def census():
    """The live self-rating; a module that cannot be probed is `Unverified`."""
    return build()


def matrix_path():
    """Absolute path of the bundled survey matrix."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness_matrix.json")


def load_matrix(path=None):
    """The bundled 34-system ETCSLV matrix, or `{}` when it cannot be read."""
    try:
        with open(path or matrix_path(), "r", encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001 — a missing dataset is data, not a crash
        return {}


def _longrun_rating(payload, cid):
    for c in (payload or {}).get("components") or ():
        if c.get("id") == cid:
            return c.get("rating") or "Unverified"
    return "Unverified"


def compare(payload=None, matrix=None):
    """Longrun's self-rating joined to the survey's 34 systems, per component.

    For each component: how many of the surveyed systems rate `Full`, and whether
    Longrun is `behind_peers` (not Full while at least half the field is). This is
    a coverage comparison, never a quality ranking.
    """
    payload = payload if isinstance(payload, dict) else census()
    matrix = matrix if isinstance(matrix, dict) else load_matrix()
    order = [c for c in (matrix.get("componentOrder") or COMPONENT_ORDER) if c in COMPONENT_ORDER] \
        or list(COMPONENT_ORDER)
    systems = [s for s in (matrix.get("systems") or ()) if isinstance(s, dict)]
    total = len(systems)
    rows = []
    for cid in order:
        full = 0
        for s in systems:
            for cell in s.get("components") or ():
                if isinstance(cell, dict) and cell.get("id") == cid \
                        and cell.get("rating") == "Full":
                    full += 1
                    break
        share = round(full / total, 3) if total else None
        mine = _longrun_rating(payload, cid)
        rows.append({"id": cid, "longrun": mine, "peers_full": full, "peers_total": total,
                     "peers_full_share": share,
                     "behind_peers": bool(mine != "Full" and share is not None and share >= 0.5)})
    return {"format": FORMAT, "componentOrder": order, "systems": total, "rows": rows}


def card(payload):
    """A bounded, plain-text coverage card — "" when there is no payload."""
    components = (payload or {}).get("components") or ()
    if not components:
        return ""
    lines = ["## Harness coverage (ETCSLV · observed at read time)"]
    for c in components:
        ev = c.get("evidence") or ()
        present = sum(1 for e in ev if e.get("present") is True)
        lines.append("%s %s: %s (%d/%d present)"
                     % (c.get("id"), COMPONENTS.get(c.get("id"), {}).get("name", ""),
                        c.get("rating"), present, len(ev)))
    summary = (payload or {}).get("summary") or {}
    lines.append("summary: " + " · ".join("%d %s" % (summary.get(r, 0), r)
                                          for r in ("Full", "Partial", "Absent", "Unverified")))
    return "\n".join(lines)[:MAX_TEXT]
