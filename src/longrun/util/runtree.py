#!/usr/bin/env python3
"""Turn tree + failure-onset localization (HD-2, 2026-11-14).

The chat loop already persists everything a failure needs: every tool call is a
card in `sess["tool_cards"]` with `ok`, `error`, `exit_code`, `node` (the todo it
served) and `after` (its message boundary), and the plan's steps are nodes in the
session graph. What was missing is the READ MODEL — today a failed turn is
diagnosed by reading `_render_transcript`'s flat ordered log and guessing which
call broke the run.

`build()` groups the flat stores into the loop's real hierarchy — STAGE (one plan
step, i.e. one todo node) → STEP (one tool call, in execution order) — and `onset()`
names the FIRST step that went wrong, whether a later call recovered it, and how
many times the same tool was retried after it.

Two facts this is careful about:

* `after` is per-CARD, not per-round (measured 2026-11-14: 24 cards on one live
  session had 24 distinct `after` values), so it orders steps and anchors them to
  the transcript; it does NOT delimit a model round. The plan node is the only
  stable "stage" the store really has.
* A card can name a todo that no longer exists in the graph (a replan replaced
  it). Those steps are kept, in their own stage, rather than dropped — a deleted
  todo must not silently delete the evidence of what failed.

Read-only: nothing is written, no model is called. The failure CLASS is
`selfevolve.error_class` — the same normalizer `failure_candidates` ranks by, so a
tree's class and the miner's class are one string, never two.
PURE module: no server dependency, unit-testable.
"""
import os

from longrun.plan import taskgraph
from longrun.util import selfevolve


def _failed(card):
    """True when a card names a failure: a bad verdict, or a non-zero exit."""
    if not card.get("ok"):
        return True
    ec = card.get("exit_code")
    return isinstance(ec, int) and ec != 0


def steps(sess):
    """Every tool call of the session, in execution order, as flat steps.

    Order is `(ts, after)`: `ts` is the wall clock the card was persisted with,
    `after` its message boundary — the same two keys the transcript renderer
    sorts by, so the tree and the transcript never disagree about what came
    first.
    """
    cards = list((sess or {}).get("tool_cards") or [])
    cards.sort(key=lambda c: (c.get("ts") or 0, c.get("after") or 0))
    out = []
    for i, c in enumerate(cards, 1):
        bad = _failed(c)
        rec = {"i": i, "tool": str(c.get("tool") or "?"), "ok": not bad,
               "failed": bad,
               "exit_code": c.get("exit_code"),
               "node": c.get("node") or "",
               # U+2014: a failure's class, or the empty string for a success —
               # never "ok", so a reader cannot mistake a class for a verdict.
               "reason": selfevolve.error_class(c.get("error")) if bad else "",
               "after": c.get("after"),
               "ts": c.get("ts")}
        out.append(rec)
    return out


def onset(flat):
    """The FIRST step that went wrong, with what happened to it afterwards.

    Returns None when no step failed — an honest "nothing broke", not a guess.
    `recovered` is a LATER success of the SAME tool in the SAME stage: that is
    the difference between "the run failed here" and "the run stumbled here".
    """
    first = next((s for s in flat if s["failed"]), None)
    if first is None:
        return None
    later = [s for s in flat if s["i"] > first["i"]]
    same = [s for s in later if s["tool"] == first["tool"]]
    recovered = any(s["ok"] and s["node"] == first["node"] for s in same)
    return {"i": first["i"], "tool": first["tool"], "reason": first["reason"],
            "exit_code": first["exit_code"], "node": first["node"],
            "recovered": recovered,
            "retries": len(same),
            "failed_total": sum(1 for s in flat if s["failed"]),
            "steps_total": len(flat)}


def _verdict(ond, stage_title):
    """One operator-readable line, or "" when nothing failed."""
    if not ond:
        return ""
    where = (" in '%s'" % stage_title) if stage_title else ""
    exit_ = (" (exit %s)" % ond["exit_code"]) if isinstance(ond["exit_code"], int) else ""
    after = ("recovered by a later %s that succeeded" % ond["tool"]
             if ond["recovered"] else
             "%s was never retried successfully" % ond["tool"])
    return ("first failure at step %d of %d%s: %s%s — %s"
            % (ond["i"], ond["steps_total"], where, ond["tool"], exit_, after))


def build(sess, graph=None):
    """The turn tree: stages (plan steps) → steps, plus the onset verdict.

    A session with no plan still gets ONE stage holding every step, so the
    answer is never empty for a run that did work.
    """
    flat = steps(sess)
    nodes = list(((graph or {}).get("nodes") or []))
    stages, open_steps, seen = [], [], set()
    for n in nodes:
        nid = str(n.get("id") or "")
        if not nid:
            continue
        seen.add(nid)
        mine = [s for s in flat if s["node"] == nid]
        row = {"id": nid, "label": str(n.get("label") or nid),
               "status": str(n.get("status") or "todo")}
        if mine:
            stages.append({**row, "steps": mine, "n": len(mine)})
        else:
            # A plan step that executed NOTHING is information, not clutter: it
            # is where a turn claimed progress without a tool call. It stays in
            # its own list so the tree of what RAN is not padded with 33 empty
            # stages (measured on a live session: 33 nodes, 24 steps).
            open_steps.append(row)
    orphans = [s for s in flat if s["node"] not in seen]
    if orphans:
        # Grouped by the dead node id, so two replaced todos stay two stages and
        # a reader can still see which one carried the failure.
        for nid in sorted({s["node"] for s in orphans}):
            mine = [s for s in orphans if s["node"] == nid]
            stages.append({"id": nid or "(unplanned)",
                           "label": ("(todo no longer in the plan: %s)" % nid
                                     if nid else "(no plan step)"),
                           "status": "orphan", "steps": mine, "n": len(mine)})
    ond = onset(flat)
    title = ""
    if ond:
        title = next((st["label"] for st in stages if st["id"] == ond["node"]), "")
    return {"session": (sess or {}).get("id") or "",
            "planned": bool(nodes),
            "stages": stages,
            "open": open_steps,
            "steps": flat,
            "counts": {"steps": len(flat),
                       "failed": sum(1 for s in flat if s["failed"]),
                       "stages": len(stages),
                       "open": len(open_steps)},
            "onset": ond,
            "verdict": _verdict(ond, title)}


def describe(sid, graph=None):
    """`build()` for a session id — the read side of `GET /api/sessions/<sid>/trace-tree`.

    Returns `{"error": ...}` for an unknown session, so a caller never has to
    distinguish "no such session" from "a session that did nothing".
    """
    from longrun.memory import stores
    sess = stores.load_session(sid) if sid else None
    if not sess:
        return {"error": "session not found", "session": sid or ""}
    g = graph if graph is not None else taskgraph.load(sid)
    return build(sess, g)
