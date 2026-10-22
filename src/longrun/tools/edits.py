#!/usr/bin/env python3
"""Longrun file-edit journal — per-run change tracking, diff and undo (JAG-127).

Every harness `fs.write` / `fs.edit` records the file's PRE-IMAGE (content before
the change) here, keyed by the run/session id the tools already receive. From
that journal the UI can show an IDE-style change summary:

    created 2 (+200) · edited 3 (+40 −26)

open a real side-by-side (before → after) diff for one file, and UNDO it
(restore the pre-image; a file the agent CREATED is removed).

Storage: data/edits/<key>.json  (append-only list, capped). Override with
LONGRUN_EDITS_DIR (tests).
"""

import difflib
import json
import os
import re
import threading
import time

from longrun.util import paths
from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO
MAX_ENTRIES = 500
MAX_TEXT = 200_000     # cap the pre/post image kept per edit
MAX_ROWS = 6000        # cap diff rows returned

_lock = threading.RLock()


def _dir():
    return os.environ.get("LONGRUN_EDITS_DIR") or os.path.join(paths.DATA_DIR, "edits")


def _key_file(key):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key or "default"))[:120] or "default"
    return os.path.join(_dir(), safe + ".json")


def _load(key):
    try:
        with open(_key_file(key), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — a bad journal must not break a write
        return []


def _save(key, entries):
    write_json(_key_file(key), entries, indent=None)


def _counts(before, after):
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""))
    add = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    dele = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    return add, dele


def record(key, path, before, after, action="modified"):
    """Append one edit. `before`/`after` are the text content around the change."""
    if before == after:
        return {"ok": False, "reason": "no change"}
    before = "" if before is None else str(before)
    after = "" if after is None else str(after)
    add, dele = _counts(before, after)
    entry = {
        "ts": round(time.time(), 3),
        "path": path,
        "action": "created" if action == "created" else "modified",
        "add": add,
        "del": dele,
        "before": before[:MAX_TEXT],
        "after": after[:MAX_TEXT],
        "truncated": len(before) > MAX_TEXT or len(after) > MAX_TEXT,
    }
    with _lock:
        entries = _load(key)
        entries.append(entry)
        _save(key, entries[-MAX_ENTRIES:])
    try:
        from longrun.core import server
        server.publish("edits.recorded", key=key, path=path, action=entry["action"],
                       add=add, deleted=dele)
    except Exception:  # noqa: BLE001 — the feed must never break a write
        pass
    return {"ok": True, "add": add, "del": dele, "action": entry["action"]}


def entries(key):
    """JAG-426: the raw journal entries for a key (oldest first), read-only."""
    return _load(key)


def drop_after(key, upto_ts):
    """JAG-426: drop the entries a rewind just unwound (ts > upto_ts).

    The journal is append-only, so a time-bounded cut is the correct way to keep
    the pre-rewind history while clearing what the rewind invalidated. Returns the
    number of entries kept.
    """
    with _lock:
        rows = _load(key)
        keep = [e for e in rows if float(e.get("ts") or 0) <= float(upto_ts or 0)]
        _save(key, keep)
        return len(keep)


def summary(key):
    """Per-file aggregate + totals for an IDE-style change summary.

    JAG-127: each file's `add`/`del` is the NET of its first pre-image vs its
    last post-image (the same numbers the diff modal shows), not the sum of every
    intermediate edit — so the chip, the Changes list and the diff always agree.
    """
    with _lock:
        entries = _load(key)
    per, order = {}, []
    for x in entries:
        p = x["path"]
        if p not in per:
            per[p] = {"path": p, "action": x["action"], "add": 0, "del": 0,
                      "edits": 0, "first_ts": x["ts"], "last_ts": x["ts"],
                      "_before": x["before"], "_after": x["after"]}
            order.append(p)
        per[p]["edits"] += 1
        per[p]["last_ts"] = x["ts"]
        per[p]["_after"] = x["after"]
        if x["action"] == "created":
            per[p]["action"] = "created"
    files = []
    for p in order:
        f = per[p]
        f["add"], f["del"] = _counts(f.pop("_before"), f.pop("_after"))
        files.append(f)
    files.sort(key=lambda f: f["last_ts"], reverse=True)
    totals = {
        "files": len(files),
        "created": sum(1 for f in files if f["action"] == "created"),
        "modified": sum(1 for f in files if f["action"] == "modified"),
        "add": sum(f["add"] for f in files),
        "del": sum(f["del"] for f in files),
    }
    return {"key": key, "files": files, "totals": totals, "count": len(entries)}


