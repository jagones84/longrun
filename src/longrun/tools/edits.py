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
import posixpath
import re
import threading
import time
from typing import Any

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
    # The post-write stat is the cheap fingerprint of "the disk still holds what
    # the journal says": summary() compares it before reading a single byte.
    try:
        st = os.stat(path)
        entry["after_stat"] = [int(st.st_mtime_ns), int(st.st_size)]
    except OSError:
        entry["after_stat"] = None
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


def _disk_state(path, entry):
    """Does the file on disk still match what the journal last recorded?

    Returns `(state, text)` with state `clean` | `changed` | `missing`. `text` is
    the file as it is now, and is only returned when it differs AND can be
    compared (a truncated journal image cannot be diffed honestly, so the caller
    keeps the recorded counts instead of inventing new ones). The stat stored by
    `record()` makes the common case one `stat()` call and no read.
    """
    try:
        st = os.stat(path)
    except OSError:
        return "missing", None
    ref = (entry or {}).get("after_stat")
    if isinstance(ref, (list, tuple)) and len(ref) == 2:
        try:
            if [int(st.st_mtime_ns), int(st.st_size)] == [int(ref[0]), int(ref[1])]:
                return "clean", None
        except (TypeError, ValueError):
            pass
    if (entry or {}).get("truncated"):
        return "changed", None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_TEXT + 1)
    except OSError:
        return "missing", None
    return ("clean", None) if text == entry.get("after", "") else ("changed", text)


def summary(key):
    """Per-file aggregate + totals for an IDE-style change summary.

    JAG-127: each file's `add`/`del` is the NET of its first pre-image vs its
    last post-image (the same numbers the diff modal shows), not the sum of every
    intermediate edit — so the chip, the Changes list and the diff always agree.

    The list is reconciled with the DISK on every read: a file edited outside the
    harness (the editor dock, another agent, an external editor) reports
    `disk: "changed"` and its counts describe the file as it is NOW; a deleted
    file reports `disk: "missing"`. The journal is still the source of each
    file's pre-image (that is what makes reject possible), but it never claims a
    state the workspace no longer has.
    """
    with _lock:
        entries = _load(key)
    per, order = {}, []
    for x in entries:
        p = x["path"]
        if p not in per:
            per[p] = {"path": p, "action": x["action"], "add": 0, "del": 0,
                      "edits": 0, "first_ts": x["ts"], "last_ts": x["ts"],
                      "_before": x["before"], "_after": x["after"], "_last": x}
            order.append(p)
        per[p]["edits"] += 1
        per[p]["last_ts"] = x["ts"]
        per[p]["_after"] = x["after"]
        per[p]["_last"] = x
        if x["action"] == "created":
            per[p]["action"] = "created"
    files = []
    for p in order:
        f = per[p]
        before, after = f.pop("_before"), f.pop("_after")
        f["add"], f["del"] = _counts(before, after)
        f["disk"], disk_text = _disk_state(p, f.pop("_last"))
        if disk_text is not None:
            f["add"], f["del"] = _counts(before, disk_text)
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


def _canonical_path(path: str) -> str:
    """Normalize a journal path's separators and dot segments."""
    return posixpath.normpath(str(path or "").replace("\\", "/"))


def _is_absolute_path(path: str) -> bool:
    """Recognize POSIX and Windows absolute paths after separator normalization."""
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:/", path))


