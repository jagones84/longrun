"""Session / plan / task persistence + the per-session runtime clean-up.

Owns the on-disk session transcripts (data/sessions/*.json), the plan + task
stores, the job / workspace bookkeeping and the append/persist helpers the chat
loop calls. Extracted from ``server.py`` (JAG-376). Stdlib + sibling modules only.
"""
import atexit
import json
import os
import re
import shutil
import threading
import time
import uuid

from longrun.memory import threads as threads_mod
from longrun.plan import taskgraph
from longrun.core.events import (_ACTIVE_CHAT, _ACTIVE_CHAT_LOCK, _TURN_LOCKS,
                     _TURN_LOCKS_GUARD, _turn_lock, publish)
from longrun.util.fswrite import read_json, write_json, write_text
from longrun.util.paths import DATA_DIR, SESSIONS_DIR, REPO_ROOT as REPO, _JOBSEQ_FILE
from longrun.util.steering import (STEER_INBOX, _steer_lock, clear_abort,
                                   forget_steers, live_steers, push_abort)
from longrun.util.tracing import (_REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS,
                                  git_revision, git_dirty)
from longrun.model import context_limits as ctx_limits


# ---------------------------------------------------------------- stores ----


def _ensure_dirs():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _store_path(name):
    return os.path.join(DATA_DIR, name)


def load_plan():
    return read_json(_store_path("plan.json"), {"goal": "", "steps": [], "updated": None})


def save_plan(plan):
    plan["updated"] = round(time.time(), 3)
    write_json(_store_path("plan.json"), plan)
    publish("plan.update", goal=plan.get("goal", ""), steps=plan.get("steps", []))


def load_tasks():
    return read_json(_store_path("tasks.json"), {"tasks": [], "updated": None})


def save_tasks(store):
    store["updated"] = round(time.time(), 3)
    write_json(_store_path("tasks.json"), store)
    publish("tasks.update", tasks=store.get("tasks", []))


_SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")

# replay_record: the tools whose card proves the prefix changed the workspace,
# and the ones that may have (a shell command or a script can run anything).
_EFFECT_TOOLS = frozenset(("fs.write", "fs.edit"))
_MAYBE_EFFECT_TOOLS = frozenset(("shell", "shell.exec", "python", "python.run",
                                 "git", "git.run"))


def _valid_sid(sid):
    """A session id becomes a FILE name, so it must be a plain token (JAG-230).

    Ids arrive straight from the client (query string / JSON body). Anything
    with a path separator, a `..` segment or a non-string type is a traversal /
    type-confusion attempt and must never reach the filesystem.
    """
    return (isinstance(sid, str) and ".." not in sid
            and _SID_RE.match(sid) is not None)


def load_session(sid):
    if not _valid_sid(sid):
        return None
    doc = read_json(os.path.join(SESSIONS_DIR, sid + ".json"), None)
    if isinstance(doc, dict):
        # v1045: stamp the SNAPSHOT (never written to disk) so `save_session` can
        # tell a copy read BEFORE a deliberate clear from one read after it — the
        # running turn holds the transcript in memory and saves it later.
        doc["_loaded_at"] = time.time()
    return doc


# JAG-222: a session deleted WHILE its turn is running used to be RESURRECTED —
# the (not-aborted) worker persisted the final reply and recreated the file. A
# tombstone makes the write a no-op until the id is deliberately re-created.
# JAG-315: the tombstone is now PERSISTED (`.deleted`, deliberately not `*.json`
# so `list_sessions` never reads it as a session) and survives a restart; and
# `get_or_create_session` no longer silently resurrects a deleted id — a chat or
# attach that still references it gets a FRESH session instead.
_DELETED_SESSIONS = set()
_deleted_lock = threading.Lock()
_TOMBSTONE_FILE = os.path.join(SESSIONS_DIR, ".deleted")
# v1045: `clear_session` ran while a turn was still holding its own transcript
# snapshot. The turn keeps the messages in memory and saves them at the end (and
# on every tool card), so the wipe was written back over — measured 2026-11-15
# 18:28:50: `session.cleared` fired, then the aborted turn re-saved 130 messages.
# This records WHEN each session was cleared in this process, so a snapshot read
# before that instant can never write its transcript again.
_CLEARED_AT = {}
# v947: one write lock per session id — see `_save_lock`/`save_session`.
_SAVE_LOCKS = {}
_SAVE_GUARD = threading.Lock()


def _load_tombstones():
    """Reload the durable deleted-session ids (a missing file is fine)."""
    try:
        with open(_TOMBSTONE_FILE, encoding="utf-8") as f:
            for line in f:
                sid = line.strip()
                if sid and _valid_sid(sid):
                    _DELETED_SESSIONS.add(sid)
    except (FileNotFoundError, OSError):
        pass


def _persist_tombstones():
    """Write the deleted-session ids atomically so a restart cannot forget them."""
    try:
        write_text(_TOMBSTONE_FILE, "".join(sid + "\n" for sid in sorted(_DELETED_SESSIONS)))
    except OSError:
        pass


_load_tombstones()


# JAG-455: a deleted transcript is MOVED to trash/, never unlinked. An operator who
# deletes a row by mistake (or deletes DURING a run, while the turn worker is still
# writing) can recover it, and the oldest files are pruned so the trash cannot grow
# without bound. Repeated DELETE is now a clean 404 (the file is already gone).
TRASH_DIR = os.path.join(DATA_DIR, "trash")
_TRASH_KEEP = 200
_TRASH_KEEP_SECS = 30 * 86400


def _trash_move(path):
    """Move a deleted artifact into data/trash/ (best-effort, keeps name + ext)."""
    try:
        if not os.path.exists(path):
            return False
        os.makedirs(TRASH_DIR, exist_ok=True)
        base = os.path.basename(path)
        dest = os.path.join(TRASH_DIR, base)
        if os.path.exists(dest):
            dest = os.path.join(TRASH_DIR, "%d-%s" % (int(time.time()), base))
        os.replace(path, dest)
        return True
    except OSError:
        return False


def _prune_trash():
    """Cap data/trash/: keep the newest `_TRASH_KEEP`, drop the rest after 30 days.

    v973: entries may be FILES or DIRECTORIES (a whole session sub-folder is moved
    here as one entry), so the removal has to match the kind.
    """
    try:
        paths = [os.path.join(TRASH_DIR, f) for f in os.listdir(TRASH_DIR)]
        paths.sort(key=os.path.getmtime, reverse=True)
        now = time.time()
        for p in paths[_TRASH_KEEP:]:
            try:
                if now - os.path.getmtime(p) <= _TRASH_KEEP_SECS:
                    continue
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.unlink(p)
            except OSError:
                pass
    except OSError:
        pass


# ------------------------------------------------------------ v973: offload ---
# `data/offload/<session>/NNN_<tool>.txt` holds every oversized tool observation
# verbatim, so the model can read it back instead of losing the tail to a
# truncation. Nothing ever removed one: measured 2026-11-14 — 158 session
# folders, 32 MB, the oldest 13 days old. The bound is the same shape as
# `_prune_trash` above, and the safety argument is the same: the file is a
# preview the model already consumed, and the observation itself still travels in
# the session transcript and the run record.
OFFLOAD_DIR = os.path.join(DATA_DIR, "offload")


def _offload_keep_files():
    try:
        from longrun.model import context_limits
        return max(0, int(context_limits.limit("offload_keep_files")))
    except Exception:  # noqa: BLE001 — an unreadable budget means "no cap"
        return None


def _offload_keep_secs():
    try:
        from longrun.model import context_limits
        return max(0.0, float(context_limits.limitf("offload_keep_days")) * 86400.0)
    except Exception:  # noqa: BLE001
        return None


def prune_offload(session_id=None, keep_files=None, keep_days=None):
    """Bound data/offload/: newest `offload_keep_files` per session, and nothing
    older than `offload_keep_days` (v973). Returns `{ok, removed, bytes, kept}`.

    `session_id` limits the walk to one session (the writer's cheap, exact call);
    with no argument it sweeps every session (the delete-time and manual call).
    """
    kf = keep_files if keep_files is not None else _offload_keep_files()
    kd = (keep_days * 86400.0) if keep_days is not None else _offload_keep_secs()
    roots = ([os.path.join(OFFLOAD_DIR, session_id)] if session_id
             else [os.path.join(OFFLOAD_DIR, d)
                   for d in (os.listdir(OFFLOAD_DIR)
                             if os.path.isdir(OFFLOAD_DIR) else [])])
    now = time.time()
    removed = 0
    freed = 0
    for root in roots:
        try:
            names = [n for n in os.listdir(root)
                     if os.path.isfile(os.path.join(root, n))]
        except OSError:
            continue
        rows = []
        for n in names:
            p = os.path.join(root, n)
            try:
                rows.append((os.path.getmtime(p), p))
            except OSError:
                continue
        rows.sort(reverse=True)                     # newest first
        for i, (mt, p) in enumerate(rows):
            over = (kf is not None and i >= kf)
            stale = (kd is not None and (now - mt) > kd)
            if not (over or stale):
                continue
            try:
                size = os.path.getsize(p)
                os.unlink(p)
                removed += 1
                freed += size
            except OSError:
                pass
        # A session folder that no longer holds a file is not kept as an empty shell.
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return {"ok": True, "removed": removed, "bytes": freed,
            "kept_files": kf, "kept_days": kd}


#: v973: the two per-session FOLDER stores. Both are keyed by session id, both are
#: written on demand, and neither was swept when its session went away.
SESSION_FOLDER_STORES = ("attachments", "sandbox")


