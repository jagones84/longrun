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

# Ledger schema version: a doc written by an older version is re-derived from the
# transcript once (a brand-new store, so an upgrade simply rebuilds it).
VERSION = 2


def _publish(kind, **data):
    """Fan out to the harness feed; never let the feed break a title write.

    JAG-431r8: a Free.N title/summary set by the `chapters` tool must reach the
    open WebUI live (it used to need a reload).
    """
    try:
        from longrun.core import server
        return server.publish(kind, **data)
    except Exception:  # noqa: BLE001
        return None


def _safe(key):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(key or "unknown"))[:96]


def path_for(sid):
    """Absolute path of the ledger file for a session."""
    return os.path.join(THREADS_DIR, _safe(sid) + ".json")


def _load(sid):
    return read_json(path_for(sid), None)


def _save(doc):
    sid = doc.get("session")
    # JAG-431r4: never resurrect a DELETED session's ledger. A worker in flight
    # (abort is cooperative) can call record()/set_title() AFTER DELETE purged the
    # files; stores.save_session is tombstone-guarded but this ledger was not, so an
    # orphan data/threads/<sid>.json reappeared for a deleted session.
    try:
        from longrun.memory import stores as _stores
        if sid in getattr(_stores, "_DELETED_SESSIONS", ()):
            return doc
    except Exception:  # noqa: BLE001
        pass
    doc["updated"] = round(time.time(), 3)
    write_json(path_for(sid), doc)
    return doc


def _new_doc(sid):
    return {"v": VERSION, "session": sid, "seq": 0, "groups": [],
            "updated": round(time.time(), 3)}


def _cap(doc):
    groups = doc.get("groups") or []
    if len(groups) > MAX_GROUPS:
        doc["groups"] = groups[-MAX_GROUPS:]


# ------------------------------------------------------------------ grouping --


def _open(doc, kind, node, idx):
    doc["seq"] = int(doc.get("seq", 0)) + 1
    g = {"id": "g%d" % doc["seq"], "kind": kind, "node": node,
         "from": idx, "to": idx, "items": 0, "title": None, "digest": "",
         "summary": None, "req": None, "req_from": None, "ts": round(time.time(), 3)}
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
    is_user = (role == "user")
    if node:
        if last and last.get("kind") == "task" and last.get("node") == node:
            g = last
        else:
            g = _open(doc, "task", node, idx)
    else:
        if is_user or last is None or last.get("kind") == "task":
            g = _open(doc, "free", None, idx)
        else:
            g = last
    g["items"] = int(g.get("items", 0)) + 1
    if idx is not None:
        g["to"] = idx
    # A free thread is usually STARTED by a user turn: remember that request text and
    # its message index (the rewind anchor + the "request to …" title source).
    if is_user and g.get("kind") == "free" and not g.get("req"):
        g["req"] = str(text or "").strip().replace("\n", " ")[:200]
        g["req_from"] = idx
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


def _carry_meta(old, new):
    """Keep the agent-set title/summary across a schema REBUILD.

    Those fields ARE the point of the ledger, so a version upgrade must never silently
    drop them. Matched by ordinal + kind — a rebuild re-derives the same chronological
    order, so the i-th group of a kind maps to the i-th of the same kind.
    """
    if not old:
        return
    og, ng = (old.get("groups") or []), (new.get("groups") or [])
    for i, g in enumerate(ng):
        if i >= len(og):
            break
        o = og[i]
        if not isinstance(o, dict) or o.get("kind") != g.get("kind"):
            continue
        if o.get("title") and not g.get("title"):
            g["title"] = o["title"]
        if o.get("summary") and not g.get("summary"):
            g["summary"] = o["summary"]


