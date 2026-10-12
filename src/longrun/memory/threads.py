"""Session thread ledger — a durable, compaction-proof outline of a session's chat.

A long chat is a chronological stream of GROUPS: TASK groups (a contiguous run of
work on a todo-graph node) and FREE groups (runs of chat with no todo behind them —
the WebUI's ``Free.N``). Long sessions are compacted IN PLACE: ``compact_session``
rewrites ``sess["messages"]`` (older turns collapse into a single summary), so the
prose of an old free thread is DESTROYED. The durable event log cannot help either —
it is a pruned REPLAY buffer, not an archive.

This module keeps its OWN tiny per-session ledger (``data/threads/<sid>.json``)
updated at the ONE choke point every persisted item goes through
(``stores.append_message`` / ``persist_tool_card`` / ``persist_inject``) — i.e.
BEFORE any compaction can touch the transcript — so that after any number of
compactions the agent can still:

  * see the WHOLE thread in chronological order (task + free), and
  * recover a bounded DIGEST of a group whose content was compacted away, so it can
    give that group a meaningful TITLE.

Grouping mirrors the WebUI ``who()`` logic: an item carrying a ``node`` belongs to
that node's TASK group; a node-less item belongs to the current FREE group; a USER
message always opens a NEW free group; a node-less item after a task group opens a
new free group too. Stdlib-only.
"""
import os
import re
import threading
import time

from longrun.util.fswrite import read_json, write_json
from longrun.util.paths import THREADS_DIR

# Keep the durable ledger bounded: a per-group digest cap and a global group cap.
MAX_DIGEST = int(os.environ.get("LONGRUN_THREAD_DIGEST", "1500"))
MAX_LINE = 240
MAX_GROUPS = int(os.environ.get("LONGRUN_THREAD_GROUPS", "2000"))

LOCK = threading.RLock()


def _safe(key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(key or "unknown"))[:96]


def path_for(sid):
    """Absolute path of the ledger file for a session."""
    return os.path.join(THREADS_DIR, _safe(sid) + ".json")


def _load(sid):
    return read_json(path_for(sid), None)


def _save(doc):
    doc["updated"] = round(time.time(), 3)
    write_json(path_for(doc.get("session")), doc)
    return doc


def _new_doc(sid):
    return {"session": sid, "seq": 0, "groups": [], "updated": round(time.time(), 3)}


def _cap(doc):
    groups = doc.get("groups") or []
    if len(groups) > MAX_GROUPS:
        doc["groups"] = groups[-MAX_GROUPS:]


# ------------------------------------------------------------------ grouping --


def _open(doc, kind, node, idx):
    doc["seq"] = int(doc.get("seq", 0)) + 1
    g = {"id": "g%d" % doc["seq"], "kind": kind, "node": node,
         "from": idx, "to": idx, "items": 0, "title": None, "digest": "",
         "ts": round(time.time(), 3)}
    doc["groups"].append(g)
    return g


def _digest(g, text):
    s = str(text or "").strip().replace("\n", " ")
    if not s or len(g.get("digest", "")) >= MAX_DIGEST:
        return
    add = (" · " if g.get("digest") else "") + s[:MAX_LINE]
    g["digest"] = (g.get("digest", "") + add)[:MAX_DIGEST]


def _feed(doc, node, role, text, idx):
    """Append ONE item to the ledger, opening/extending the right group."""
    groups = doc["groups"]
    last = groups[-1] if groups else None
    if node:
        if last and last.get("kind") == "task" and last.get("node") == node:
            g = last
        else:
            g = _open(doc, "task", node, idx)
    else:
        if role == "user" or last is None or last.get("kind") == "task":
            g = _open(doc, "free", None, idx)
        else:
            g = last
    g["items"] = int(g.get("items", 0)) + 1
    if idx is not None:
        g["to"] = idx
    _digest(g, text)


def _items(sess):
    """Chronological item stream (messages + tool cards + injects) for a session.

    Uses the SAME ordering the WebUI ``loadHistory`` uses (ts first, then the
    message boundary), so a backfilled ledger matches the rendered chat.
    """
    msgs = sess.get("messages") or []
    n = len(msgs)

    def ts_at(a):
        try:
            a = int(a)
        except (TypeError, ValueError):
            a = n
        for k in range(max(0, a), n):
            t = msgs[k].get("ts")
            if isinstance(t, (int, float)):
                return t
        return None

    evs = []
    for i, m in enumerate(msgs):
        if m.get("internal"):
            continue
        evs.append((m.get("ts"), i, "m", m))
    for c in (sess.get("tool_cards") or []):
        key = c.get("ts") if isinstance(c.get("ts"), (int, float)) else ts_at(c.get("after", n))
        evs.append((key, (c.get("after") if c.get("after") is not None else n), "c", c))
    for r in (sess.get("injects") or []):
        key = r.get("ts") if isinstance(r.get("ts"), (int, float)) else ts_at(r.get("after", n))
        evs.append((key, (r.get("after") if r.get("after") is not None else n), "i", r))
    evs.sort(key=lambda e: (e[0] if e[0] is not None else float("inf"), e[1]))
    return evs