def sweep_session_folders(days=None, dry_run=False):
    """Move a GONE session's `attachments`/`sandbox` folder to trash (v973).

    The same rule as `taskgraph.sweep_orphans` (v812): an artifact whose owner no
    longer exists is unreachable and must not pile up in the data home. Measured
    2026-11-14 — **151 of 160 `sandbox` folders and 5 of 13 `attachments` folders
    belonged to sessions that no longer existed**.

    The grace window is the SAME `graph_orphan_days` the graph sweep uses: one
    number for one rule (an owner-less artifact), so a session that is momentarily
    missing is never swept. Recovery is the ordinary one — the folder moves into
    `data/trash/`, it is not unlinked.
    """
    try:
        from longrun.model import context_limits
        grace = float(days if days is not None
                      else context_limits.limit("graph_orphan_days")) * 86400.0
    except Exception:  # noqa: BLE001 — no readable grace means "do not sweep"
        return {"ok": False, "error": "no grace window"}
    try:
        live = {n[:-5] for n in os.listdir(SESSIONS_DIR) if n.endswith(".json")}
    except OSError:
        return {"ok": False, "error": "no sessions dir"}
    now = time.time()
    removed = []
    for sub in SESSION_FOLDER_STORES:
        root = os.path.join(DATA_DIR, sub)
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            if n in live:
                continue                     # the owner is still here — keep it
            d = os.path.join(root, n)
            try:
                if not os.path.isdir(d) or (now - os.path.getmtime(d)) <= grace:
                    continue
                if dry_run:
                    removed.append(os.path.join(sub, n))
                elif _trash_move(d):
                    removed.append(os.path.join(sub, n))
            except OSError:
                pass
    return {"ok": True, "removed": removed, "dry_run": bool(dry_run)}


def purge_offload(session_id):
    """Remove one session's offloaded observations entirely (v973).

    Same rule as `checkpoints.purge_session`: deleting a session must not leave
    its offload folder behind for a later read to find.
    """
    if not session_id:
        return 0
    root = os.path.join(OFFLOAD_DIR, session_id)
    removed = 0
    try:
        for n in os.listdir(root):
            p = os.path.join(root, n)
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
        os.rmdir(root)
    except OSError:
        pass
    return removed


def _save_lock(sid):
    """The per-session write lock (v947).

    A turn saves its own dict at the end; a handoff/escalation saves an inject
    from a dict it read earlier. Two writers interleaving their read-merge-write
    lost whichever list the other had (a deliverable disappeared from the
    transcript). One short-held lock per session serialises the write; it is an
    RLock because `persist_inject` → `save_session` nests inside a turn's save.
    """
    with _SAVE_GUARD:
        lock = _SAVE_LOCKS.get(sid)
        if lock is None:
            lock = _SAVE_LOCKS[sid] = threading.RLock()
        return lock


def _owns_turn(sid):
    """True when the CALLING thread is this session's turn worker (v947).

    The turn holds `_turn_lock(sid)` for its whole life; every other writer
    (a job handoff, an escalation, a REST call) does not. The distinction is what
    makes the merge safe: the turn's list is the authority and may legitimately
    SHRINK (a rewrite, a trim), while a side writer's list is an older copy that
    must never rewind it.
    """
    try:
        is_owned = getattr(_turn_lock(sid), "_is_owned", None)
        return bool(is_owned and is_owned())
    except Exception:  # noqa: BLE001 — no lock knowledge means "side writer"
        return False


def _adopt_disk_tail(sess, field):
    """Carry the records another writer appended that this copy never saw (v947).

    Only the PROVABLE case is merged: the in-memory `field` is a prefix of the
    one on disk, i.e. this writer read an older copy and only ADDED to it, so
    taking the disk list loses nothing. Anything else — a rewritten head, a
    deletion — keeps the in-memory list: there the writer is the authority, and a
    merge would resurrect records removed on purpose.
    """
    try:
        sid = (sess or {}).get("id")
        if not sid:
            return
        mine = sess.get(field) or []
        theirs = (load_session(sid) or {}).get(field) or []
        if len(theirs) <= len(mine):
            return
        if list(mine) != theirs[:len(mine)]:
            return
        sess[field] = list(theirs)
    except Exception:  # noqa: BLE001 — a failed merge must never block a save
        return


def save_session(sess, truncate=False):
    """Persist one session, merging records another writer appended (v947).

    `truncate=True` is for a DELIBERATE wipe (`clear_session`,
    `reset_stateless_session`): an empty list is indistinguishable from "a side
    writer that never held these records", so the tail adoption must be skipped
    or the wipe is undone on the next save (the v534 A2 pin was red because of
    exactly that). Every other writer keeps the merge.
    """
    sid = sess.get("id")
    if not _valid_sid(sid):
        return  # JAG-230: never write a transcript to a path from an unsafe id
    with _deleted_lock:
        if sid in _DELETED_SESSIONS:
            return  # JAG-222: the session was deleted — never resurrect it
    # v947: read-merge-write under ONE lock per session. A turn and a handoff hold
    # different snapshots of the same session; with the two interleaved, the last
    # writer won the whole document and the other's list vanished (a coordinator's
    # deliverable disappeared from the transcript while `runs[coord].result` still
    # held it). The merge is a strict-prefix adoption: only records this copy
    # never saw are taken.
    with _save_lock(sid):
        # v1045: a clear during the turn outranks this snapshot. The loop holds the
        # transcript in memory and saves it at the end (and on every tool card), so
        # a snapshot read BEFORE the clear must never write messages/cards/injects
        # again — that is how 130 pre-clear messages came back over a `session.cleared`.
        stamp = float(sess.get("_loaded_at") or 0.0)
        cleared = float(_CLEARED_AT.get(sid) or 0.0)
        stale = bool(sess.get("_stale_after_clear")) or bool(
            stamp and cleared and stamp < cleared)
        if stale:
            # Sticky: every later save from this same in-memory turn is discarded
            # too (the interrupt note, the last cards), until a NEW turn reloads.
            sess["_stale_after_clear"] = True
        # A field the operator changed WHILE this dict was being written (the turn's
        # stale copy) must not come back: re-apply the live value the owner endpoint
        # recorded. No-op for a session nobody changed live.
        adopt_live_choices(sess)
        if not truncate:
            if stale:
                sess["messages"] = []
                sess["tool_cards"] = []
                sess["injects"] = []
            else:
                if not _owns_turn(sid):
                    # A side writer (handoff/escalation) must not rewind the turn's
                    # messages. The turn itself is the authority on its own transcript.
                    _adopt_disk_tail(sess, "messages")
                # These two are append-only by design: even the turn must not drop a
                # record another thread wrote while it was running.
                _adopt_disk_tail(sess, "injects")
                _adopt_disk_tail(sess, "tool_cards")
            # JAG-796: a mid-run steer is a REAL user message; whichever writer saves
            # first must carry it, or the operator's own words vanish from the chat.
            # It is keyed by its own id, so a steer typed AFTER the clear still lands.
            adopt_live_steers(sess)
        # JAG-431p: carry each TITLED free group's title/summary onto the message that
        # STARTS it, so the WebUI labels groups by data that rides the transcript (and
        # therefore survives compaction) instead of by an ordinal. Best-effort.
        try:
            threads_mod.sync_chapters(sess)
        except Exception:  # noqa: BLE001
            pass
        p = os.path.join(SESSIONS_DIR, sid + ".json")
        # The snapshot stamp and the stale flag are in-process bookkeeping, never
        # part of the document a reader (or another process) sees.
        write_json(p, {k: v for k, v in sess.items()
                       if k not in ("_loaded_at", "_stale_after_clear")})
    try:
        st = os.stat(p)
        with _SESSION_SUMMARY_LOCK:
            _SESSION_SUMMARY_CACHE[p] = ((st.st_mtime_ns, st.st_size), _session_summary_row(sess))
    except OSError:
        pass


