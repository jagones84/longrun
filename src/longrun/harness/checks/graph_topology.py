#!/usr/bin/env python3
"""Graph-topology audit — one finding per real defect across a system's graphs.

Round 169. Source: the stored graph-engineering talk (Neo4j, `g_NgCLTibiM`):
designing agent work as an explicit graph buys *predictability* (a constrained
path), *governance* ("which branches were taken and which were not") and
*portability*. This module is the predictability half — it reads the system's
own census (`longrun.harness.graph_topology.census`) and names the topology
defects no other checker sees. It joins the shipped graph checkers
(`tool_graph`, `intent_audit`, `skill_cfi`, `hypergraph_ke`) rather than
replacing any of them: those each read ONE synthesized graph, this reads the
persisted orchestration graphs as one census.

Four kinds of finding, each carrying a locator:

  * `orphan-edge`      — an edge names a node the graph does not declare;
  * `undeclared-cycle` — a `dep` cycle the graph does NOT mirror with a
                         `feedback` edge. A declared loop is NOT a defect:
                         `dep a->b` + `feedback b->a` is the intent;
  * `dead-blocker`     — a `blocked` node whose prerequisites include a terminal
                         FAILED one and none `done` (the JAG-348 wedge: the graph
                         waits forever on work that will never finish);
  * `invariant-failed` — a declared invariant the census carries with `ok: false`.

Pure: a plain-data census in, findings out, no app import (ADR-0003). The only
adapter is `core/forge.py` (`python3 forge.py graph audit FILE.json`).

  audit(census) -> {"format", "verdict": "clean"|"defects", "findings": [...]}
"""
from __future__ import annotations

FORMAT = "longrun-graph-topology/1"
MAX_FINDINGS = 200
FAILED_STATUSES = ("failed", "error", "cancelled", "partial")


def _reaches(adj, start):
    """The node set reachable from `start` over `adj` (excludes start itself)."""
    seen, stack = set(), list(adj.get(start, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    return seen


def _dep_adj(nodes, edges):
    """`{node: [successor, ...]}` over `dep` edges whose endpoints both exist."""
    adj = {n: [] for n in nodes}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if e.get("kind") == "dep" and a in adj and b in adj and a != b:
            adj[a].append(b)
    return adj


def _cycle(nodes, edges):
    """(cyclic dep edges, the nodes they touch) for the FIRST cycle shape found.

    A `dep` edge u->v lies on a cycle exactly when u is reachable from v. An
    empty pair means the `dep` subgraph is acyclic.
    """
    adj = _dep_adj(nodes, edges)
    cyclic, touched = [], set()
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if e.get("kind") != "dep" or a not in adj or b not in adj or a == b:
            continue
        if a in _reaches(adj, b):
            cyclic.append(e)
            touched.update((a, b))
    return cyclic, touched


def _declared(edges, touched):
    """True when a `feedback` edge lies on the loop's own nodes."""
    for e in edges:
        if e.get("kind") == "feedback" and e.get("from") in touched and e.get("to") in touched:
            return True
    return False


def _graph_findings(name, graph):
    """Every finding inside ONE graph of the census."""
    nodes = [str(n) for n in (graph.get("nodes") or ())]
    known = set(nodes)
    edges = [e for e in (graph.get("edges") or ()) if isinstance(e, dict)]
    statuses = graph.get("statuses") or {}
    out = []

    for e in edges:
        a, b = str(e.get("from")), str(e.get("to"))
        if a not in known or b not in known:
            out.append({"kind": "orphan-edge", "graph": name,
                        "detail": "%s --%s--> %s (one endpoint is not a declared node)"
                                  % (a, e.get("kind"), b)})

    cyclic, touched = _cycle(nodes, edges)
    if cyclic and not _declared(edges, touched):
        out.append({"kind": "undeclared-cycle", "graph": name,
                    "detail": "dep cycle over %s with no feedback edge declaring the loop"
                              % ", ".join(sorted(touched))})

    deps = {}
    for e in edges:
        if e.get("kind") == "dep":
            deps.setdefault(str(e.get("to")), []).append(str(e.get("from")))
    for node, status in statuses.items():
        if status != "blocked":
            continue
        pre = deps.get(str(node), [])
        pre_status = [statuses.get(p) for p in pre]
        if any(s in FAILED_STATUSES for s in pre_status) and "done" not in pre_status:
            out.append({"kind": "dead-blocker", "graph": name,
                        "detail": "%s is blocked by %s, none done — it can never be released"
                                  % (node, ",".join(p for p, s in zip(pre, pre_status)
                                                    if s in FAILED_STATUSES))})
    return out


def audit(census):
    """The findings a census carries; `verdict` is `clean` when there are none."""
    census = census if isinstance(census, dict) else {}
    findings = []
    graphs = census.get("graphs") or {}
    if isinstance(graphs, dict):
        for name in sorted(graphs):
            graph = graphs[name]
            if not isinstance(graph, dict):
                continue
            findings.extend(_graph_findings(str(name), graph))
    for inv in census.get("invariants") or ():
        if isinstance(inv, dict) and inv.get("ok") is False:
            findings.append({"kind": "invariant-failed",
                             "graph": str(inv.get("graph") or "invariants"),
                             "detail": str(inv.get("detail") or inv.get("id") or "invariant failed")})
    if len(findings) > MAX_FINDINGS:
        findings = findings[:MAX_FINDINGS]
    return {"format": FORMAT,
            "verdict": "defects" if findings else "clean",
            "findings": findings}
