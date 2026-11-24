#!/usr/bin/env python3
"""Graph topology — the ONE census of the graphs a running system owns.

Round 169. Source: the stored graph-engineering talk (Neo4j, `g_NgCLTibiM`):
"designing agent work as an explicit graph — where nodes do work and edges route
state between them", whose third benefit is *governance* — an inspector that
shows **which branches were taken and which were not**. This module is the one
derivation that inspector (the Orbit deck, `forge.py graph`, the audit) reads,
so the topology is no longer re-derived per reader.

It reads the *execution* graphs the app already persists — agents (`reports_to`
-> `handoff`), teams (membership), jobs + subjobs (`contain` / `dep`) — and
builds them out of `util.dag.Graph`, so any reader gets nodes, typed edges, the
dep cycle and the frontier from one place. Bounded reads, fail-open: a store
that cannot be read contributes nothing instead of breaking a caller.

Live seam (`orbit/api`, `forge.py`) — it belongs at the `harness/` root, never in
`checks/` (ADR-0003; `v1273` pins the invariant). The *audit* of this census is
the report-only checker `harness/checks/graph_topology.py`.

  build_from(agents, jobs, teams)  -> the census payload (one policy, one place)
  census()                         -> the same payload from the LIVE registries
  card(payload)                    -> a bounded, plain-text topology card
  frontier(payload)                -> the nodes that can start now, across graphs
"""
from __future__ import annotations

from longrun.util import dag as _dag

FORMAT = "longrun-graph-topology/1"
MAX_NODES = 2000
MAX_EDGES = 4000
MAX_TEXT = 1200
MAX_LIST = 8

# Kind for each relationship, so the census is self-describing.
_HANDOFF = "handoff"
_MEMBER = "membership"
_CONTAIN = "contain"
_DEP = "dep"


def _agents_graph(agents):
    g = _dag.Graph()
    for a in agents or ():
        if a.get("id"):
            g.add_node(a.get("id"), status=a.get("role") or None)
    for a in agents or ():
        if a.get("id") and a.get("reports_to"):
            g.add_edge(a.get("id"), a.get("reports_to"), kind=_HANDOFF)
    return g


def _teams_graph(teams):
    g = _dag.Graph()
    for t in teams or ():
        if not t.get("id"):
            continue
        g.add_node(t.get("id"))
        for m in t.get("members") or ():
            g.add_node(m)                       # a member is a node here, so the
            g.add_edge(t.get("id"), m, kind=_MEMBER)   # membership edge has no orphan
    return g


def _jobs_graph(jobs):
    g = _dag.Graph()
    for j in jobs or ():
        jid = j.get("id")
        if not jid:
            continue
        g.add_node(jid, status=j.get("status"))
        for b in j.get("blocked_by") or ():
            g.add_edge(jid, b, kind=_DEP)
        for sid, s in (j.get("subjobs") or {}).items():
            g.add_node(sid, status=s.get("status"))
            g.add_edge(jid, sid, kind=_CONTAIN)
            for d in s.get("deps") or ():
                g.add_edge(sid, d, kind=_DEP)
    return g


def _one(name, graph, out, capped):
    cen = graph.census()
    nodes = cen.get("nodes") or []
    edges = cen.get("edges") or []
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        capped.append(name)
        nodes, edges = nodes[:MAX_NODES], edges[:MAX_EDGES]
    out[name] = {"nodes": list(nodes), "edges": [dict(e) for e in edges],
                 "statuses": dict(cen.get("statuses") or {})}
    return cen


def build_from(agents=None, jobs=None, teams=None):
    """The census payload from the three live lists (one policy, one place)."""
    graphs = {"agents": _agents_graph(agents),
              "teams": _teams_graph(teams),
              "jobs": _jobs_graph(jobs)}
    out, totals_nodes, totals_edges, frontier, capped = {}, 0, {}, [], []
    for name in sorted(graphs):
        cen = _one(name, graphs[name], out, capped)
        totals_nodes += cen["counts"]["nodes"]
        for k, n in cen["counts"]["edges"].items():
            totals_edges[k] = totals_edges.get(k, 0) + n
        frontier.extend("%s:%s" % (name, n) for n in graphs[name].ready(set()))
    return {"format": FORMAT, "graphs": out,
            "totals": {"nodes": totals_nodes, "edges": totals_edges},
            "frontier": sorted(frontier), "truncated": capped}


def build(graphs):
    """Aggregate `{name: Graph}` (a caller's own graphs) into the same payload."""
    out, totals_nodes, totals_edges, frontier, capped = {}, 0, {}, [], []
    for name in sorted(graphs or {}):
        g = graphs[name]
        if not hasattr(g, "census"):
            continue
        cen = _one(str(name), g, out, capped)
        totals_nodes += cen["counts"]["nodes"]
        for k, n in cen["counts"]["edges"].items():
            totals_edges[k] = totals_edges.get(k, 0) + n
        frontier.extend("%s:%s" % (name, n) for n in g.ready(set()))
    return {"format": FORMAT, "graphs": out,
            "totals": {"nodes": totals_nodes, "edges": totals_edges},
            "frontier": sorted(frontier), "truncated": capped}


def census():
    """The LIVE census; any store that cannot be read is simply absent."""
    def _safe(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — the census must never break a caller
            return []

    def _agents():
        from longrun.agent import agents as _a
        return _a.REGISTRY.list().get("agents", [])

    def _jobs():
        from longrun.orchestrate import jobs as _j
        return _j.JOBS.list().get("jobs", [])

    def _teams():
        from longrun.orchestrate import teams as _t
        return _t.REGISTRY.list().get("teams", [])

    return build_from(_safe(_agents), _safe(_jobs), _safe(_teams))


def _line(name, g):
    kinds = {}
    for e in g.get("edges") or ():
        kinds[e.get("kind")] = kinds.get(e.get("kind"), 0) + 1
    detail = " ".join("%s%d" % (k[0], kinds[k]) for k in sorted(kinds))
    return "%s: %dn %de%s" % (name, len(g.get("nodes") or ()), len(g.get("edges") or ()),
                              (" (" + detail + ")") if detail else "")


def frontier(payload):
    """The nodes that can start now, across every graph in the census."""
    return list((payload or {}).get("frontier") or ())


def card(payload):
    """A bounded, sorted topology card text — "" when there is no graph."""
    graphs = (payload or {}).get("graphs") or {}
    if not graphs:
        return ""
    lines = ["## Topology (observed at read time)"]
    for name in sorted(graphs):
        lines.append(_line(name, graphs[name]))
    fr = frontier(payload)
    if fr:
        shown = ", ".join(fr[:MAX_LIST])
        if len(fr) > MAX_LIST:
            shown += " (+%d more)" % (len(fr) - MAX_LIST)
        lines.append("frontier: " + shown)
    if payload.get("truncated"):
        lines.append("truncated: " + ", ".join(payload["truncated"]))
    return "\n".join(lines)[:MAX_TEXT]