def _purge_session_artifacts(sid):
    """JAG-179: delete EVERY per-session artifact, not just the transcript.

    A session owns four files, all keyed by the session id: the transcript
    (`data/sessions/<sid>.json`), its task graph (`data/graphs/<sid>.json`), its
    run metrics (`data/runs/<sid>.json`) and its edit journal
    (`data/edits/<sid>.json`). The delete button only removed the transcript, so
    graphs/runs/edits piled up as orphans (586 graph files for 76 sessions was
    exactly this leak). This also sweeps the `.bak-*` / `.reset-*` backups.
    """
    import glob
    if not _valid_sid(sid):
        return []  # JAG-230: a traversal-shaped id must never drive unlink()
    with _LIVE_LOCK:            # a deleted id must not leave live fields behind
        _LIVE.pop(sid, None)
    bases = [os.path.join(SESSIONS_DIR, sid + ".json")]
    try:
        bases.append(taskgraph._path(sid))
        # v812: a RUN keys its graph by the run id (and records the session inside),
        # so `<sid>.json` is not the only file this session owns. Without this the
        # run graphs outlived their chat: 198 of 248 graph files had no session and
        # 589 nodes lived only there.
        for _p in taskgraph.files_for_session(sid):
            if _p not in bases:
                bases.append(_p)
    except Exception:  # noqa: BLE001
        pass
    try:
        bases.append(threads_mod.path_for(sid))   # JAG-431j: the thread ledger
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model import runmetrics
        bases.append(runmetrics._path(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.tools import edits
        bases.append(edits._key_file(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.orchestrate import roles as roles_mod
        bases.append(roles_mod.path_for(sid))   # JAG-314: the per-session ROLE.md
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.memory import checkpoints
        checkpoints.purge_session(sid)          # JAG-413: drop session checkpoints
    except Exception:  # noqa: BLE001
        pass
    try:
        purge_offload(sid)                      # v973: and its offloaded observations
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model import costs
        bases.append(costs._path(sid))          # JAG-462: the per-session cost ledger
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.agent import session_jobs
        bases.append(session_jobs.path_for(sid))  # JAG-533/SJ: the Session Job ledger
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.agent import subagent as subagent_mod
        # JAG-533/SJ: the durable subagent records of this session (every SJ subjob
        # wrote one). Without this a session's children outlive the chat.
        subagent_mod.purge_parent(sid)
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.plan import goal as goal_mod
        # G-1: the durable goal record (`data/goals/<sid>.json`). Added after this
        # cascade was written, so it was the one per-session file a delete left
        # behind: the file stayed on disk AND `GET /api/goal?session=<sid>` kept
        # answering for a session that no longer existed.
        bases.append(goal_mod.path(sid))
    except Exception:  # noqa: BLE001
        pass
    removed = []
    for base in bases:
        for f in glob.glob(glob.escape(base) + "*"):
            if f.endswith(".tmp"):
                continue
            if _trash_move(f):          # JAG-455: recoverable, not unlinked
                removed.append(os.path.basename(f))
    # v973: the two per-session FOLDERS the cascade never touched. Measured
    # 2026-11-14: `data/attachments` 67 MB and `data/sandbox` 69 MB, both keyed by
    # session id and neither removed by a delete — the same leak JAG-179 closed for
    # the per-session FILES. Moved to trash (recoverable), exact path only: no glob,
    # so two sessions sharing a prefix can never take each other's folder.
    for _sub in ("attachments", "sandbox"):
        _d = os.path.join(DATA_DIR, _sub, sid)
        try:
            if os.path.isdir(_d) and _trash_move(_d):
                removed.append(os.path.join(_sub, sid))
        except Exception:  # noqa: BLE001
            pass
    _prune_trash()
    return removed


def _forget_session_runtime(sid):
    """JAG-302: drop the IN-MEMORY per-session entries on delete.

    JAG-179 purged the per-session FILES; the runtime maps keyed by session id
    (ctx-cache, turn lock, steer inbox) were never pruned, so they grew without
    bound across create/chat/delete cycles. The abort flag is only cleared when
    no turn is live — a running turn must still see it to stop.
    """
    _REAL_PROMPT_TOKENS.pop(sid, None)
    _REAL_CACHED_TOKENS.pop(sid, None)
    # 2026-11-16: a deleted/cleared session must not keep the saturation computed for
    # the transcript that no longer exists (it can be recomputed on demand).
    with _CTX_BACKFILL_LOCK:
        _CTX_BACKFILL.pop(sid, None)
        _CTX_BACKFILL_TRIED.discard(sid)
    with _steer_lock:
        STEER_INBOX.pop(sid, None)
    forget_steers(sid)   # JAG-796: the durable steer log would otherwise leak too
    # JAG-431r4: ALWAYS drop the in-memory registration. The DELETE path pushes an
    # abort FIRST (JAG-222), so a live worker still stops — but leaving _ACTIVE_CHAT
    # behind when `active` was true leaked the entry (the exact JAG-302 runtime leak
    # this function exists to prevent). The abort flag is the ONLY thing kept while
    # a turn is live.
    with _ACTIVE_CHAT_LOCK:
        active = sid in _ACTIVE_CHAT
        _ACTIVE_CHAT.pop(sid, None)
    with _TURN_LOCKS_GUARD:
        _TURN_LOCKS.pop(sid, None)
    if not active:
        clear_abort(sid)
    # JAG-431r4: also prune the agent module's per-session maps (JAG-302 missed them),
    # best-effort via a lazy import to avoid a circular import at module load.
    try:
        from longrun.agent import agent as _agent_mod
        for _m in ("_OFFLOAD_SEQ", "_REFLECT_LATEST"):
            _d = getattr(_agent_mod, _m, None)
            if isinstance(_d, dict):
                _d.pop(sid, None)
    except Exception:  # noqa: BLE001
        pass


def clear_session(sid, from_turn=False):
    """JAG-321: TRULY wipe a session's transcript — messages AND the side stores.

    The transcript the WebUI rebuilds on reload (`loadHistory`) is the merge of
    `messages` + `tool_cards` + `injects`. The `/clear` endpoint used to reset
    only `messages`, so the persisted tool cards and the harness entries
    (nudge / pivot / final / retry) came straight back — a "reset" left the chat
    visibly un-cleared. Wipe all three. Returns the session dict, or None when
    the id does not exist.

    `from_turn=True` is the session's OWN running turn asking to be cleared
    (`sessions.reset` with the caller as target, v1046): that turn is blocked
    waiting for this very call, and a batch item runs on a pool worker, so a
    blocking `_turn_lock` acquire deadlocks it (measured 2026-11-15 18:38: the
    turn never got its `tool.result`). The tombstone armed below plus the
    per-session save lock keep the write safe without the turn lock.
    """
    if not _valid_sid(sid):
        return None
    push_abort(sid)
    if from_turn:
        return _clear_now(sid)
    with _turn_lock(sid):
        return _clear_now(sid)


def _clear_now(sid):
    """The wipe itself; the caller owns the serialisation (see `clear_session`)."""
    sess = load_session(sid)
    if not sess:
        return None
    sess["messages"] = []
    sess["tool_cards"] = []
    sess["injects"] = []
    # v1045: arm the tombstone BEFORE writing, so every snapshot this process
    # already handed out (the running turn's copy) is stale from here on.
    _CLEARED_AT[sid] = time.time()
    save_session(sess, truncate=True)
    try:
        taskgraph.reset(sid)
    except Exception:  # noqa: BLE001 — a missing graph must not block the clear
        pass
    threads_mod.clear(sid)   # JAG-431j: the thread ledger describes this session
    _forget_session_runtime(sid)
    publish("session.cleared", session=sid)
    return sess


def _rel_time(ts):
    """JAG-113: short relative label ('now', '3 min', '15 h', '2 d') for a timestamp.

    English-only (repo rule): this string rides the session-list badge, so 'ora'/'g'
    (Italian) were user-visible artifact strings.
    """
    try:
        d = max(0.0, time.time() - float(ts))
    except (TypeError, ValueError):
        return ""
    if d < 60:
        return "now"
    if d < 3600:
        return "%d min" % int(d // 60)
    if d < 86400:
        return "%d h" % int(d // 3600)
    return "%d d" % int(d // 86400)


_SESSION_SUMMARY_CACHE = {}   # path -> ((mtime_ns, size), summary_dict)
_SESSION_SUMMARY_LOCK = threading.Lock()
# 2026-11-16 (operator): a session that ran BEFORE the turn started recording
# `sess["ctx"]` has no saturation. One background pass fills it from the same
# assembler the Context panel uses (`context_usage`), cached IN MEMORY only — never
# written to the session document (that would be a second truth) and never on the
# request path (the first build costs seconds: it warms the model weights).
_CTX_BACKFILL = {}            # sid -> {"pct", "tokens_used", "budget_tokens"}
_CTX_BACKFILL_TRIED = set()   # one attempt per session per process
_CTX_BACKFILL_LOCK = threading.Lock()
_CTX_BACKFILL_Q = None        # queue.Queue, created with the single worker
_CTX_BACKFILL_WORKER = None   # the thread handle, joined at interpreter exit
_CTX_BACKFILL_STOP = None     # threading.Event set by that hook


def _ctx_backfill_loop(stop):
    """ONE daemon worker: the queue keeps the cost off every request thread."""
    from longrun.core import httpapi   # lazy: memory must not import core at load
    import queue
    while not stop.is_set():
        try:
            sid = _CTX_BACKFILL_Q.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            u = httpapi.context_usage(sid)
            if u.get("available"):
                with _CTX_BACKFILL_LOCK:
                    _CTX_BACKFILL[sid] = {"pct": u.get("pct"),
                                          "tokens_used": u.get("tokens_used"),
                                          "budget_tokens": u.get("budget_tokens")}
        except Exception:  # noqa: BLE001 — a meter must never kill the worker
            pass


def _ctx_backfill_shutdown():
    """Stop and JOIN the worker before the interpreter finalises (2026-11-18).

    A daemon thread still alive at finalisation takes the process down with
    SIGSEGV (measured: v230/v321/v323/v325/v455/v595/v954, 7 of the 843 tests of
    the 15:13 full run, each passing alone). This is the same failure class the
    providers warm-up fixed for its own threads; the join runs BEFORE the .so
    files are unloaded, and `daemon=True` keeps a hung worker from blocking exit.
    """
    with _CTX_BACKFILL_LOCK:
        worker, stop = _CTX_BACKFILL_WORKER, _CTX_BACKFILL_STOP
    if stop is not None:
        stop.set()
    if worker is not None:
        try:
            worker.join(timeout=5.0)
        except Exception:  # noqa: BLE001 — shutdown must never raise
            pass


atexit.register(_ctx_backfill_shutdown)


def _ctx_backfill_request(sid):
    """Ask for one session's saturation, at most once per process."""
    global _CTX_BACKFILL_Q, _CTX_BACKFILL_WORKER, _CTX_BACKFILL_STOP
    with _CTX_BACKFILL_LOCK:
        if sid in _CTX_BACKFILL_TRIED:
            return
        _CTX_BACKFILL_TRIED.add(sid)
        if _CTX_BACKFILL_Q is None:
            import queue
            _CTX_BACKFILL_Q = queue.Queue()
            _CTX_BACKFILL_STOP = threading.Event()
            _CTX_BACKFILL_WORKER = threading.Thread(
                target=_ctx_backfill_loop, args=(_CTX_BACKFILL_STOP,),
                daemon=True, name="ctx-backfill")
            _CTX_BACKFILL_WORKER.start()
        _CTX_BACKFILL_Q.put(sid)



def _session_summary_row(s):
    if not isinstance(s, dict) or not s.get("id"):
        return None
    msgs = s.get("messages", [])
    stamps = [s.get("created") or 0]
    if msgs:
        stamps.append(msgs[-1].get("ts") or 0)
    cards = s.get("tool_cards") or []
    if cards:
        stamps.append(cards[-1].get("ts") or 0)
    upd = max(stamps)
    # 2026-11-16 (operator): "each chat context status shall be visible in the sessions
    # webui even if not the active one". The turn records what the router really sent on
    # its last request (`sess["ctx"]`), so every row carries its own saturation; None —
    # never a fabricated 0 — when the session has not run yet.
    ctx = s.get("ctx") if isinstance(s.get("ctx"), dict) else {}
    return {
        "id": s["id"],
        "title": s.get("title", ""),
        "created": s.get("created"),
        "updated": upd,
        "messages": len(msgs),
        "workspace": s.get("workspace"),
        "model": s.get("model"),
        "ctx_pct": ctx.get("pct"),
        "ctx_tokens": ctx.get("tokens_used"),
        "ctx_budget": ctx.get("budget_tokens"),
        "system": bool(s.get("system")),
        "undeletable": bool(s.get("undeletable")),
        "stateless": bool(s.get("stateless")),
        # 2026-11-16: TRI-state. True/False = the operator's explicit grant/revoke;
        # None = "no decision" — the effective value (a top org leader is granted by
        # default) is resolved once per list in `list_sessions`.
        "allow_architect": (s.get("allow_architect")
                            if isinstance(s.get("allow_architect"), bool) else None),
    }


def list_sessions():
    """JAG-113: sessions ordered by LAST USE (not creation), with an age label.

    JAG-323: each row carries a live ``running`` flag (from `_ACTIVE_CHAT`, the
    registry of turns in flight). Before, the main app's session list had NO such
    field, so a turn started HEADLESS — a job/routine turn on a session this
    browser did not open — was invisible: the session looked idle while a model
    burned GPU/tokens ("phantom run"). The flag is authoritative: every turn,
    whoever started it, registers in `_ACTIVE_CHAT` for its whole duration.
    """
    try:
        with _ACTIVE_CHAT_LOCK:
            _active = set(_ACTIVE_CHAT.keys())
    except Exception:  # noqa: BLE001
        _active = set()
    out = []
    seen_paths = set()
    try:
        for entry in sorted(os.scandir(SESSIONS_DIR), key=lambda e: e.name):
            if not entry.name.endswith(".json"):
                continue
            p = entry.path
            seen_paths.add(p)
            try:
                st = entry.stat()
                stamp = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            with _SESSION_SUMMARY_LOCK:
                cached = _SESSION_SUMMARY_CACHE.get(p)
            if cached and cached[0] == stamp:
                row = cached[1]
            else:
                s = read_json(p, None)
                # JAG-533/SJ: a JSON in this directory that is NOT a session (a
                # stray per-session ledger, a partial write, a hand-placed file)
                # must never take the endpoint down. ONE file without "id" here
                # raised KeyError and /api/sessions answered an EMPTY response,
                # so the WebUI showed "Sessions unavailable" (live, 2026-10-22).
                row = _session_summary_row(s)
                with _SESSION_SUMMARY_LOCK:
                    _SESSION_SUMMARY_CACHE[p] = (stamp, row)
            if not row:
                continue
            # A RUNNING turn's router number is fresher than the one it persisted at its
            # last end, so the rail follows the live request while the turn works.
            _live = _REAL_PROMPT_TOKENS.get(row["id"])
            if _live and row.get("ctx_budget"):
                try:
                    _lp = round(int(_live) / int(row["ctx_budget"]) * 100, 1)
                    row = {**row, "ctx_tokens": int(_live), "ctx_pct": _lp}
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            if row.get("ctx_pct") is None and row["id"] not in _active:
                # No turn has recorded this session yet: serve the background value
                # while the worker computes it (the request never waits for it).
                with _CTX_BACKFILL_LOCK:
                    _bf = _CTX_BACKFILL.get(row["id"])
                if _bf:
                    row = {**row, "ctx_pct": _bf.get("pct"),
                           "ctx_tokens": _bf.get("tokens_used"),
                           "ctx_budget": _bf.get("budget_tokens")}
                else:
                    _ctx_backfill_request(row["id"])
            upd = row["updated"]
            out.append({
                **row,
                # JAG-933: the ABSOLUTE path of the transcript this row stands for.
                # The operator hands it to another agent ("read the chat in this
                # file") or pastes it into an editor/shell, so it must be the real
                # file on this host — never a path the browser rebuilt from a
                # guessed data home. It rides the ROW, not the document: `path`
                # added to the session dict itself would be persisted by
                # `save_session` and leak into every transcript on disk.
                "path": os.path.abspath(p),
                "age": _rel_time(upd),
                "running": row["id"] in _active,
            })
        with _SESSION_SUMMARY_LOCK:
            for k in list(_SESSION_SUMMARY_CACHE):
                if k not in seen_paths:
                    _SESSION_SUMMARY_CACHE.pop(k, None)
    except FileNotFoundError:
        pass
    # 2026-11-16 (operator): Teamorg/Architect is granted by DEFAULT to a team's top
    # leader and can be revoked. The explicit bool on the record wins; only the rows
    # with no decision consult the org chart, and that is read ONCE for the list.
    try:
        from longrun.agent.architect import effective_access_map
        eff = effective_access_map(out)
        for r in out:
            if r.get("id") in eff:
                r["allow_architect"] = bool(eff[r["id"]])
    except Exception:  # noqa: BLE001 — the rail must render even if the org is unreadable
        for r in out:
            r["allow_architect"] = bool(r.get("allow_architect"))
    return sorted(out, key=lambda s: s.get("updated") or 0, reverse=True)


def ensure_agent(sess):
    """EV-30: a session IS an agent, so it is born with an `A<n>` id.

    The old contract handed a session a `J<n>` sequence from a MONOTONIC counter
    (`ensure_job` + `.jobseq`) and only *designated* it as an agent later; the rail
    then showed `J219` for a chat and `A8` for a team member. That contradicted
    both the object model ("Agent = a session, id AX") and the operator rule
    "IDs reset after resets/deletes — agent numbers, todos, jobs, every object".

    The registry owns the number now, so it retracts on delete like every other id
    (`fswrite.retract`). `kind="session"` keeps the record out of the org chart
    while leaving it in `REGISTRY.list()`, which is what the WebUI reads to badge
    the session. Returns True when the record was created.
    """
    sid = str((sess or {}).get("id") or "")
    if not sid:
        return False
    try:
        from longrun.agent import agents as agents_mod
    except Exception:  # noqa: BLE001 — a session must exist even if the registry is broken
        return False
    reg = agents_mod.REGISTRY
    if reg.get(sid):
        return False
    title = str(sess.get("title") or "").strip()[:80]
    res = reg.designate(sid, name=title or None, kind="session")
    if not res.get("ok"):
        # A title that collides with another agent's name must not block the id.
        res = reg.designate(sid, kind="session")
    return bool(res.get("ok"))


def ensure_session_workspace(sess, workspace=None):
    """JAG-117: every session is linked to a folder.

    Precedence: the explicit `workspace` argument, else the session's existing
    folder, else the global default. Returns True when it changed `sess`.
    """
    try:
        from longrun.memory import rules as rules_mod
        want = rules_mod.check_dir(workspace) or sess.get("workspace") or rules_mod.get_workspace()
    except Exception:  # noqa: BLE001 — never break session loading
        want = workspace or sess.get("workspace") or REPO
    if want and sess.get("workspace") != want:
        sess["workspace"] = want
        return True
    return False


def backfill_session_workspaces():
    """JAG-117: pin a folder on any stored session that has none yet."""
    n = 0
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            s = read_json(os.path.join(SESSIONS_DIR, fn), None)
            if s and ensure_session_workspace(s):
                save_session(s)
                n += 1
    except FileNotFoundError:
        pass
    return n


def backfill_agents():
    """EV-30: give every stored session its `A<n>`, in creation order.

    One-shot migration for sessions created under the old `J<n>` contract. Also
    retires the monotonic counter file: nothing reads it any more, and leaving it
    behind would keep a number the registry can now reuse.
    """
    n = 0
    try:
        names = [f for f in sorted(os.listdir(SESSIONS_DIR)) if f.endswith(".json")]
    except FileNotFoundError:
        return 0
    rows = [s for s in (read_json(os.path.join(SESSIONS_DIR, f), None) for f in names) if s]

    def _age(x):
        try:
            return float(x.get("created") or 0)
        except (TypeError, ValueError):
            return 0.0

    for s in sorted(rows, key=_age):
        if ensure_agent(s):
            n += 1
        if "job" in s:
            # EV-30: the old J<n> is not migrated as a second label — the agent id
            # is the session's identity now, and a stale `job` would be a second truth.
            s.pop("job", None)
            save_session(s)
    try:
        if os.path.isfile(_JOBSEQ_FILE):
            os.remove(_JOBSEQ_FILE)   # EV-30: the monotonic session counter is gone
    except OSError:
        pass
    return n


def _set_session_model(sid, model):
    """JAG-309: the single writer for a session's model AND its agent's model.

    An agent IS a session (agents.py: agent["session"] == sid), yet two
    independent writers let the two diverge: Orbit set only `agent["model"]`
    (which jobs read) while the composer set only `session["model"]` (which
    interactive chat reads). A3 showed a local model in Orbit but
    `deepseek-reasoner` in the composer. Unify them here: one model per entity,
    served by BOTH surfaces. `""` clears the choice; `None` leaves it untouched
    is NOT the contract here — this is an explicit write, so `""` clears.
    """
    sid = str(sid or "").strip()
    if not sid:
        return None
    ref = str(model or "")[:120]
    sess = load_session(sid)
    _prev = (sess or {}).get("model") if sess is not None else None
    if sess is not None:
        sess["model"] = ref
    live_fields_changed(sid, model=ref)
    if sess is not None:
        save_session(sess)
    try:
        from longrun.agent import agents as agents_mod
        if agents_mod.REGISTRY.is_agent(sid):
            agents_mod.REGISTRY.designate(sid, model=ref)
    except Exception:  # noqa: BLE001 — the agent layer is optional for a session
        pass
    # JAG-532: this is the single writer for the session model, so it is also the
    # single place that must TELL the UI — a model set by Orbit, the composer or the
    # CLI used to leave the other surface showing the previous one until F5. Only a
    # REAL change is announced, so the startup reconcile stays silent.
    # …and the single place that must DEFEND the choice against a longer-lived turn
    # that would write its stale copy over it (live fields already carry the new
    # value, set above before save_session so adopt_live_choices keeps it).
    if str(_prev or "") != ref:
        publish("session.updated", session=sid, model=ref)
    return ref


# Fields an OPERATOR can change from the WebUI WHILE a turn is running, and the
# value its OWN endpoint last wrote in this process. A turn loads the session at its
# START and writes the WHOLE dict at its end (and again on every tool card), so a
# stale in-memory copy reverted a live choice — live 2026-11-02: the model picked
# mid-run came back as the previous one because the tool-card write of the running
# turn won. `_LIVE` is the tombstone-style defence (see `_DELETED_SESSIONS`): the
# owners record the value here, and `save_session` re-applies it, so no writer can
# resurrect an older one. Process-local, dropped on restart.
LIVE_OPERATOR_FIELDS = ("model", "workspace")
# The DOCUMENT state has the same race as the operator fields: the `docs` tool can
# write `plan`/`plan_mode` from INSIDE a running turn, whose final save would
# otherwise drop the record (or an old copy would resurrect a cleared one). The
# owners (`propose_plan`, `approve_plan`, `reject_plan`, `set_plan_mode` and
# `plan.docs.unlock`) record the FINAL value here before their own save, so every
# later writer re-applies it — the same defence model/workspace already use.
LIVE_DOC_FIELDS = ("plan", "plan_mode")
_LIVE_FIELDS = LIVE_OPERATOR_FIELDS + LIVE_DOC_FIELDS

_LIVE = {}                  # sid -> {field: value}
_LIVE_LOCK = threading.Lock()


def live_fields_changed(sid, **fields):
    """Record the value an OWNER endpoint just wrote for a live field."""
    if not _valid_sid(sid):
        return
    with _LIVE_LOCK:
        slot = _LIVE.setdefault(sid, {})
        for k, v in fields.items():
            if k in _LIVE_FIELDS:
                slot[k] = v


def adopt_live_choices(sess):
    """Re-apply the operator's live choices to `sess` before it is written.

    Never raises and never invents a field: a session with no live change is
    returned untouched.
    """
    sid = (sess or {}).get("id")
    if not _valid_sid(sid):
        return sess
    with _LIVE_LOCK:
        live = dict(_LIVE.get(sid) or {})
    for k, v in live.items():
        sess[k] = v
    return sess


def adopt_live_steers(sess):
    """Fold any mid-run steer into `sess` before it is written (JAG-796).

    A steer typed while a turn was running lived ONLY in the in-memory inbox and
    in that turn's own context, so it reached the transcript — marked `internal`,
    which the WebUI never renders — only when the turn ended. A turn blocked
    inside a dispatch (or interrupted) meant the operator's own message was
    invisible in the chat and gone on a reload.

    Same contract as `adopt_live_choices`: the recorded steers are re-applied on
    EVERY write, keyed by their own id, so whichever writer saves first carries
    them as REAL user messages and a stale in-memory copy of the session cannot
    drop them afterwards.
    """
    sid = (sess or {}).get("id")
    if not _valid_sid(sid):
        return sess
    recs = live_steers(sid)
    if not recs:
        return sess
    have = {str(m.get("steer_id") or "") for m in (sess.get("messages") or [])
            if isinstance(m, dict) and m.get("steer")}
    for it in recs:
        text = str(it.get("text") or "").strip()
        if not text or str(it.get("id") or "") in have:
            continue
        try:
            threads_mod.record(sess, node=None, role="user", text=text,
                               idx=len(sess.get("messages", [])))
        except Exception:  # noqa: BLE001 — a ledger hiccup must never block the write
            pass
        sess.setdefault("messages", []).append(
            {"role": "user", "content": text,
             "ts": it.get("ts") or round(time.time(), 3),
             "steer": True, "steer_id": it.get("id")})
        have.add(str(it.get("id")))
    return sess


def reconcile_agent_models():
    """JAG-309: make every agent's model agree with its session's (agent wins).

    The agent model is the explicit per-agent choice made in Orbit and is what
    its jobs actually ran on, so it is authoritative; the session model is
    back-filled from it. When only the session has one, the agent inherits it.
    Idempotent; runs once at startup so pre-JAG-309 divergence heals.
    """
    try:
        from longrun.agent import agents as agents_mod
        rows = agents_mod.REGISTRY.list().get("agents", [])
    except Exception:  # noqa: BLE001 — agents are optional
        return 0
    fixed = 0
    for a in rows:
        sid = a.get("session")
        if not sid:
            continue
        sess = load_session(sid)
        if sess is None:
            continue
        am = a.get("model") or ""
        sm = sess.get("model") or ""
        if am == sm:
            continue
        if am:
            sess["model"] = str(am)[:120]
            save_session(sess)
            fixed += 1
        else:
            try:
                agents_mod.REGISTRY.designate(sid, model=sm)
                fixed += 1
            except Exception:  # noqa: BLE001
                pass
    return fixed


def _remember_workspace(path):
    """JAG-126: remember the folder of the session being used, so the NEXT new
    session defaults to it. Never breaks the session if the write fails."""
    try:
        from longrun.memory import rules as rules_mod
        rules_mod.remember_workspace(path)
    except Exception:  # noqa: BLE001
        pass


def _chat_workspace(sess):
    """JAG-127: the folder of the chatting session, for the tool approval gate
    (a file op outside it must be confirmed). Never raises."""
    try:
        from longrun.memory import rules as rules_mod
        return rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        return None


def set_session_trust(sid, trust):
    """Persist a session trust profile (`locked`/`standard`/`open`).

    Validated through `sandbox.trust_profile` (unknown names raise, JAG-2.7);
    the rejection leaves the old trust untouched. Returns True on success.
    """
    from longrun.tools import sandbox as _sb
    _sb.trust_profile(trust)  # raises ValueError on unknown names
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    s["trust"] = str(trust).strip().lower()
    save_session(s)
    return True


def set_plan_mode(sid, on):
    """Lock/unlock a session into Cline-style plan mode.

    While `plan_mode` is on (and no plan was approved), `registry.classify`
    denies mutating tools — the agent may only explore until the operator
    approves the proposed plan. Returns True on success.
    """
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    s["plan_mode"] = bool(on)
    live_fields_changed(sid, plan_mode=bool(on))
    save_session(s)
    return True


def propose_plan(sid, steps, doc=None, lock=False, origin=None, intent=None):
    """Record the agent's proposed plan for a session (status `proposed`).

    v1051: `doc` optionally carries the plan/spec document metadata
    (`{kind, title, path, documents, ...}`) on the SAME `plan` object — one state
    machine, one writer. `lock=True` sets `plan_mode` in the SAME write, so a
    document and its gate can never land separately. Empty step lists raise (a
    plan with no steps approves nothing). Returns True on success.

    2026-11-17: `origin` (`composer|tool|cli|auto`) and `intent`
    (`document|implement`) are recorded on the plan so the SECOND decision —
    "may the agent implement it?" — never has to be guessed from prose. A fresh
    proposal is never implemented: `implement` starts False.
    """
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    clean = [str(x).strip() for x in (steps or []) if str(x).strip()]
    if not clean:
        raise ValueError("propose_plan: steps must be a non-empty list of strings")
    plan = {"steps": clean, "status": "proposed", "implement": False}
    if isinstance(doc, dict):
        plan["doc"] = dict(doc)
    if origin:
        plan["origin"] = str(origin)
    if intent:
        plan["intent"] = str(intent)
    s["plan"] = plan
    if lock:
        s["plan_mode"] = True
    live_fields_changed(sid, plan=plan, **({"plan_mode": True} if lock else {}))
    save_session(s)
    return True


def approve_plan(sid, implement=False, by="operator"):
    """Approve the pending plan's CONTENT; optionally authorise implementation.

    2026-11-17 (operator: "one can be approved to do spec but not authorized to
    auto approve and implement them"): approving the document and opening the
    write gate are two decisions. `implement=False` records `approved` and
    LEAVES the session locked (the gate is released by `grant_implement` or by
    the auto-policy path); `implement=True` also releases the gate in the same
    write. Requires a `proposed` plan — an approval always refers to a concrete
    proposal. Returns True on success.
    """
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    plan = s.get("plan") or {}
    if plan.get("status") != "proposed":
        raise ValueError("approve_plan: no proposed plan for session %r" % (sid,))
    plan["status"] = "approved"
    plan["decided_by"] = plan.get("decided_by") or by
    plan["decided_ts"] = time.time()
    if isinstance(plan.get("doc"), dict):
        plan["doc"] = dict(plan["doc"], status="approved")
    if implement:
        plan["implement"] = True
        s["plan_mode"] = False
    s["plan"] = plan
    live_fields_changed(sid, plan=plan, **({"plan_mode": False} if implement else {}))
    save_session(s)
    return True


def grant_implement(sid):
    """Authorise the implementation of an ALREADY approved document.

    The second decision: `plan["implement"]=True` and the gate opens. Refuses
    unless the content was approved first, so "authorise to implement" can never
    stand in for "approve the plan". Idempotent. Returns True on success.
    """
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    plan = s.get("plan") or {}
    if plan.get("status") != "approved":
        raise ValueError("grant_implement: the document is not approved yet")
    plan["implement"] = True
    plan.setdefault("implemented_ts", round(time.time(), 3))
    s["plan"] = plan
    s["plan_mode"] = False
    live_fields_changed(sid, plan=plan, plan_mode=False)
    save_session(s)
    return True


def reject_plan(sid):
    """Reject the document: a `proposed` one OR an approved one never implemented.

    2026-11-17 (operator): *"rejecting spec or plan into the approvals RH panel
    doesn't make the approval entity to disappear"*. The inbox shows a second row
    once the CONTENT is approved (it awaits ▶), and `reject` accepted only
    `proposed`: the click answered 400 ("no proposed plan") and the row stayed in
    the panel for ever, with an approve button that was disabled too — the entity
    had no exit. Withdrawing an approved plan whose implementation was NEVER
    authorised is still the operator's decision; once it IS authorised the
    document is in force and there is nothing left to reject.

    The lock is untouched here (the caller — `docs.reject` — unlocks); v597 A10
    pins that. Returns True on success.
    """
    s = load_session(sid)
    if not s:
        raise ValueError("unknown session %r" % (sid,))
    plan = s.get("plan") or {}
    if plan.get("status") not in ("proposed", "approved"):
        raise ValueError("reject_plan: no plan to reject for session %r" % (sid,))
    if plan.get("status") == "approved" and plan.get("implement"):
        raise ValueError("reject_plan: the implementation is already authorised "
                         "for session %r — nothing left to reject" % (sid,))
    plan["status"] = "rejected"
    plan["implement"] = False
    plan["decided_by"] = plan.get("decided_by") or "operator"
    plan["decided_ts"] = time.time()
    if isinstance(plan.get("doc"), dict):
        plan["doc"] = dict(plan["doc"], status="rejected")
    s["plan"] = plan
    live_fields_changed(sid, plan=plan)
    save_session(s)
    return True


def get_or_create_session(sid, title=None, workspace=None, trust=None):
    if sid and not _valid_sid(sid):
        sid = None  # JAG-230: refuse a traversal-shaped id, allocate a safe one
    if sid:
        with _deleted_lock:
            _gone = sid in _DELETED_SESSIONS
        if _gone:
            # JAG-315: a deleted session must never come back. A caller that still
            # holds the old id (a chat / attach from a stale tab) gets a FRESH one
            # rather than silently resurrecting the deleted transcript.
            sid = None
        else:
            s = load_session(sid)
            if s:
                changed = ensure_session_workspace(s, workspace)
                ensure_agent(s)   # EV-30: registry write — not a session-file change
                if changed:
                    save_session(s)
                _remember_workspace(s.get("workspace"))
                return s
    sid = sid or uuid.uuid4().hex[:12]
    s = {"id": sid, "title": title or "session " + sid[:6],
         "created": round(time.time(), 3), "messages": []}
    if trust is not None:
        from longrun.tools import sandbox as _sb
        _sb.trust_profile(trust)  # raises ValueError on unknown names
        s["trust"] = str(trust).strip().lower()
    ensure_session_workspace(s, workspace)
    save_session(s)
    ensure_agent(s)                              # EV-30: allocate A<n> on creation
    _remember_workspace(s.get("workspace"))
    return s


def _card_rows(sess):
    return [c for c in ((sess or {}).get("tool_cards") or []) if isinstance(c, dict)]


def _card_index(cards, handle):
    """The position of the card named by a manifest handle, or None."""
    h = str(handle or "").strip().lstrip("#")
    if not h:
        return None
    from longrun.model.context_engine import card_handle
    for i, c in enumerate(cards):
        if str(c.get("id") or "") == h:
            return i
    for i, c in enumerate(cards):
        if card_handle(c) == h:
            return i
    return None


def card_by_handle(sess, handle):
    """The tool card named by a manifest handle, or None.

    Accepts what `context_engine.card_handle` prints — a card `id`, or `t<ms>`
    for a card persisted before ids existed — with or without the leading `#`.
    One resolver for the CLI, the HTTP filter and the `sessions` tool.
    """
    cards = _card_rows(sess)
    i = _card_index(cards, handle)
    return None if i is None else cards[i]


def card_index_by_handle(sess, handle):
    """The POSITION of the tool card named by a manifest handle, or None.

    A caller that must point at the card (e.g. `harness.backtrace.explain`)
    uses this instead of `is`-comparing the object `card_by_handle` returns.
    The position indexes the session's dict cards — the same filtered list
    `explain` indexes — so it cannot drift if the resolver ever hands back a
    copy or a normalised dict.
    """
    return _card_index(_card_rows(sess), handle)


def replay_record(cards, workspace="", upto_ts=None):
    """What a fork can and cannot replay of the prefix it inherited.

    S1 (arXiv:2611.11216) measures the same gap on an agent benchmark: the
    declared settings reconstruct 42/71 executions, an RNG reset lifts that to
    68/71, and hidden state still diverges in 4. Longrun owns neither a model
    seed nor a frozen workspace, so a fork must SAY which class of replay it is
    instead of implying one. Pure over the cards the fork already copies; the
    git read fails open to None and never breaks a fork.

    Classes: `transcript-only` (the prefix changed nothing outside the
    transcript — a re-run is as faithful as the model allows),
    `effects-not-restored` (a definite writer ran: the fork starts from the
    current tree, not from the tree of that moment), `unverified-effects` (only
    tools that MAY write ran; their card cannot say).
    """
    rows = []
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        if upto_ts is not None:
            try:
                if float(c.get("ts") or 0) > upto_ts:
                    continue
            except (TypeError, ValueError):
                continue
        rows.append(c)
    counts = {}
    for c in rows:
        tool = str(c.get("tool") or "")
        counts[tool] = counts.get(tool, 0) + 1
    writes = sum(n for t, n in counts.items() if t in _EFFECT_TOOLS)
    possible = sum(n for t, n in counts.items() if t in _MAYBE_EFFECT_TOOLS)
    if writes:
        fidelity = "effects-not-restored"
    elif possible:
        fidelity = "unverified-effects"
    else:
        fidelity = "transcript-only"
    ws = str(workspace or "")
    return {"fidelity": fidelity, "cards": len(rows),
            "writes": writes, "possible": possible,
            "write_tools": {t: counts[t] for t in sorted(counts)
                            if t in _EFFECT_TOOLS or t in _MAYBE_EFFECT_TOOLS},
            "workspace": ws,
            "head": (git_revision(ws, refresh=True) if ws else None),
            "dirty": (git_dirty(ws) if ws else None)}


def fork_session(sid, at=None, title=None, model=None, workspace=None):
    """Branch a session at message `at` into a NEW session (DeepSeek resume/fork).

    The source transcript is the PREFIX `messages[:at]` (0-based, exclusive);
    `at=None` copies the whole transcript. The source is never mutated: the fork
    gets its own id, its own agent number, `forked_from`/`fork_at`/`fork_ts`
    provenance, and the tool cards that precede the cutoff (a card after the cut
    belongs to work the fork did not inherit). `workspace`/`model` default to the
    source and can be overridden, which is what makes a fork an A/B arm: the same
    prefix, a different model.

    `replay` (round 9) is the fork's own fidelity record: `transcript-only`,
    `effects-not-restored` or `unverified-effects`, plus the workspace HEAD and
    dirty count — a fork copies words, never state, and must not imply otherwise.

    Returns {"ok": True, "session": <new>, "source", "fork_at", "messages"} or
    {"ok": False, "error"} — an out-of-range `at` is refused, never clamped.
    """
    src = load_session(sid)
    if not src:
        return {"ok": False, "error": "session not found"}
    msgs = list(src.get("messages") or [])
    if at is None:
        n = len(msgs)
    else:
        if isinstance(at, bool):
            return {"ok": False, "error": "at must be an integer"}
        try:
            n = int(at)
        except (TypeError, ValueError):
            return {"ok": False, "error": "at must be an integer"}
        if n < 0 or n > len(msgs):
            return {"ok": False,
                    "error": "at out of range (0..%d)" % len(msgs)}
    try:
        prefix = json.loads(json.dumps(msgs[:n]))
        cutoff = float(msgs[n - 1].get("ts") or 0) if n else float("-inf")
        cards = [c for c in (src.get("tool_cards") or [])
                 if n >= len(msgs) or float(c.get("ts") or 0) <= cutoff]
        cards = json.loads(json.dumps(cards))
    except (TypeError, ValueError):
        return {"ok": False, "error": "session transcript is not JSON-safe"}
    new_id = uuid.uuid4().hex[:12]
    new = {"id": new_id,
           "title": str(title or ((src.get("title") or "session") + " (fork)"))[:120],
           "created": round(time.time(), 3), "messages": prefix,
           "workspace": str(workspace or src.get("workspace") or ""),
           "forked_from": sid, "fork_at": n, "fork_ts": round(time.time(), 3)}
    if model or src.get("model"):
        new["model"] = str(model or src.get("model"))
    if src.get("trust"):
        new["trust"] = src.get("trust")
    if cards:
        new["tool_cards"] = cards
    new["replay"] = replay_record(cards, new.get("workspace") or "")
    save_session(new)
    ensure_agent(new)                       # a fork IS a new agent (its own A<n>)
    _remember_workspace(new.get("workspace"))
    return {"ok": True, "session": new, "source": sid, "fork_at": n,
            "messages": len(prefix)}


def append_message(sess, role, content, reasoning=None, meta=None):
    # JAG-238: the transcript must only ever hold STRING content. A client could
    # POST {"message": 123}; the int was persisted and later crashed /api/context
    # (`len(int)` -> dropped connection). Coerce at this single choke point so no
    # caller can poison the stored transcript.
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    msg = {"role": role, "content": content, "ts": round(time.time(), 3)}
    if reasoning:
        msg["reasoning"] = reasoning
    if meta:
        msg.update(meta)
    # JAG-431j: file this turn into the session's durable thread ledger BEFORE the
    # transcript write — compaction rewrites `messages` (older turns -> one summary),
    # so the ledger must capture the content while it is still guaranteed present.
    threads_mod.record(sess, node=msg.get("node"), role=role, text=content,
                       idx=len(sess.get("messages", [])))
    sess["messages"].append(msg)
    save_session(sess)
    return msg


def persist_tool_card(sess, tool, ok, args=None, result="", error="",
                      exit_code=None, backend=None, node=None, think=None, after=None,
                      data=None):
    """JAG-96: persist an inline tool card so cold-start UIs can rebuild it.

    Stored in `sess["tool_cards"]` — NOT in `messages` — so it never reaches the
    model prompt (`context_engine.build` only reads `messages`). `after` is the
    number of already-persisted messages the card follows, letting the WebUI and
    the mobile mirror interleave cards with the transcript on history reload.
    `node` (JAG-167) is the todo node id the card belongs to, so the in-chat tree
    can nest it under the right node on reload.

    JAG-192: `after` MUST be passed explicitly from the chat loop. During a turn
    the transcript lives in the local `msgs` list and is flushed into
    `sess["messages"]` only at the end, so `len(sess["messages"])` is frozen at
    the turn-start value — every card of a multi-step turn then collapsed onto
    the same boundary and a reload stacked the whole turn at the top instead of
    interleaving it (that is the "Ctrl+Shift+R reshuffles the chat" bug).
    `node` is coerced to its id so a caller that accidentally passes the node
    dict cannot poison the JSON with "[object Object]".
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        args_str = args if isinstance(args, str) else json.dumps(args or {},
                                                                ensure_ascii=False)
        card = {
            "id": uuid.uuid4().hex[:8],
            "tool": str(tool),
            "ok": bool(ok),
            "args": args_str[:4000],
            "result": str(result or "")[:4000],
            "error": str(error or "")[:2000],
            "exit_code": exit_code,
            "backend": backend,
            "node": node,
            "think": (str(think)[:6000] if think else None),
            "after": (len(sess.get("messages", [])) if after is None else int(after)),
            "ts": round(time.time(), 3),
        }
        # 2026-11-16: structured tool payload (web hits, engine, ids) for the UI.
        # It lives INSIDE the card, never in `messages`, so it cannot reach the
        # model prompt. Capped: `publish` stores every event payload verbatim in
        # events.db and `save_session` rewrites the whole session JSON per card.
        if isinstance(data, dict) and data:
            try:
                if len(json.dumps(data, ensure_ascii=False)) <= 6000:
                    card["data"] = data
            except Exception:  # noqa: BLE001 — an unserialisable payload is dropped
                pass
        # JAG-431j: file the tool call into the thread ledger (digest) before it is
        # stored — the ledger must not depend on the (compactable) transcript.
        threads_mod.record(sess, node=node, text="\u2699 %s %s" % (tool, args_str),
                           idx=card["after"])
        sess.setdefault("tool_cards", []).append(card)
        save_session(sess)
        return card
    except Exception:  # noqa: BLE001 — persisting a card must never break a turn
        return None


def persist_inject(sess, kind, text, node=None, after=None):
    """JAG-167: persist a harness→LLM injection so the chat can rebuild it on reload.

    Mirrors `persist_tool_card`: stored in `sess["injects"]` (never re-sent as its
    own message), with `after` (message boundary) + `node` (the todo node it
    belongs to) + `ts`, so `loadHistory` re-nests it under the right node. JAG-192:
    `after` is passed explicitly by the chat loop (see persist_tool_card) and
    `node` is coerced to its id.

    2026-11-05 (operator: "what i see in UI in the chat under harness label shall
    be EXACTLY what the LLM receives not else"): NO dedup here. Every record is
    one message the model actually received, so a second identical send must be
    recorded a second time — dropping it made the reloaded chat disagree with the
    wire. `text` is the WRAPPED content (`[harness] …`), i.e. the exact bytes.
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        # v947: the `after` boundary must count the messages that are really on
        # disk NOW. This dict may predate a turn that saved in between (a handoff
        # is written from another thread), so adopt the unseen tail first.
        if after is None:
            _adopt_disk_tail(sess, "messages")
        rec = {"kind": str(kind or "inject"), "text": str(text or ""),
               "node": node,
               "after": (len(sess.get("messages", [])) if after is None else int(after)),
               "ts": round(time.time(), 3)}
        threads_mod.record(sess, node=node, text=text, idx=rec["after"])
        sess.setdefault("injects", []).append(rec)
        save_session(sess)
        return rec
    except Exception:  # noqa: BLE001 — persisting an inject must never break a turn
        return None


def drop_inject(sess, text):
    """Withdraw the LAST inject record whose text is `text` (2026-11-05).

    Used by the mid-turn trim: the harness dropped that message before the next
    model call, so the model never received it and the chip must not survive in
    the rebuilt chat. Returns the removed record, or None.
    """
    try:
        recs = sess.get("injects") or []
        for i in range(len(recs) - 1, -1, -1):
            if str(recs[i].get("text") or "") == str(text or ""):
                gone = recs.pop(i)
                save_session(sess)
                return gone
    except Exception:  # noqa: BLE001
        return None
    return None


# JAG-113: the live tool card must show input + output (truncated), like the
# persisted one rebuilt on reload — the live SSE event used to carry neither.
TOOL_EVENT_MAX = ctx_limits.limit("tool_event_max")


def _trunc(text, n=None):
    """Truncate to <= n chars INCLUDING the '… trunc.' suffix (JAG-113)."""
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    n = n or TOOL_EVENT_MAX
    if len(s) <= n:
        return s
    keep = max(0, n - 48)
    return s[:keep] + "\n… [%d chars truncated]" % (len(s) - keep)


def _tool_event(tool, ok, args=None, output="", **extra):
    """Payload for a live tool card (args + truncated output + meta)."""
    args_s = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    ev = {"tool": str(tool), "ok": bool(ok), "args": _trunc(args_s),
          "output": _trunc(output or "")}
    ev.update(extra)
    return ev


# JAG-371: the API-key management (ENV_FILE, KNOWN_ENV_KEYS, _env_file_upsert,
# set_key, reveal_key, keys_status) moved to `keys.py` (imported above).


# --- JAG-51 session contract: no request without a persisted answer ---------
ERROR_PREFIX = "⚠️ error: "


def session_mark(sess):
    """Index (len of `messages`) to pass to `ensure_reply_persisted` as `since`.

    Call it *before* appending the request's `user` message: it captures the
    boundary of the request so the helper can tell whether that request
    produced an assistant turn.
    """
    return len(sess.get("messages", []))


def has_reply_since(sess, since):
    """True iff an `assistant` message was persisted at index >= `since`."""
    return any(m.get("role") == "assistant" for m in sess.get("messages", [])[since:])


#: The keys an explicit `{"action":"finish", ...}` carries its verdict in. The
#: canonical one is `summary`; the rest are the weak-model synonyms the turn loop
#: accepts (`agent._is_explicit_finish`), so both readers agree on ONE list.
FINISH_SUMMARY_KEYS = ("summary", "text", "content", "answer", "message", "result")


def finish_summary(content):
    """The verdict of an explicit finish envelope in `content`, or "".

    D5: the loop may run closure-gate rounds AFTER a finish was emitted, so the
    LAST assistant message of a turn is not always the reply (measured live:
    A52's dispatch returned an unrelated code snippet that followed the finish).
    A finish envelope is the model's declared end of the turn.
    """
    from longrun.util.textkit import extract_action_json
    act = extract_action_json(str(content or ""))
    if not isinstance(act, dict):
        return ""
    if str(act.get("action") or "").strip().lower() != "finish":
        return ""
    for k in FINISH_SUMMARY_KEYS:
        v = act.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _starts_work(content):
    """True when an assistant message is an ACTION (the turn kept working).

    2026-11-08: `extract_action_json` finds an action-shaped object ANYWHERE in
    the text, by design (the loop must act on `prose + {"tool": ...}`). For reply
    SELECTION that is too eager: a dense answer that EXPLAINS "the command was
    {…} — here is the result" was discarded as if the turn had resumed. The
    envelope must be the bulk of the message (>= half of it, whitespace ignored);
    a quoted example inside a long answer is prose.

    2026-11-08 (measured on job J30): a model that answers with its NATIVE
    tool-call markup (`<｜｜DSML｜｜ invoke name="fs.write">`) was counted as prose.
    The longest such message won `turn_reply`, so a job's `assignment` and
    `runs[*].result` were 2.8 KB of raw markup instead of the plan — every worker
    was handed the envelope as its brief. Markup is a CALL the loop already
    parsed and executed, never an answer.
    """
    import re as _re
    text = str(content or "").strip()
    if not text:
        return False
    from longrun.util.textkit import extract_action_json, is_tool_markup
    if is_tool_markup(text):
        return True
    act = extract_action_json(text)
    if not isinstance(act, dict) or not (act.get("action") or act.get("tool")):
        return False
    try:
        envelope = json.dumps(act, ensure_ascii=False, sort_keys=True)
    except Exception:  # noqa: BLE001 — a non-serializable object is not an envelope
        return False
    compact = len(_re.sub(r"\s+", "", envelope))
    body = len(_re.sub(r"\s+", "", text))
    return bool(compact) and compact * 2 >= body


def turn_reply(messages, longest=False):
    """The prose reply of a TURN (`messages` already sliced to that turn).

    `longest=False` returns the LAST non-empty assistant message — the normal
    "what did the model say" read. `longest=True` returns the MOST substantial
    one (JAG-303): a turn can end with a short harness-prompted summary
    ("report the RESULT you already have") AFTER the real deliverable, so the
    last message is not always the work. `reasoning` is a separate field, so it
    never wins by accident. Empty string when the turn produced no reply.

    D5: when the turn closed on an explicit finish, the FINISH summary is the
    reply — a closure-gate round after it must not mask the result, so messages
    after the finish are dropped and the envelope itself counts as its summary.
    An ACTION after the finish means the turn kept working (e.g. goal-mode
    recovery), so that finish is no longer the end and the normal selection
    applies. `longest=True` still prefers a longer deliverable written before
    the finish.
    """
    msgs = [m for m in (messages or [])
            if isinstance(m, dict) and m.get("role") == "assistant"]
    finish_i, fin = -1, ""
    for i, m in enumerate(msgs):
        f = finish_summary(m.get("content"))
        if f:
            finish_i, fin = i, f
    declared = fin
    if finish_i >= 0 and any(_starts_work(m.get("content"))
                             for m in msgs[finish_i + 1:]):
        finish_i, fin = -1, ""
    if finish_i >= 0:
        contents = [str(m.get("content") or "").strip() for m in msgs[:finish_i]
                    if not _starts_work(m.get("content"))] + [fin]
    else:
        # 2026-11-08: the round after a finish can itself be an ACTION
        # (`todo.update` bookkeeping, a `fs.read` the closure gate asked for) —
        # that envelope is not a reply, and returning it made the banner revert
        # to raw JSON. Select PROSE only; when the turn produced none, the
        # declared finish is still the best answer it gave.
        contents = [str(m.get("content") or "").strip() for m in msgs
                    if not _starts_work(m.get("content"))]
    contents = [c for c in contents if c]
    if not contents:
        if declared:
            return declared
        # no prose and no declared summary: show SOMETHING rather than nothing
        # (v303 pins this for a bare `{"action":"finish"}`) — but native tool-call
        # markup is never that something: the loop already executed it, so the
        # turn has no answer and "" says so.
        from longrun.util.textkit import is_tool_markup
        raw = [str(m.get("content") or "").strip() for m in msgs]
        raw = [c for c in raw if c and not is_tool_markup(c)]
        return (raw or [""])[-1]
    return max(contents, key=len) if longest else contents[-1]


def ensure_reply_persisted(sess, since, error=None, model=None):
    """JAG-51 invariant: a request never leaves an orphan `user` message.

    Every request on a session must end with an `assistant` message — the model
    reply, an explicit error turn, or both (reply + graph error are separate).
    If nothing assistant-shaped was persisted since `since`, append the explicit
    error record and return it; otherwise return None. Idempotent: calling it
    twice (e.g. from `except` and `finally`) never doubles a message.
    """
    if has_reply_since(sess, since):
        return None
    detail = str(error) if error else "empty reply from the model"
    return append_message(sess, "assistant", ERROR_PREFIX + detail,
                          meta={"model": model, "error": True, "error_detail": detail})


def classify_interruption(sess, checkpoint=None):
    """M10 slice (DeepSeek resume/fork/replay): was the killed turn replay-safe?

    A hard restart kills the in-flight turn; its transcript was never flushed,
    but its tool cards WERE persisted per call (`persist_tool_card`, each with
    `after` = the persisted message count at card time). Cards with
    `after >= len(messages)` belong to the killed turn — earlier turns' cards
    sit below the frozen boundary. Zero such cards means the model died before
    executing anything, so replaying from the PRE-turn checkpoint is safe;
    any executed card means effects are unknown and only the user can continue.
    Returns None when the transcript does not end on a user turn (no orphan).
    """
    msgs = (sess or {}).get("messages") or []
    if not msgs or msgs[-1].get("role") != "user":
        return None
    n = len(msgs)
    executed = sum(1 for c in ((sess or {}).get("tool_cards") or [])
                   if isinstance(c, dict)
                   and (c.get("after") if isinstance(c.get("after"), int)
                        else 0) >= n)
    if executed == 0 and checkpoint:
        return {"effect": "interrupted_before_effect", "executed": 0,
                "checkpoint": checkpoint}
    return {"effect": "unknown_effect", "executed": executed,
            "checkpoint": checkpoint}


def reconcile_orphan_turns(session=None):
    """JAG-262: close turns left half-done by a hard restart.

    A systemd restart (SIGTERM) kills an in-flight chat turn; its `finally` never
    runs, so the session keeps a trailing `user` message with no reply and the
    WebUI shows it as if it were still working ("stuck"). At startup nothing can
    be in flight, so any session ending on a `user` turn is an orphan: close it
    with an explicit assistant notice (never silently dropped). Returns the count.

    `session` (JAG-263): restrict the sweep to one session id, so the agent can
    repair a single stuck session on demand via the `reconcile` tool.
    """
    fixed = 0
    if session:
        names = ([session + ".json"]
                 if os.path.exists(os.path.join(SESSIONS_DIR, session + ".json"))
                 else [])
    else:
        try:
            names = os.listdir(SESSIONS_DIR)
        except FileNotFoundError:
            return 0
    for fn in names:
        if not fn.endswith(".json"):
            continue
        sid = fn[:-5]
        # JAG-262b: a session with a LIVE turn has a trailing `user` message too
        # (the reply is persisted only at the end), so a blind sweep would corrupt
        # a working session. NEVER touch a session that currently owns a turn.
        if sid in _ACTIVE_CHAT:
            continue
        try:
            sess = load_session(sid)
        except Exception:  # noqa: BLE001
            continue
        msgs = (sess or {}).get("messages", [])
        if not msgs or msgs[-1].get("role") != "user":
            continue
        # M10 slice: look up the PRE-turn checkpoint (JAG-426 anchors it to the
        # trailing user message) and classify the kill. Local import: checkpoints
        # must never pull stores at module load.
        try:
            from longrun.memory import checkpoints as _cps
            _cp = _cps.get_by_idempotency_key(
                "turn:%s:%s" % (sid, len(msgs) - 1))
            _cpid = (_cp or {}).get("id")
        except Exception:  # noqa: BLE001
            _cpid = None
        _cls = classify_interruption(sess, _cpid) or {
            "effect": "unknown_effect", "executed": 0, "checkpoint": _cpid}
        try:
            sess["interrupted"] = {
                "effect": _cls["effect"], "executed": _cls["executed"],
                "checkpoint": _cls["checkpoint"], "at": round(time.time(), 3)}
            save_session(sess)
        except Exception:  # noqa: BLE001 — the record is best-effort
            pass
        if _cls["effect"] == "interrupted_before_effect":
            _notice = ("previous turn was interrupted by a service restart "
                       "before it executed anything — the harness resumes it "
                       "automatically when it can (look for [Harness restart] "
                       "below); if nothing follows, send a new message to continue.")
        else:
            _notice = ("previous turn was interrupted by a service restart "
                       "— the harness resumes it automatically when it can (look "
                       "for [Harness restart] below); if nothing follows, send a "
                       "new message to continue.")
        try:
            append_message(
                sess, "assistant",
                ERROR_PREFIX + _notice,
                meta={"error": True, "error_detail": "interrupted-by-restart",
                      "interrupted": True,
                      "interrupt_effect": _cls["effect"]})
            # also release progress left 'doing' by the killed turn, so the panel
            # does not show a phantom active step.
            try:
                from longrun.plan import taskgraph
                g = taskgraph.load(sid)
                if g:
                    for n in list(g.get("nodes", [])):
                        if n.get("status") == "doing":
                            taskgraph.update_node(g, n["id"], status="todo")
                    # 2026-11-15 (operator): "resilience on any restart … task
                    # shall not be abandoned". The restart is the one case where
                    # the turn never reaches its own end-of-turn bookkeeping, so
                    # the record is written HERE: the next turn opens with the
                    # exact steps the restart interrupted, and with the reason.
                    taskgraph.note_turn_end(taskgraph.load(sid) or g,
                                            reason="restart")
            except Exception:  # noqa: BLE001
                pass
            publish("session.reconciled", session=sid, reason="orphan_user_turn")
            fixed += 1
        except Exception:  # noqa: BLE001 — recovery must never block startup
            continue
    return fixed

