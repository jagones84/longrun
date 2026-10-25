"""Shared atomic JSON helpers for the harness stores.

Single source of truth for reading and writing JSON state so every store
handles a crash (or concurrent writers) the same way: a UNIQUE temp file in the
target directory + ``os.replace``. A fixed ``<path>.tmp`` collides when two
threads write the same file at once — the first ``os.replace`` renames the tmp
away and the second raises ``FileNotFoundError`` (JAG-201 for transcripts,
JAG-287 for task graphs). Before this module each store re-implemented its own
variant, and some still used the racy fixed-name tmp.

Stdlib-only and imports nothing from the rest of the package, so it can never
create an import cycle.
"""

import json
import os
import uuid


def read_json(path, default=None):
    """Return the JSON document at ``path``, or ``default`` on any read/parse error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def read_registry(path, **defaults):
    """Read the JSON registry at ``path`` and guarantee its top-level keys exist.

    Every registry (agents, jobs, routines, teams) is a plain ``{...: {}, "seq": 0}``
    document whose readers must survive a missing or corrupt file AND a document
    written by an older version. ``read_registry(FILE, agents={}, seq=0)`` is that
    contract in one place instead of four slightly different copies (JAG-483).
    """
    d = read_json(path, None)
    d = d if isinstance(d, dict) else {}
    for k, v in defaults.items():
        d.setdefault(k, v)
    return d


def retract_seq(d, key):
    """Pull a registry counter back to the highest LIVE record number.

    Deletes pop the record but never touched ``seq``, so A/J/R/T numbers grew
    forever (delete 50 agents, the next is still A51 — then A10000). Retracting
    to ``max(live n)`` means: deleting everything restarts at 1; deleting the
    top pulls the counter back; deleting from the middle changes nothing.
    Existing ids are never touched, so no live id is ever reused — only the
    counter stops running away. Call it inside the store lock after any pop.
    """
    try:
        live = [int((r or {}).get("n") or 0)
                for r in (d.get(key) or {}).values()]
    except (TypeError, ValueError):
        return d
    d["seq"] = max(live + [0])
    return d


def write_json(path, obj, *, indent=2, ensure_ascii=False, sort_keys=False):
    """Atomically write ``obj`` as JSON to ``path``.

    Writes to a unique ``<path>.<uuid>.tmp`` in the same directory, then
    ``os.replace`` it onto the target so a reader never sees a half-written
    file. The unique temp name is deliberate — see the module docstring.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_text(path, text):
    """Atomically write ``text`` (UTF-8) to ``path`` using a unique temp file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    body = text if isinstance(text, str) else ("" if text is None else str(text))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def safe_id(val, default="unknown", max_len=96):
    """Sanitize ``val`` into a safe filename token (alnum + ``._-``)."""
    s = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(val or default))[:max_len]
    return s or default


def path_under(path, root):
    """Return True when ``path`` resolves inside ``root`` (both realpath'd)."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
        return p == r or p.startswith(r + os.sep)
    except Exception:  # noqa: BLE001
        return False