def _doc_for(sid, sess=None):
    """Load the ledger, (re)building it when absent or written by an older schema.

    `sess` is the CURRENT session dict when the caller already has it (and, for
    `record`, one that does NOT yet include the item about to be filed).
    """
    doc = _load(sid)
    if doc is not None and doc.get("v") == VERSION:
        return doc
    if sess is None:
        try:
            from longrun.core import server
            sess = server.load_session(sid)
        except Exception:  # noqa: BLE001
            sess = None
    if not sess:
        return doc   # no transcript to rebuild from — keep whatever we had
    old = doc
    doc = _backfill(sess)
    _carry_meta(old, doc)
    _save(doc)
    return doc


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
            doc = _doc_for(sid, sess)
            if doc is None:
                doc = _new_doc(sid)
            _feed(doc, node, role, text, idx)
            _cap(doc)
            _save(doc)
    except Exception:  # noqa: BLE001 — the ledger is best-effort
        pass


def outline(sid):
    """Ordered groups of a session (task + free), oldest first.

    Backfills once, on demand, for a session that predates this ledger (or was
    written by an older schema version).
    """
    if not sid:
        return []
    doc = _doc_for(sid)
    return (doc or {}).get("groups", [])


def get(sid, gid):
    """One group by id, or None."""
    for g in outline(sid):
        if g.get("id") == gid:
            return g
    return None


def node_for(sid, node_id):
    """The task-graph node behind a TASK group (label, status, evidence), or None."""
    return _nodes_map(sid).get(node_id) if node_id else None


def set_title(sid, gid, title, summary=None):
    """Set a FREE group's TITLE and/or SUMMARY (its justification).

    `summary` is the free-group equivalent of a todo's evidence: a short "what/why it
    was about" note — stored in the durable ledger, so the agent can recollect it after
    any number of compactions. Returns (ok, group|error).
    """
    title = str(title or "").strip()[:200]
    summ = None if summary is None else str(summary).strip()[:600]
    with LOCK:
        doc = _doc_for(sid)
        if doc is None:
            return False, "no thread ledger for session %r" % sid
        for g in doc.get("groups", []):
            if g.get("id") == gid:
                if g.get("kind") != "free":
                    return False, ("group %s is a TASK group — a todo already carries "
                                   "its node label + evidence; only free groups take a "
                                   "title/summary" % gid)
                if title:
                    g["title"] = title
                if summary is not None:
                    g["summary"] = summ or None
                _save(doc)
                # JAG-431r8: tell the feed so any open WebUI repaints the Free.N
                # label/summary live (only for the session that changed).
                _publish("threads.updated", session=sid, gid=gid,
                         title=g.get("title"), summary=g.get("summary"))
                return True, g
        return False, "unknown group %r (call action=list for the ids)" % gid


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# Words that carry no meaning for a "request to …" label.
_STOP = {"the", "a", "an", "please", "can", "you", "could", "would", "i", "me",
         "my", "to", "of", "and", "or", "for", "is", "are", "it", "this", "that",
         "with", "in", "on", "at", "do", "does", "make", "let", "us", "we"}


def _short_ask(text, words=8):
    """A <=`words`-word paraphrase of a user request, for an auto title."""
    toks = [t for t in re.split(r"[^\w'./-]+", _norm(text)) if t]
    keep = [t for t in toks if t.lower() not in _STOP] or toks
    return " ".join(keep[:words]).strip(".,;:!? ")


def untitled_free(sid):
    """Every FREE group still missing a title, oldest first.

    The FULL list, with NO page cap — the 🏷 autoname subroutine (one direct LLM
    call, no tool budget) names them all at once. `render_untitled` pages the same
    set for the agent's `chapters action=untitled` view; that paging exists only
    because a chat turn may spend a bounded number of tool calls.
    """
    return [g for g in outline(sid)
            if g.get("kind") == "free" and not g.get("title")]


