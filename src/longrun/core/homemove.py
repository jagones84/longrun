#!/usr/bin/env python3
"""Move the user's data home, with progress (JAG-533).

User state (sessions, events, indexes, costs, the self-evolution runtime) must
live OUTSIDE the harness checkout: the repo is replaced by `git pull`, may be
read-only, and is world-readable in a container. `util.paths` resolves the root;
this module is the ONE place allowed to MOVE it.

A move is deliberately paranoid, because the failure mode is losing a chat
history:

  1. refuse a target inside the repository or inside the current data dir;
  2. COPY (never rename across filesystems), building the tree first;
  3. verify the copied file count, then delete the source only on a match;
  4. persist `data_home` in config.json LAST, so a crash mid-copy leaves the
     server pointing at data that still exists.

`status()` is polled by the Settings panel: `phase` is scanning|copied|copying|
done|error, with byte progress for the progress bar.
"""
import os
import shutil
import threading
import time

from longrun.util import paths
from longrun.util.fswrite import write_json

_lock = threading.RLock()
_state = {"phase": "idle", "done": 0, "total": 0, "files": 0, "copied": 0,
          "source": "", "target": "", "error": None, "started": None,
          "finished": None, "removed_source": False, "restart_required": False}


def status():
    """A copy of the move state (safe to serialise)."""
    with _lock:
        out = dict(_state)
    total = out.get("total") or 0
    out["pct"] = (round(100.0 * (out.get("done") or 0) / total, 1) if total else
                  (100.0 if out.get("phase") == "done" else 0.0))
    return out


def _set(**kw):
    with _lock:
        _state.update(kw)


def _walk(source):
    """(total_bytes, file_count) under `source`."""
    total = files = 0
    for root, _dirs, names in os.walk(source):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
            files += 1
    return total, files


def _inside(path, parent):
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(parent)
        return p == r or p.startswith(r + os.sep)
    except OSError:
        return False


def validate(target):
    """`{ok, error?}` for a candidate data home (no filesystem writes)."""
    t = str(target or "").strip()
    if not t:
        return {"ok": False, "error": "path required"}
    t = os.path.abspath(os.path.expanduser(t))
    if _inside(t, paths.REPO_ROOT):
        return {"ok": False,
                "error": "the data home cannot live inside the harness repository "
                         "(%s)" % paths.REPO_ROOT}
    if _inside(t, paths.DATA_DIR) or _inside(paths.DATA_DIR, t):
        return {"ok": False, "error": "that path overlaps the CURRENT data dir"}
    parent = os.path.dirname(t)
    if not os.path.isdir(parent):
        return {"ok": False, "error": "parent folder does not exist: %s" % parent}
    return {"ok": True, "home": t}


def _copy_tree(source, dest, on_bytes):
    """Copy every entry under `source` into `dest`; returns files copied."""
    copied = 0
    for root, _dirs, names in os.walk(source):
        rel = os.path.relpath(root, source)
        out = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(out, exist_ok=True)
        for n in names:
            src = os.path.join(root, n)
            try:
                shutil.copy2(src, os.path.join(out, n))
            except OSError:
                continue          # a locked/vanished file must not abort the move
            copied += 1
            try:
                on_bytes(os.path.getsize(src))
            except OSError:
                on_bytes(0)
    return copied


def _merge_move(old, new):
    """Move `old` into `new`, merging when `new` already exists.

    The target home often already has an (empty) `matrix/` or `workspaces/`
    created at startup, so a plain rename would fail and strand the old tree.
    """
    if not os.path.isdir(old) or _inside(old, new):
        return
    try:
        if not os.path.exists(new):
            shutil.move(old, new)
            return
        for name in os.listdir(old):
            src, dst = os.path.join(old, name), os.path.join(new, name)
            if not os.path.exists(dst):
                shutil.move(src, dst)
    except OSError:
        pass