def _backfill(sess):
    """Derive a ledger from a session's current transcript (sessions predating it)."""
    doc = _new_doc(sess.get("id"))
    for _ts, idx, t, v in _items(sess):
        if t == "m":
            _feed(doc, v.get("node"), v.get("role"), v.get("content", ""), idx)
        elif t == "c":
            _feed(doc, v.get("node"), None, "\u2699 " + str(v.get("tool", "")), v.get("after"))
        else:
            _feed(doc, v.get("node"), None, v.get("text", ""), v.get("after"))
    return doc


# ------------------------------------------------------------------- public --


def record(sess, node=None, role=None, text="", idx=None):
    """File ONE persisted item into the session's ledger (call BEFORE the store
    writes it, so a first-time backfill does not see the item twice).

    Never raises: a ledger failure must never break a chat turn.
    """
    sid = (sess or {}).get("id")
    if not sid:
        return
    if isinstance(node, dict):
        node = node.get("id")
    try:
        with LOCK:
            doc = _load(sid)
            if doc is None:
                doc = _backfill(sess)
            _feed(doc, node, role, text, idx)
            _cap(doc)
            _save(doc)
    except Exception:  # noqa: BLE001 — the ledger is best-effort
        pass


def outline(sid):
    """Ordered groups of a session (task + free), oldest first.

    Backfills once, on demand, for a session that predates this ledger.
    """
    if not sid:
        return []
    doc = _load(sid)
    if doc is None:
        try:
            from longrun.core import server
            sess = server.load_session(sid)
        except Exception:  # noqa: BLE001
            sess = None
        if not sess:
            return []
        with LOCK:
            doc = _backfill(sess)
            _save(doc)
    return doc.get("groups", [])


def get(sid, gid):
    """One group by id, or None."""
    for g in outline(sid):
        if g.get("id") == gid:
            return g
    return None


def set_title(sid, gid, title):
    """Set (or clear) the TITLE of a FREE group. Returns (ok, group|error)."""
    title = str(title or "").strip()[:200]
    with LOCK:
        doc = _load(sid)
        if doc is None:
            # trigger the lazy backfill, then reload
            outline(sid)
            doc = _load(sid)
        if doc is None:
            return False, "no thread ledger for session %r" % sid
        for g in doc.get("groups", []):
            if g.get("id") == gid:
                if g.get("kind") != "free":
                    return False, ("group %s is a TASK group — todos already carry "
                                   "their node label; only free groups need a title" % gid)
                g["title"] = title or None
                _save(doc)
                return True, g
        return False, "unknown group %r (call action=list for the ids)" % gid


def clear(sid):
    """Drop a session's ledger (used by /clear — the session itself is wiped)."""
    try:
        os.remove(path_for(sid))
        return True
    except OSError:
        return False


def truncate(sid, upto_idx):
    """Drop groups that START at/after a message index (used by rewind)."""
    try:
        cut = int(upto_idx)
    except (TypeError, ValueError):
        return 0
    with LOCK:
        doc = _load(sid)
        if doc is None:
            return 0
        groups = doc.get("groups", [])
        kept = []
        for g in groups:
            frm = g.get("from")
            if isinstance(frm, int) and frm >= cut:
                continue
            if isinstance(g.get("to"), int) and g["to"] >= cut:
                g["to"] = cut
            kept.append(g)
        if len(kept) != len(groups):
            doc["groups"] = kept
            _save(doc)
        return len(groups) - len(kept)


def _node_labels(sid):
    try:
        from longrun.plan import taskgraph
        g = taskgraph.load(sid) or {}
        return {n.get("id"): (n.get("label") or "") for n in (g.get("nodes") or [])}
    except Exception:  # noqa: BLE001
        return {}


def render(sid, limit=200):
    """The whole thread as a compact ordered text block (for the `chapters` tool)."""
    groups = outline(sid)
    if not groups:
        return ("THREAD (this session): no groups yet — the session is empty or brand "
                "new. Groups appear as you chat and take on tasks.")
    labels = _node_labels(sid)
    show = groups[-int(limit):] if limit else groups
    base = len(groups) - len(show)
    lines = ["THREAD (this session) — %d group(s), chronological "
             "(task = a todo node; free = chat with no todo):" % len(groups)]
    for i, g in enumerate(show, base + 1):
        where = "msg %s-%s \u00b7 %s item%s" % (g.get("from"), g.get("to"),
                                                g.get("items"),
                                                "" if g.get("items") == 1 else "s")
        title = (" title=%r" % g["title"]) if g.get("title") else ""
        if g.get("kind") == "task":
            lbl = labels.get(g.get("node")) or ""
            lines.append("  #%d task %s  [%s]  <%s \u00b7 id=%s>%s"
                         % (i, g.get("node"), lbl, where, g.get("id"), title))
        else:
            dig = (g.get("digest") or "").strip()
            lines.append("  #%d free  %s  <%s \u00b7 id=%s>%s"
                         % (i, "\u201c%s\u201d" % dig if dig else "(no text yet)",
                            where, g.get("id"), title))
    lines.append("Use action=read id=<gN> for a group's content, action=title id=<gN> "
                 "title=\"…\" to name a FREE group.")
    return "\n".join(lines)