def render_untitled(sid, limit=8):
    """Render a compact batch of free groups that still need titles.

    The full thread can exceed the chat observation budget and be offloaded.
    This view returns only missing titles, with bounded previews, so the model
    can reach every group without reading a large offload.
    """
    groups = untitled_free(sid)
    if not groups:
        return "UNTITLED FREE GROUPS: none (0 remain)."
    try:
        page_size = max(1, min(int(limit or 8), 16))
    except (TypeError, ValueError):
        page_size = 8
    batch = groups[:page_size]
    lines = [
        "UNTITLED FREE GROUPS: %d remain; showing %d. "
        "Title each listed id, then call action=untitled again."
        % (len(groups), len(batch))
    ]
    for group in batch:
        request = _norm(group.get("req") or "")[:120] or "(not captured)"
        context = _norm(group.get("digest") or "")[:120] or "(not captured)"
        lines.append('id=%s request="%s" context="%s"'
                     % (group.get("id") or "", request, context))
    if len(groups) > len(batch):
        lines.append("More remain after this batch.")
    else:
        lines.append("This is the final batch; call action=untitled again to confirm none remain.")
    return "\n".join(lines)


def autotitle_untitled(sid, only_missing=True):
    """Give every UNTITLED free group a deterministic title + summary (JAG-451).

    The `chapters` tool (the 🏷 button) asks the MODEL to name free groups, but
    that is a full turn: it may never run, and a compaction can then fold a
    still-unnamed group into the summary and the chat loses its "Free.N · title"
    label. This is the cheap, deterministic safety net the harness runs BEFORE an
    auto-compaction (and on demand): it derives the title from the group's own
    captured user REQUEST (``req``) and the summary from its digest — no model,
    no network, so it can never stall a turn. Groups the model already named are
    left untouched. Returns the number of groups titled.
    """
    sid = str(sid or "").strip()
    if not sid:
        return 0
    n = 0
    with LOCK:
        doc = _doc_for(sid)
        if doc is None:
            return 0
        for g in (doc.get("groups") or []):
            if g.get("kind") != "free":
                continue
            if only_missing and g.get("title"):
                continue
            src = _norm(g.get("req") or g.get("digest") or "")
            if not src:
                continue
            ask = _short_ask(src)
            if ask and not g.get("title"):
                g["title"] = "request to %s" % ask[:160]
            if not g.get("summary"):
                g["summary"] = src[:240]
            n += 1
        if n:
            _save(doc)
    return n


def _anchor_index(msgs, g):
    """Message index that STARTS a free group (its first USER request, else its first
    message), or None.

    The stored ``req_from``/``from`` is a message index captured at append time, so
    after a compaction it can be stale. It is therefore VERIFIED against the group's
    ``req`` (a user turn whose text still starts with the request) and, failing that,
    re-found by content — a stale index must never label an unrelated message.
    """
    n = len(msgs)
    req = _norm(g.get("req"))[:60]
    cand = g.get("req_from")
    if cand is None:
        cand = g.get("from")

    def ok(i):
        if not isinstance(i, int) or not (0 <= i < n):
            return False
        m = msgs[i]
        if m.get("internal"):
            return False
        if req:
            return (m.get("role") == "user"
                    and _norm(m.get("content")).startswith(req))
        return True

    if ok(cand):
        return cand
    if req:
        for i, _m in enumerate(msgs):
            if ok(i):
                return i
    return None


def sync_chapters(sess):
    """Mirror each TITLED free group's title/summary onto the message that STARTS it.

    The WebUI labels a rendered free group from the CHAPTER metadata carried by that
    message (``messages[i]["chapter"]``), NOT from an ordinal — so the label follows
    the group wherever it is rendered and SURVIVES compaction (a retained message is
    kept verbatim; a group whose start message was summarized away is not rendered
    either). Idempotent, best-effort, and it never calls ``save_session`` (the caller
    owns the session dict). Returns the number of messages whose chapter changed.
    """
    sid = (sess or {}).get("id")
    if not sid:
        return 0
    try:
        doc = _load(sid)
    except Exception:  # noqa: BLE001
        return 0
    if not doc:
        return 0
    msgs = sess.get("messages") or []
    changed = 0
    for g in (doc.get("groups") or []):
        if g.get("kind") != "free":
            continue
        title, summary = g.get("title"), g.get("summary")
        if not (title or summary):
            continue
        i = _anchor_index(msgs, g)
        if i is None:
            continue
        want = {"gid": g.get("id"), "title": title or "", "summary": summary or "",
                "req_from": g.get("req_from")}
        if msgs[i].get("chapter") != want:
            msgs[i]["chapter"] = want
            changed += 1
    return changed


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
            # JAG-431r4: `from`/`to` are INCLUSIVE message indices, and `cut` is the
            # EXCLUSIVE bound (the anchor index captured before the message was
            # appended, so the transcript keeps 0..cut-1). Clipping to `cut` advertised
            # one message (index `cut`) that the rewind had just removed.
            if isinstance(g.get("to"), int) and g["to"] >= cut:
                g["to"] = cut - 1
            kept.append(g)
        if len(kept) != len(groups):
            doc["groups"] = kept
            _save(doc)
        return len(groups) - len(kept)