def _run(source_data, target_home, remove_source, move_matrix, move_workspaces):
    """The worker: copy, verify, delete the source, then persist the choice."""
    try:
        _set(phase="scanning", done=0, total=0, copied=0, error=None,
             started=time.time(), removed_source=False, restart_required=False)
        total, files = _walk(source_data)
        _set(phase="copying", total=total, files=files)
        dest = os.path.join(target_home, "data")
        os.makedirs(dest, exist_ok=True)
        last = [0.0]

        def _on_bytes(n):
            done = (_state.get("done") or 0) + n
            _set(done=done, copied=(_state.get("copied") or 0) + 1)
            now = time.time()
            if now - last[0] > 0.2:      # throttle the event storm
                last[0] = now
                _publish("copying")

        copied = _copy_tree(source_data, dest, _on_bytes)
        _set(phase="copied", copied=copied)
        if copied < files:
            _set(phase="error",
                 error="copied %d of %d files — nothing was deleted, the source is "
                       "still authoritative" % (copied, files))
            return
        old_home = os.path.dirname(source_data)
        if move_matrix:
            # The repo-root `.Matrix` is the pre-JAG-533 location; `<old home>/matrix`
            # is where it lives now. Both must follow the data home.
            _merge_move(os.path.join(paths.REPO_ROOT, ".Matrix"),
                        os.path.join(target_home, "matrix"))
            _merge_move(os.path.join(old_home, "matrix"),
                        os.path.join(target_home, "matrix"))
        # JAG-534: the operator's PROJECTS live in `<home>/workspaces` too; a
        # home move that left them behind would orphan every default workspace.
        if move_workspaces:
            _merge_move(os.path.join(old_home, "workspaces"),
                        os.path.join(target_home, "workspaces"))
        # The copy IS the user's data now, so the choice is persisted BEFORE the
        # source is touched: a delete that hits a root-owned file (seen on the DGX:
        # a Root-owned `uname.txt` inside a sandbox dir) must never leave the
        # server pointing at a half-deleted tree.
        cfg = paths.read_config()
        cfg["data_home"] = target_home
        write_json(paths.config_file(), cfg)
        removed = False
        warning = None
        if remove_source and not _inside(source_data, target_home):
            try:
                shutil.rmtree(source_data)
                removed = True
            except OSError as e:
                warning = ("the new copy is COMPLETE and active, but part of the old "
                           "data dir could not be removed (%s) — delete it manually"
                           % e)
        _set(phase="done", removed_source=removed, restart_required=True,
             finished=time.time(), error=warning)
        _publish("done")
    except Exception as e:  # noqa: BLE001 — the UI must SEE the failure
        _set(phase="error", error=str(e), finished=time.time())
        _publish("error")


def _publish(phase):
    """Emit a `home.move` event so any open WebUI follows the move live."""
    try:
        from longrun.core.events import publish
        st = status()
        publish("home.move", phase=phase, pct=st["pct"], done=st["done"],
                total=st["total"], copied=st["copied"], files=st["files"],
                error=st["error"])
    except Exception:  # noqa: BLE001 — progress reporting is best-effort
        pass


def start(target, remove_source=True, move_matrix=True, move_workspaces=True):
    """Begin a move in the background. Returns the initial status/validation."""
    v = validate(target)
    if not v.get("ok"):
        return v
    with _lock:
        if _state.get("phase") in ("scanning", "copying"):
            return {"ok": False, "error": "a move is already running"}
    source_data = paths.DATA_DIR
    if not os.path.isdir(source_data):
        return {"ok": False, "error": "current data dir does not exist: %s" % source_data}
    _set(source=source_data, target=v["home"])
    threading.Thread(target=_run,
                     args=(source_data, v["home"], bool(remove_source),
                           bool(move_matrix), bool(move_workspaces)),
                     daemon=True, name="home-move").start()
    return {"ok": True, "started": True, "source": source_data, "target": v["home"]}


def restart_supervised():
    """Restart the server when a supervisor owns it (systemd/docker), else refuse.

    A manual `python server.py` has nothing to come back, so exiting would just
    kill the harness: in that case the UI tells the operator to restart.
    """
    supervised = bool(os.environ.get("INVOCATION_ID") or
                      os.environ.get("LONGRUN_SUPERVISED"))
    if not supervised:
        return {"ok": False,
                "error": "not supervised — restart the server manually to apply"}
    threading.Timer(0.4, lambda: os._exit(3)).start()
    return {"ok": True, "restarting": True}
