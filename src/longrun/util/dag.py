"""Generic DAG helpers (JAG-533/SJ) shared by BOTH job engines.

Two layers need the same questions answered over a plain
``{item: [prereq, ...]}`` mapping:

  * the MULTI-SESSION job layer (``longrun.orchestrate.jobs``): ``deps`` between
    the agents of one job, and ``blocked_by`` between jobs;
  * the SESSION-scoped layer (``longrun.agent.session_jobs``, "SJ"): ``deps``
    between the subjobs of one in-session batch.

They are deliberately SEGREGATED (own ids, own stores, own lifecycle) but they
must not re-implement the same graph logic, so the pure functions live HERE and
``orchestrate.jobs`` imports ``waves``/``blockers_state`` from this module
instead of keeping its own copy.

No I/O, no locks, no global state: every function takes plain data and returns
plain data, so it is trivially testable and safe to call from any thread.
"""
from __future__ import annotations


def waves(items, deps):
    """Topological waves: each wave holds the items whose deps are already done.

    Moved verbatim from ``longrun.orchestrate.jobs`` (JAG-533) so the SJ
    scheduler and the multi-session job runner share ONE implementation. A cycle
    is broken (the first remaining item) rather than hanging forever — call
    ``has_cycle`` first when a cycle must be REPORTED instead of survived.
    """
    left = list(dict.fromkeys(items))
    out = []
    while left:
        ready = [i for i in left if not (set(deps.get(i, [])) & set(left))]
        if not ready:              # a cycle: break it rather than hang
            ready = [left[0]]
        out.append(ready)
        for i in ready:
            left.remove(i)
    return out


def has_cycle(items, deps):
    """True when the dependency graph over `items` has a cycle (Kahn counting).

    ``waves`` survives a cycle by breaking it; a scheduler that must REFUSE a
    malformed plan needs the cycle reported, so this is the strict twin.
    """
    items = list(dict.fromkeys(items))
    known = set(items)
    indeg = {}
    for i in items:
        deps_i = [d for d in (deps.get(i) or []) if d in known and d != i]
        indeg[i] = len(set(deps_i))
    ready = [i for i in items if indeg[i] == 0]
    seen = 0
    while ready:
        cur = ready.pop()
        seen += 1
        for i in items:
            if cur in (deps.get(i) or []):
                indeg[i] -= 1
                if indeg[i] == 0:
                    ready.append(i)
    return seen != len(items)


def blockers_state(blockers, status, missing_ok=True):
    """``(all_done, failed)`` for `blockers`, given an ``{id: status}`` map.

    A blocker in ANY terminal state other than ``done`` (``error`` / ``partial``
    / ``cancelled`` / ``failed``) is a FAILED dependency, not an open one
    (JAG-348): the dependent must be failed loudly instead of staying blocked
    forever. ``missing_ok`` treats an id ABSENT from `status` as satisfied — a
    deleted blocker must not wedge the graph (JAG-314).
    """
    all_done, failed = True, []
    status = status or {}
    for b in blockers or []:
        if b not in status:
            if missing_ok:
                continue
            all_done = False
            failed.append(b)
            continue
        st = status.get(b)
        if st == "done":
            continue
        if st in ("error", "partial", "cancelled", "failed"):
            failed.append(b)
        all_done = False
    return all_done, failed


def ready(pending, deps, done_ids):
    """The subset of `pending` whose dependencies are ALL in `done_ids`.

    The SJ scheduler's core question: a subjob may START only when every
    dependency it declared has finished, so the dependency's output can be
    handed to it as input.
    """
    done = set(done_ids or [])
    return [i for i in pending if not (set(deps.get(i, [])) - done)]


# ── graph engineering (round 169) ───────────────────────────────────────────
# The chaos the four helpers above leave behind: sixteen structures in this
# codebase ARE graphs, and only four of them share these functions, on `dep`
# edges alone — nothing could carry an *edge kind*, so no cross-graph question
# ("what is the frontier?", "is this loop declared?") had a home. `Graph` is
# that home: a stdlib value object over the SAME `{item: [prereq]}` shape, so
# the four helpers above stay byte-identical and every existing caller keeps
# working. Sources: the stored graph-engineering talk (Neo4j, `g_NgCLTibiM`);
# `S-2026-11-01-057` (deterministic execution constraints).
#
# A Loop IS a graph: a `feedback` edge declares it, so a `dep` cycle that the
# graph ALSO mirrors with a `feedback` edge is intended, and `has_cycle` (the
# strict twin) is asked over `dep` edges only.

EDGE_KINDS = ("dep", "contain", "membership", "handoff", "feedback")


class Graph:
    """Nodes + TYPED edges, with the helpers above as its traversal.

    Pure, no I/O: build it from data already in memory. `census()` is the
    bounded, plain-data summary a reader (the topology audit, the Orbit deck,
    the CLI) consumes without touching any store.
    """

    FORMAT = "longrun-graph/1"

    def __init__(self, nodes=None, edges=None):
        self._nodes = {}          # id -> status or None
        self._edges = []          # {"from", "to", "kind"}
        for n in nodes or ():
            self.add_node(n)
        for e in edges or ():
            self.add_edge(*e)     # (a, b) or (a, b, kind)

    def add_node(self, node, status=None):
        self._nodes[str(node)] = status
        return self

    def add_edge(self, src, dst, kind="dep"):
        if kind not in EDGE_KINDS:
            raise ValueError("unknown edge kind %r (expected one of %s)"
                             % (kind, ", ".join(EDGE_KINDS)))
        self._edges.append({"from": str(src), "to": str(dst), "kind": kind})
        return self

    @property
    def nodes(self):
        return list(self._nodes)

    def edges(self, kind=None):
        """Every edge as a plain dict, optionally filtered to one kind."""
        return [dict(e) for e in self._edges if kind is None or e["kind"] == kind]

    def deps(self, kinds=("dep",)):
        """`{node: [prereq, ...]}` over `kinds` (the shape the helpers take)."""
        out = {n: [] for n in self._nodes}
        for e in self._edges:
            if e["kind"] in kinds and e["from"] != e["to"]:
                out.setdefault(e["to"], []).append(e["from"])
        return out

    def statuses(self):
        """Only the nodes whose status was declared."""
        return {n: s for n, s in self._nodes.items() if s}

    def waves(self):
        return waves(self.nodes, self.deps())

    def ready(self, done_ids):
        done = set(str(x) for x in (done_ids or ()))
        return ready(self.nodes, self.deps(), done)

    def has_cycle(self):
        return has_cycle(self.nodes, self.deps())

    def census(self):
        """The plain-data summary: nodes, typed edges, counts, the dep cycle."""
        counts = {k: 0 for k in EDGE_KINDS}
        for e in self._edges:
            counts[e["kind"]] += 1
        return {"format": self.FORMAT,
                "nodes": self.nodes,
                "edges": self.edges(),
                "counts": {"nodes": len(self._nodes), "edges": counts},
                "cycle": self.has_cycle(),
                "statuses": self.statuses()}