def _nodes_map(sid):
    """{node id: node} for the session's task graph (the todos' labels + JUSTIFICATION)."""
    try:
        from longrun.plan import taskgraph
        g = taskgraph.load(sid) or {}
        return {n.get("id"): n for n in (g.get("nodes") or [])}
    except Exception:  # noqa: BLE001
        return {}


def _why(node):
    """A todo's justification: its latest evidence text, else its superseded reason."""
    ev = [e for e in ((node or {}).get("evidence") or []) if (e.get("text") or "").strip()]
    if ev:
        return " \u00b7 why: \u201c%s\u201d" % str(ev[-1]["text"]).replace("\n", " ")[:140]
    reason = (node or {}).get("reason")
    if reason:
        return " \u00b7 reason: \u201c%s\u201d" % str(reason).replace("\n", " ")[:140]
    return ""


def render(sid, limit=200):
    """The whole thread as a compact ordered text block (for the `chapters` tool).

    Carries the JUSTIFICATION of every group (a todo's evidence / a free group's
    summary), so the agent can recollect WHY after any number of compactions.
    """
    groups = outline(sid)
    if not groups:
        return ("THREAD (this session): no groups yet — the session is empty or brand "
                "new. Groups appear as you chat and take on tasks.")
    nodes = _nodes_map(sid)
    show = groups[-int(limit):] if limit else groups
    base = len(groups) - len(show)
    lines = ["THREAD (this session) — %d group(s), chronological "
             "(task = a todo node; free = chat with no todo):" % len(groups)]
    for i, g in enumerate(show, base + 1):
        where = "msg %s-%s \u00b7 %s item%s" % (g.get("from"), g.get("to"),
                                                g.get("items"),
                                                "" if g.get("items") == 1 else "s")
        if g.get("kind") == "task":
            n = nodes.get(g.get("node")) or {}
            lines.append("  #%d task %s [%s] %s%s  <%s \u00b7 id=%s>"
                         % (i, g.get("node"), n.get("status") or "?",
                            (n.get("label") or "").replace("\n", " ")[:110],
                            _why(n), where, g.get("id")))
        else:
            req = (g.get("req") or "").strip()
            dig = (g.get("digest") or "").strip()
            body = req or dig
            # JAG-451: an explicit [UNTITLED] marker lets the agent find every
            # free group that still lacks a name WITHOUT parsing the `title=`
            # token (which also appears in the tool's own instructions and so
            # produced false positives / silently skipped groups).
            tag = "" if g.get("title") else " [UNTITLED]"
            extra = ""
            if g.get("title"):
                extra += " \u00b7 title=\u201c%s\u201d" % str(g["title"])[:80]
            if g.get("summary"):
                extra += " \u00b7 summary=\u201c%s\u201d" % str(g["summary"]).replace("\n", " ")[:200]
            lines.append("  #%d free%s %s%s  <%s \u00b7 id=%s>"
                         % (i, tag, "\u201c%s\u201d" % body if body else "(no text yet)",
                            extra, where, g.get("id")))
    lines.append("Every group carries its justification (a task's evidence / a free "
                 "group's summary). Use action=read id=<gN> for the full record. A free "
                 "group marked [UNTITLED] has no name yet: title it with action=title "
                 "id=<gN> title=\"request to <short ask>\" summary=\"<what/why, one line>\" "
                 "\u2014 one action=title call per [UNTITLED] group, until none remain.")
    return "\n".join(lines)
