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