def _rows(a, b):
    """Aligned left/right rows from two texts (difflib opcodes)."""
    a_lines, b_lines = a.splitlines(), b.splitlines()
    sm = difflib.SequenceMatcher(None, a_lines, b_lines)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"l": a_lines[i1 + k], "r": b_lines[j1 + k], "t": "ctx"})
        elif tag == "replace":
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                rows.append({"l": a_lines[i1 + k] if i1 + k < i2 else "",
                             "r": b_lines[j1 + k] if j1 + k < j2 else "", "t": "chg"})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"l": a_lines[k], "r": "", "t": "del"})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"l": "", "r": b_lines[k], "t": "add"})
        if len(rows) > MAX_ROWS:
            rows = rows[:MAX_ROWS]
            rows.append({"l": "…", "r": "…", "t": "ctx"})
            break
    return rows


def diff(key, path):
    """The full before→after view for one file (first pre-image vs last post-image)."""
    with _lock:
        entries = [_x for _x in _load(key) if _x["path"] == path]
    if not entries:
        return {"error": "no edits recorded for %s" % path}
    before, after = entries[0]["before"], entries[-1]["after"]
    add, dele = _counts(before, after)
    return {"key": key, "path": path, "action": entries[0]["action"],
            "add": add, "del": dele, "edits": len(entries),
            "truncated": any(e.get("truncated") for e in entries),
            "rows": _rows(before, after)}


def undo(key, path=None):
    """Restore files to their FIRST pre-image (a created file is removed)."""
    with _lock:
        entries = _load(key)
        if not entries:
            return {"ok": False, "error": "nothing to undo"}
        targets = [path] if path else sorted({e["path"] for e in entries})
        restored, errors = [], []
        for p in targets:
            pe = [e for e in entries if e["path"] == p]
            if not pe:
                continue
            first = pe[0]
            try:
                if first["action"] == "created":
                    if os.path.isfile(p):
                        os.remove(p)
                    restored.append({"path": p, "action": "removed"})
                else:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(first["before"])
                    restored.append({"path": p, "action": "restored"})
            except OSError as e:
                errors.append({"path": p, "error": str(e)})
        keep = [e for e in entries if e["path"] not in set(targets)]
        _save(key, keep)
    try:
        from longrun.core import server
        server.publish("edits.undone", key=key, restored=len(restored))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "restored": restored, "errors": errors}


def approve(key, path=None):
    """ACCEPT changes: drop the pending entries WITHOUT touching the files (JAG-275).

    The review flow: a change stays PENDING in the journal until the operator
    either APPROVES it (keep the file as written, forget the entry) or REJECTS it
    (`undo` -> restore the pre-image / remove a created file). Approving never
    modifies the file; it only consumes the pending diff so the list does not
    grow forever. `path=None` approves every pending file at once.
    """
    with _lock:
        entries = _load(key)
        if not entries:
            return {"ok": False, "error": "nothing to approve"}
        targets = [path] if path else sorted({e["path"] for e in entries})
        keep = [e for e in entries if e["path"] not in set(targets)]
        _save(key, keep)
    try:
        from longrun.core import server
        server.publish("edits.approved", key=key, approved=len(targets))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "approved": targets}


def clear(key):
    with _lock:
        _save(key, [])
    return {"ok": True}