def diff(key: str, path: str) -> dict[str, Any]:
    """The full before→after view for one file (first pre-image vs last post-image)."""
    requested_path = str(path or "")
    canonical_request = _canonical_path(requested_path)
    with _lock:
        journal = _load(key)
        entries = [
            item for item in journal
            if _canonical_path(item.get("path", "")) == canonical_request
        ]
        if not entries and not _is_absolute_path(canonical_request):
            relative_path = canonical_request
            parts = relative_path.split("/")
            if "/" in relative_path and ".." not in parts:
                suffix = "/" + relative_path
                matches = [
                    item for item in journal
                    if _canonical_path(item.get("path", "")).endswith(suffix)
                ]
                matched_paths = {
                    _canonical_path(item.get("path", "")) for item in matches
                }
                if len(matched_paths) > 1:
                    return {
                        "error": "ambiguous edit path %s (%d journal paths)"
                        % (requested_path, len(matched_paths))
                    }
                entries = matches
    if not entries:
        return {"error": "no edits recorded for %s" % requested_path}
    before, after = entries[0]["before"], entries[-1]["after"]
    # Same disk reconciliation as summary(): the diff's RIGHT column is the file
    # as it is now, so an edit made outside the harness cannot be hidden behind a
    # stale recorded image. A file that no longer exists keeps the recorded image
    # — the same choice summary() makes — and is labelled `missing` instead, so
    # the list and the diff can never report different counts for one file.
    disk, disk_text = _disk_state(entries[-1]["path"], entries[-1])
    if disk_text is not None:
        after = disk_text
    add, dele = _counts(before, after)
    return {"key": key, "path": requested_path, "action": entries[0]["action"],
            "add": add, "del": dele, "edits": len(entries), "disk": disk,
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


# ---------------------------------------------------------------------------
# MyArtifacts — the same journal, read as one cross-session index of what the
# harness produced. No second store: a file is an artifact because a journal
# recorded it, so the page and the Workspace change list can never disagree.
# ---------------------------------------------------------------------------

#: Suffix → the group the page shows it under. `plan.artifacts.DELIVERABLE_EXTS`
#: is NOT reused: that list exists to GRADE a turn and deliberately excludes
#: code and images, which are exactly what a "my artifacts" page must show.
ARTIFACT_KINDS = (
    ("document", (".md", ".markdown", ".txt", ".rst", ".pdf", ".doc", ".docx",
                  ".odt", ".rtf", ".pptx", ".ppt", ".html", ".htm")),
    ("data", (".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".json", ".jsonl", ".xml",
              ".yaml", ".yml", ".db", ".sqlite", ".parquet")),
    ("image", (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif",
               ".ico", ".tiff")),
    ("code", (".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".sh", ".bash",
              ".ps1", ".sql", ".go", ".rs", ".java", ".rb", ".php", ".css", ".scss",
              ".c", ".h", ".cpp", ".hpp", ".swift", ".kt")),
    ("media", (".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a")),
)
MAX_ARTIFACT_JOURNALS = 400


def kind_of(path):
    """The artifact group a produced file belongs to (`other` when unknown)."""
    suffix = os.path.splitext(str(path or ""))[1].lower()
    for kind, exts in ARTIFACT_KINDS:
        if suffix in exts:
            return kind
    return "other"


def _journal_keys():
    """Every journal key present on disk, the most recently written first."""
    try:
        names = [n for n in os.listdir(_dir()) if n.endswith(".json")]
    except OSError:
        return []
    rows = []
    for name in names:
        p = os.path.join(_dir(), name)
        try:
            rows.append((os.path.getmtime(p), name[:-5]))
        except OSError:
            continue
    rows.sort(reverse=True)
    return [key for _mtime, key in rows]


def artifacts(limit=500, session=None, kind=None, query=None):
    """One row per (session, path) the harness produced, newest first.

    Fields: `session`, `path`, `name`, `kind`, `action` (created|modified),
    `edits` (how many journal entries name it), `ts` (last write), `size` and
    `exists` (read from the disk NOW — a card never claims a file that is gone).
    """
    limit = max(1, min(2000, int(limit or 500)))
    keys = [str(session)] if session else _journal_keys()[:MAX_ARTIFACT_JOURNALS]
    needle = str(query or "").strip().lower()
    rows = {}
    for key in keys:
        for e in _load(key):
            path = str(e.get("path") or "")
            if not path:
                continue
            k = kind_of(path)
            if kind and kind != "all" and k != kind:
                continue
            if needle and needle not in path.lower():
                continue
            rec = rows.get((key, path))
            if rec is None:
                rec = {"session": key, "path": path, "name": os.path.basename(path),
                       "kind": k, "action": e.get("action") or "modified",
                       "edits": 0, "ts": 0.0}
                rows[(key, path)] = rec
            rec["edits"] += 1
            rec["ts"] = max(rec["ts"], float(e.get("ts") or 0.0))
            if e.get("action") == "created":
                rec["action"] = "created"
    out = list(rows.values())
    for rec in out:
        try:
            rec["size"], rec["exists"] = int(os.path.getsize(rec["path"])), True
        except OSError:
            rec["size"], rec["exists"] = 0, False
    out.sort(key=lambda r: r["ts"], reverse=True)
    kinds = {}
    for rec in out:
        kinds[rec["kind"]] = kinds.get(rec["kind"], 0) + 1
    return {"artifacts": out[:limit], "count": len(out), "kinds": kinds}
