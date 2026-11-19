"""Reversible, agent-directed curation of individual tool results (ITER-01 / R162).

Source: J.-P. Franke, *Agent-Controlled Forgetting for Tool-Using Agents: Reversible
Context Curation in Practice*, arXiv:2610.10590 (2026), §3.1-§3.2.

The acting model names tool results it has already interpreted; the harness archives
the raw payload and replaces the body with a short note **at the same position**.
`recover` returns the archived payload as a NEW card and never re-runs the tool — an
archived log is evidence of the earlier observation, not a fresh measurement. The batch
is validated whole: an unknown, duplicate or already-curated target refuses the entire
batch, so a partial mutation is impossible. Only tool cards are selectable; user,
system and assistant messages are not.

Deliberate limit: the card is what the compaction manifest
(`model/context_engine.py:manifest_block`) and the context panel re-read, while the
in-turn observation is already bounded by `tool_obs_limit` and the offload path
(`agent/agent.py:_offload_observation`). Curation therefore shrinks what the harness
re-reads after compaction and keeps the payload exactly recoverable; it does not
rewrite the live turn's transcript.
"""
from __future__ import annotations

import json
import os
import time

from longrun.memory import stores
from longrun.util import paths

VERSION = "longrun-context-curation/1"
ARCHIVE_DIRNAME = "context_archive"


def archive_root():
    return (os.environ.get("LONGRUN_CONTEXT_ARCHIVE_DIR")
            or os.path.join(paths.DATA_DIR, ARCHIVE_DIRNAME))


def _archive_path(sid, handle):
    safe = "".join(ch for ch in str(handle) if ch.isalnum() or ch in "-_") or "card"
    return os.path.join(archive_root(), str(sid or "unknown"), safe + ".json")


def newest_session():
    """The session JSON with the newest mtime, or "" when there is none.

    A tool handler is not given the session id, so an omitted `session` argument
    resolves to the most recently used one; the resolved id is returned in the
    result so the operator can see which session was curated.
    """
    best, stamp = "", -1.0
    try:
        for entry in os.scandir(paths.SESSIONS_DIR):
            if not entry.name.endswith(".json"):
                continue
            mtime = entry.stat().st_mtime
            if mtime > stamp:
                best, stamp = entry.name[:-5], mtime
    except OSError:
        return ""
    return best


def _note_text(note, handle):
    return ('%s\n[curated %s · payload archived — recover with '
            'context{action:"recover", ref:"%s"}]' % (note.strip(), handle, handle))


def apply_batch(sid, sess, targets):
    """Archive every target, then replace its body with the note. All or nothing."""
    if not isinstance(targets, list) or not targets:
        return {"ok": False, "error": "batch-refused",
                "refused": ["targets must be a non-empty list"], "changed": 0}
    refused, seen, plan = [], set(), []
    for i, item in enumerate(targets):
        if not isinstance(item, dict):
            refused.append("target %d is not an object" % i)
            continue
        handle = str(item.get("card") or item.get("id") or "").strip()
        note = str(item.get("note") or "").strip()
        if not handle:
            refused.append("target %d has no card handle" % i)
            continue
        if handle in seen:
            refused.append("duplicate card %s" % handle)
            continue
        seen.add(handle)
        card = stores.card_by_handle(sess, handle)
        if card is None:
            refused.append("unknown card %s" % handle)
            continue
        if card.get("curated"):
            refused.append("card %s is already curated" % handle)
            continue
        if not str(card.get("result") or "").strip() and not card.get("data"):
            refused.append("card %s has no payload to archive" % handle)
            continue
        if not note:
            refused.append("card %s has an empty note" % handle)
            continue
        plan.append((handle, note, card))
    if refused:
        return {"ok": False, "error": "batch-refused", "refused": refused, "changed": 0}
    changed = []
    for handle, note, card in plan:
        rec = {"version": VERSION, "session": sid, "card": handle,
               "tool": card.get("tool"), "args": card.get("args"),
               "result": card.get("result") or "", "data": card.get("data"),
               "error": card.get("error"), "exit_code": card.get("exit_code"),
               "node": card.get("node"), "ts": card.get("ts"),
               "note": note, "curated_at": round(time.time(), 3)}
        path = _archive_path(sid, handle)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        card["curated"] = True
        card["note"] = note
        card["archive"] = path
        card["result"] = _note_text(note, handle)
        changed.append(handle)
    return {"ok": True, "changed": len(changed), "cards": changed}


def recover(sid, sess, ref):
    """Append the archived payload as a NEW card; the tool is never re-run."""
    handle = str(ref or "").strip()
    if not handle:
        return {"ok": False, "error": "no-ref"}
    path = _archive_path(sid, handle)
    if not os.path.isfile(path):
        return {"ok": False, "error": "not-archived", "card": handle}
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    stores.persist_tool_card(sess, rec.get("tool") or "context.recover", True,
                             args={"recovered_from": handle},
                             result=rec.get("result") or "", data=rec.get("data"),
                             exit_code=rec.get("exit_code"), node=rec.get("node"))
    card = sess["tool_cards"][-1]
    card["recovered_from"] = handle
    return {"ok": True, "card": card["id"], "recovered_from": handle,
            "chars": len(rec.get("result") or "")}


def curated(sess):
    out = []
    for card in sess.get("tool_cards") or []:
        if card.get("curated"):
            out.append({"card": card.get("id"), "tool": card.get("tool"),
                        "note": card.get("note"), "archive": card.get("archive")})
    return out


def handle(args, run_id=None):
    """The `context` tool. Actions: apply | recover | list."""
    action = str(args.get("action") or "list").strip().lower()
    sid = str(args.get("session") or "").strip() or newest_session()
    if not sid:
        return {"ok": False, "error": "no-session", "version": VERSION}
    sess = stores.load_session(sid)
    if sess is None:
        return {"ok": False, "error": "unknown-session", "session": sid, "version": VERSION}
    if action in ("apply", "curate"):
        res = apply_batch(sid, sess, args.get("targets"))
    elif action in ("recover", "restore"):
        res = recover(sid, sess, args.get("ref"))
    elif action in ("list", "curated"):
        rows = curated(sess)
        res = {"ok": True, "count": len(rows), "curated": rows}
    else:
        return {"ok": False, "error": "unknown-action", "action": action, "version": VERSION}
    if res.get("ok") and action in ("apply", "curate", "recover", "restore"):
        stores.save_session(sess)
    return dict(res, session=sid, version=VERSION)
